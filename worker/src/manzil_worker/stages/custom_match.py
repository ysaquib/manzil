"""CUSTOM_MATCH: deterministic dispatch for Hunt custom Criteria (DESIGN §10.9)."""

from __future__ import annotations

import json
from typing import Any, Literal

import jsonschema
import structlog
from manzil_shared.errors import AgentBudgetExceeded, StageRetryable
from manzil_shared.models import Confidence, RequiresTool, TargetScope, UnitApplicability
from pydantic import BaseModel, Field, ValidationError

from manzil_worker.enrich.maps import commute_time, geocode, places_nearby
from manzil_worker.llm.config import model_for_stage
from manzil_worker.llm.prompt_loader import load_prompt
from manzil_worker.llm.tools import ToolContext, tool_context
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState, SourceClaim, StageWarning

log = structlog.get_logger()


class _TextResult(BaseModel):
    target: str
    value: Any = None
    confidence: Literal["high", "medium", "low", "not_found"]
    source_url: str | None = None
    evidence_quote: str | None = None


class _TextBatch(BaseModel):
    results: list[_TextResult] = Field(default_factory=list)


class _MapsResult(BaseModel):
    value: Any = None
    confidence: Literal["high", "medium", "low", "not_found"]
    evidence: str | None = None


def _json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1].rsplit("```", 1)[0]
    value = json.loads(stripped)
    if not isinstance(value, dict):
        raise ValueError("final answer must be a JSON object")
    return value


def _active_customs(state: RunState, ctx: StageCtx):
    selected = set(state.custom_criterion_keys)
    for criterion in ctx.rubric:
        custom = criterion.custom_def
        if custom is None or (selected and custom.key not in selected):
            continue
        if state.job_type.value == "refresh" and state.refresh_fields and not selected:
            if custom.requires_tool is None and "listing_details" not in state.refresh_fields:
                continue
            if custom.requires_tool is RequiresTool.MAPS and "location" not in state.refresh_fields:
                continue
        yield custom


def _targets(state: RunState, scope: str) -> dict[str, tuple[str | None, str | None]]:
    if scope == "property":
        return {"property": (None, None)}
    targets: dict[str, tuple[str | None, str | None]] = {}
    for index, plan in enumerate(state.floor_plans):
        ref = plan.response_key or f"plan-{index}"
        source_url = plan.source_url or (state.sources[0].url if state.sources else state.url)
        targets[f"{source_url}#{ref}"] = (source_url, ref)
    return targets


def _validate_known(value: Any, schema: dict[str, Any]) -> None:
    try:
        jsonschema.validate(instance=value, schema=schema)
    except jsonschema.ValidationError as error:
        raise StageRetryable(f"CUSTOM_MATCH value violates its schema: {error.message}") from error


async def _text_claims(state: RunState, ctx: StageCtx, custom) -> list[SourceClaim]:
    targets = _targets(state, custom.fact_scope)
    content = json.dumps(
        {
            "criterion": custom.model_dump(mode="json"),
            "targets": list(targets),
            "sources": [
                {"url": source.url, "text": source.cleaned_text}
                for source in state.sources
                if source.cleaned_text
            ],
        },
        sort_keys=True,
    )
    batch = await ctx.call_structured("custom_match", _TextBatch, content)
    by_target = {item.target: item for item in batch.results}
    if len(by_target) != len(batch.results) or set(by_target) != set(targets):
        raise StageRetryable("CUSTOM_MATCH must return every requested target exactly once")
    source_text = {source.url: source.cleaned_text for source in state.sources}
    claims: list[SourceClaim] = []
    for target, (target_source, floor_plan_ref) in targets.items():
        item = by_target[target]
        confidence = Confidence(item.confidence)
        value = item.value
        evidence = item.evidence_quote
        source_url = item.source_url
        if confidence is Confidence.NOT_FOUND or value is None:
            confidence = Confidence.NOT_FOUND
            value = None
            evidence = None
            source_url = target_source
        else:
            _validate_known(value, custom.value_schema)
            if (
                source_url not in source_text
                or not evidence
                or evidence not in source_text[source_url]
            ):
                raise StageRetryable("CUSTOM_MATCH known value lacks verbatim Source evidence")
            if target_source is not None and source_url != target_source:
                raise StageRetryable("Floor Plan custom evidence must be Source-local")
        claim = SourceClaim(
            criterion_key=custom.key,
            value=value,
            confidence=confidence,
            evidence_quote=evidence,
            source_id=source_url,
            model=model_for_stage("custom_match"),
            prompt_version=load_prompt("custom_match").version,
            target_scope=(
                TargetScope.PROPERTY if custom.fact_scope == "property" else TargetScope.FLOOR_PLAN
            ),
            floor_plan_ref=floor_plan_ref,
            applicability=(
                None if custom.fact_scope == "property" else UnitApplicability.SPECIFIC_FLOOR_PLANS
            ),
            origin_key=f"custom_match:text:{custom.key}",
            resolution_rule="custom_match_text",
        )
        claim.candidate_claim_group_ids = [claim.claim_group_id]
        claims.append(claim)
    return claims


async def _maps_claim(state: RunState, ctx: StageCtx, custom) -> SourceClaim:
    task = json.dumps(
        {
            "criterion": custom.model_dump(mode="json"),
            "property": {
                "lat": state.geocode.lat if state.geocode else None,
                "lng": state.geocode.lng if state.geocode else None,
                "address": (state.property_identity.address if state.property_identity else None),
            },
        },
        sort_keys=True,
    )
    with tool_context(ToolContext(event_sink=ctx.tool_event_sink)):
        result = await ctx.call_agent(
            "custom_match_location",
            task,
            [geocode, places_nearby, commute_time],
            8,
        )
    parsed = _MapsResult.model_validate(_json_object(result.final_text))
    confidence = Confidence(parsed.confidence)
    value = parsed.value
    if confidence is Confidence.NOT_FOUND or value is None:
        confidence = Confidence.NOT_FOUND
        value = None
    else:
        _validate_known(value, custom.value_schema)
    claim = SourceClaim(
        criterion_key=custom.key,
        value=value,
        confidence=confidence,
        evidence_quote=parsed.evidence,
        source_id=None,
        model=model_for_stage("custom_match_location"),
        prompt_version=load_prompt("custom_match_location").version,
        target_scope=TargetScope.PROPERTY,
        origin_key=f"custom_match:maps:{custom.key}",
        resolution_rule="custom_match_maps",
    )
    claim.candidate_claim_group_ids = [claim.claim_group_id]
    return claim


async def custom_match_stage(state: RunState, ctx: StageCtx) -> RunState:
    claims: list[SourceClaim] = []
    warnings: list[StageWarning] = []
    for custom in _active_customs(state, ctx):
        try:
            if custom.requires_tool is None:
                claims.extend(await _text_claims(state, ctx, custom))
            elif custom.requires_tool is RequiresTool.MAPS:
                claims.append(await _maps_claim(state, ctx, custom))
        except (AgentBudgetExceeded, ValidationError, ValueError, json.JSONDecodeError) as error:
            warnings.append(
                StageWarning(
                    stage="CUSTOM_MATCH",
                    code="custom_match_unavailable",
                    message=f"{custom.label} could not be evaluated; prior truth was preserved.",
                    detail={"criterion_key": custom.key, "error": str(error)},
                )
            )
            log.warning("custom_match_unavailable", criterion_key=custom.key, error=str(error))
    state.custom_claims = claims
    state.replace_warnings("CUSTOM_MATCH", warnings)
    return state
