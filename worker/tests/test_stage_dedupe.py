"""P3-4: DEDUPE stage — one unit test per decision branch (DESIGN §10.3).

Everything the stage touches is injected through StageCtx seams, so these run
with no database and no Google (AGENTS.md: no live calls, ever). The geocode seam
is a plain fake; a fake raising `MapsError` exercises the outage path.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from manzil_shared.errors import CheckpointRaised
from manzil_shared.models import CheckpointKind, JobType
from manzil_worker.enrich.maps import MapsError
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.dedupe import dedupe_stage
from manzil_worker.state import DedupeCandidate, GeocodeIn, PropertyIdentityIn, RunState

# geocode centre + a candidate ~55 m north (within 100 m) and ~1.1 km north (out).
CENTER = GeocodeIn(place_id="place-here", lat=42.0000, lng=-83.0000, formatted_address="here")
NEAR_LAT, FAR_LAT = 42.0005, 42.0100


def _state(
    *, name: str | None = None, address: str | None = "1 Main St", property_id=None
) -> RunState:
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url="https://x.test/1")
    if property_id is not None:
        state.property_id = property_id
    if name is not None or address is not None:
        state.property_identity = PropertyIdentityIn(name=name, address=address)
    return state


def _geocode_seam(result: GeocodeIn | Exception, calls: list[str] | None = None):
    async def seam(address: str) -> GeocodeIn:
        if calls is not None:
            calls.append(address)
        if isinstance(result, Exception):
            raise result
        return result

    return seam


def _ctx(*, candidates=None, geocode: GeocodeIn | Exception = CENTER, calls=None) -> StageCtx:
    async def candidates_seam() -> list[DedupeCandidate]:
        return list(candidates or [])

    return StageCtx(
        dedupe_candidates=candidates_seam,
        geocode_address=_geocode_seam(geocode, calls),
    )


def _run(state: RunState, ctx: StageCtx) -> RunState:
    return asyncio.run(dedupe_stage(state, ctx))


# ── no-identity / no-address (never fail the job) ────────────────────────────


def test_no_identity() -> None:
    calls: list[str] = []
    state = _run(_state(name=None, address=None), _ctx(calls=calls))
    assert state.dedupe is not None and state.dedupe.action == "no_identity"
    assert calls == []  # never geocoded


def test_no_address() -> None:
    state = _run(_state(name="Maple Court Apartments", address=None), _ctx())
    assert state.dedupe is not None and state.dedupe.action == "no_address"
    assert state.geocode is None


# ── geocode outage is not a failure ──────────────────────────────────────────


def test_geocode_failed_records_and_returns() -> None:
    state = _run(
        _state(name="Maple Court Apartments"),
        _ctx(geocode=MapsError("GOOGLE_MAPS_API_KEY unset")),
    )
    assert state.dedupe is not None and state.dedupe.action == "geocode_failed"
    assert "GOOGLE_MAPS_API_KEY" in (state.dedupe.note or "")
    assert state.geocode is None


# ── candidate selection ──────────────────────────────────────────────────────


def test_no_candidates_stores_geocode() -> None:
    state = _run(_state(name="Maple Court Apartments"), _ctx(candidates=[]))
    assert state.dedupe is not None and state.dedupe.action == "no_candidates"
    # The geocode is retained (seeds the properties forever-cache at projection).
    assert state.geocode == CENTER


def test_candidates_without_coords_are_skipped() -> None:
    blind = DedupeCandidate(id=uuid4(), name="Maple Court Apartments", place_id=None)
    state = _run(_state(name="Maple Court Apartments"), _ctx(candidates=[blind]))
    assert state.dedupe is not None and state.dedupe.action == "no_candidates"


def test_self_is_excluded_from_candidates() -> None:
    own_id = uuid4()
    self_row = DedupeCandidate(
        id=own_id, name="Maple Court Apartments", lat=NEAR_LAT, lng=-83.0
    )
    state = _run(
        _state(name="Maple Court Apartments", property_id=own_id),
        _ctx(candidates=[self_row]),
    )
    assert state.dedupe is not None and state.dedupe.action == "no_candidates"


# ── merge / checkpoint / keep-separate ───────────────────────────────────────


def test_auto_merge_on_near_and_similar_name() -> None:
    cand_id = uuid4()
    near = DedupeCandidate(
        id=cand_id, name="Maple Court Apartments", lat=NEAR_LAT, lng=-83.0
    )
    state = _run(_state(name="Maple Court Apartments"), _ctx(candidates=[near]))
    assert state.property_id == cand_id  # run switched to the canonical property
    assert state.dedupe is not None and state.dedupe.action == "merged_auto"
    assert state.dedupe.candidate_property_id == str(cand_id)
    assert state.dedupe.name_similarity == 100.0
    assert state.dedupe.distance_m is not None and state.dedupe.distance_m < 100.0


def test_gray_zone_raises_resolve_dedupe_checkpoint() -> None:
    cand_id = uuid4()
    near = DedupeCandidate(
        id=cand_id,
        name="Maple Court Apts",  # token_sort_ratio 84.2 → gray zone
        canonical_address="1 Main St, Detroit, MI",
        lat=NEAR_LAT,
        lng=-83.0,
    )
    with pytest.raises(CheckpointRaised) as raised:
        _run(_state(name="Maple Court Apartments"), _ctx(candidates=[near]))

    prompt = raised.value.prompt
    assert prompt.kind is CheckpointKind.RESOLVE_DEDUPE
    assert prompt.options == ["merge", "keep_separate"]
    assert prompt.default == "keep_separate"
    assert prompt.context_ref == str(cand_id)
    assert "Maple Court Apartments" in prompt.question
    assert "Maple Court Apts" in prompt.question


def test_place_id_equal_below_gray_still_checkpoints() -> None:
    # Google says same place, names disagree (sim ~36, below gray) — genuine
    # ambiguity, so it must NOT auto-keep-separate: raise the checkpoint.
    cand_id = uuid4()
    same_place = DedupeCandidate(
        id=cand_id,
        name="Riverfront Towers",
        place_id=CENTER.place_id,  # equal place_id, no coordinates
    )
    with pytest.raises(CheckpointRaised) as raised:
        _run(_state(name="Maple Court Apartments"), _ctx(candidates=[same_place]))
    assert raised.value.prompt.kind is CheckpointKind.RESOLVE_DEDUPE
    assert raised.value.prompt.context_ref == str(cand_id)


def test_below_gray_and_different_place_keeps_separate() -> None:
    cand_id = uuid4()
    near_but_unrelated = DedupeCandidate(
        id=cand_id, name="Riverfront Towers", lat=NEAR_LAT, lng=-83.0
    )
    state = _run(
        _state(name="Maple Court Apartments"), _ctx(candidates=[near_but_unrelated])
    )
    assert state.property_id != cand_id  # not merged
    assert state.dedupe is not None and state.dedupe.action == "kept_separate"
    assert state.dedupe.candidate_property_id == str(cand_id)


def test_out_of_range_candidate_is_not_a_target() -> None:
    far = DedupeCandidate(
        id=uuid4(), name="Maple Court Apartments", lat=FAR_LAT, lng=-83.0
    )
    state = _run(_state(name="Maple Court Apartments"), _ctx(candidates=[far]))
    assert state.dedupe is not None and state.dedupe.action == "no_candidates"


# ── checkpoint answer application (resume path) ──────────────────────────────


def test_answer_merge_switches_property_without_geocoding() -> None:
    canonical = uuid4()
    calls: list[str] = []
    state = _state(name="Maple Court Apartments", property_id=uuid4())
    state.checkpoint_answer = {"choice": "merge", "context_ref": str(canonical)}
    out = _run(state, _ctx(calls=calls))

    assert out.property_id == canonical
    assert out.dedupe is not None and out.dedupe.action == "merged_user"
    assert out.checkpoint_answer is None  # consumed
    assert out.checkpoint is None
    assert calls == []  # answered path never re-geocodes


def test_answer_keep_separate_keeps_placeholder() -> None:
    placeholder = uuid4()
    canonical = uuid4()
    state = _state(name="Maple Court Apartments", property_id=placeholder)
    state.checkpoint_answer = {"choice": "keep_separate", "context_ref": str(canonical)}
    out = _run(state, _ctx())

    assert out.property_id == placeholder  # unchanged
    assert out.dedupe is not None and out.dedupe.action == "kept_separate_user"
    assert out.checkpoint_answer is None


def test_confirm_value_answer_is_not_consumed_by_dedupe() -> None:
    # A confirm_value answer (choice yes/no, criterion-key context_ref) must fall
    # through DEDUPE untouched — never routed as a merge.
    from manzil_shared.models import CheckpointPrompt

    state = _state(name=None, address=None)  # no identity → normal path returns early
    state.checkpoint = CheckpointPrompt(
        kind=CheckpointKind.CONFIRM_VALUE,
        question="Accept beds at low confidence?",
        options=["yes", "no"],
        default="yes",
        context_ref="beds",
    )
    state.checkpoint_answer = {"choice": "yes", "context_ref": "beds"}
    out = _run(state, _ctx())

    assert out.dedupe is not None and out.dedupe.action == "no_identity"
    assert out.checkpoint_answer == {"choice": "yes", "context_ref": "beds"}  # left intact
