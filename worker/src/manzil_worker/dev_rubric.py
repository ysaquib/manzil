"""Versioned development Rubric installer (P3-SC3).

This is deliberately separate from the Phase 0 eval Rubric and the ordinary
answer-driven Hunt setup. It owns one deterministic local-development Hunt,
installs the checked-in template idempotently, and refuses to erase local
Rubric edits unless the operator passes ``--force``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from manzil_shared.catalog import CATALOG
from manzil_shared.models import FloorPlan, RubricCriterion, RubricOption
from manzil_shared.scoring.engine import score
from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    import asyncpg

DEV_RUBRIC_HUNT_ID = UUID("00000000-0000-0000-0000-00000d3c0001")
DEV_RUBRIC_OWNER_ID = UUID("00000000-0000-0000-0000-00000d3c0002")
DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "dev_rubric.v1.json"


class DevRubricCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_key: str
    enabled: bool = True
    options: list[RubricOption]
    unknown_delta: float = 0.0
    position: int


class DevRubricGolden(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    effective_values: dict[str, Any]
    floor_plan: dict[str, Any]
    expected_total: float
    expected_deltas: dict[str, float]


class DevRubricTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_version: int = Field(ge=1)
    hunt_name: str
    settings: dict[str, Any]
    criteria: list[DevRubricCriterion]
    goldens: list[DevRubricGolden]

    @model_validator(mode="after")
    def validate_contract(self) -> DevRubricTemplate:
        catalog_keys = {entry.key for entry in CATALOG}
        keys = [criterion.catalog_key for criterion in self.criteria]
        if len(keys) != len(set(keys)):
            raise ValueError("development Rubric has duplicate Catalog keys")
        unknown = set(keys) - catalog_keys
        if unknown:
            raise ValueError(f"development Rubric has unknown Catalog keys: {sorted(unknown)}")
        if [criterion.position for criterion in self.criteria] != list(range(len(self.criteria))):
            raise ValueError("development Rubric positions must be contiguous from zero")
        if any(not criterion.options for criterion in self.criteria):
            raise ValueError("every development Rubric criterion needs stable options")
        return self

    def rubric(self) -> list[RubricCriterion]:
        return [
            RubricCriterion(
                hunt_id=DEV_RUBRIC_HUNT_ID,
                catalog_key=criterion.catalog_key,
                enabled=criterion.enabled,
                options=criterion.options,
                unknown_delta=criterion.unknown_delta,
                non_negotiable=None,
                is_bonus=_derive_is_bonus(criterion.options, criterion.unknown_delta),
                position=criterion.position,
            )
            for criterion in self.criteria
        ]


class DevRubricDriftError(RuntimeError):
    """The dedicated Hunt exists but no longer equals the checked-in template."""


@dataclass(frozen=True)
class DevRubricInstallResult:
    status: str
    template_version: int
    hunt_id: UUID
    criteria_count: int


def _derive_is_bonus(options: list[RubricOption], unknown_delta: float) -> bool:
    return (
        bool(options)
        and unknown_delta >= 0
        and all(option.delta >= 0 and option.dealbreaker_set_score is None for option in options)
    )


def load_dev_rubric(path: Path = DEFAULT_TEMPLATE_PATH) -> DevRubricTemplate:
    return DevRubricTemplate.model_validate_json(path.read_text())


def verify_dev_rubric_goldens(template: DevRubricTemplate) -> None:
    rubric = template.rubric()
    for golden in template.goldens:
        floor_plan = FloorPlan(
            property_id=UUID(golden.floor_plan["property_id"]),
            source_id=UUID(golden.floor_plan["source_id"]),
            plan_name=str(golden.floor_plan["plan_name"]),
            beds=int(golden.floor_plan["beds"]),
            baths=float(golden.floor_plan["baths"]),
            unit_types=list(golden.floor_plan.get("unit_types", [])),
            sqft_min=golden.floor_plan.get("sqft_min"),
            rent_min=(
                Decimal(str(golden.floor_plan["rent_min"]))
                if golden.floor_plan.get("rent_min") is not None
                else None
            ),
            availability_date=(
                date.fromisoformat(str(golden.floor_plan["availability_date"]))
                if golden.floor_plan.get("availability_date")
                else None
            ),
        )
        breakdown = score(
            rubric,
            golden.effective_values,
            floor_plan,
            rubric_version=template.template_version,
        )
        if breakdown.total != golden.expected_total:
            raise ValueError(
                f"development Rubric golden {golden.name!r}: expected total "
                f"{golden.expected_total}, got {breakdown.total}"
            )
        deltas = {criterion.key: criterion.delta for criterion in breakdown.criteria}
        if deltas != golden.expected_deltas:
            raise ValueError(
                f"development Rubric golden {golden.name!r}: expected deltas "
                f"{golden.expected_deltas}, got {deltas}"
            )


def _json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _desired_rows(template: DevRubricTemplate) -> list[dict[str, Any]]:
    return [
        {
            "catalog_key": criterion.catalog_key,
            "enabled": criterion.enabled,
            "options": [option.model_dump(mode="json") for option in criterion.options],
            "unknown_delta": float(criterion.unknown_delta),
            "non_negotiable": None,
            "is_bonus": _derive_is_bonus(criterion.options, criterion.unknown_delta),
            "position": criterion.position,
        }
        for criterion in template.criteria
    ]


def _persisted_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "catalog_key": row["catalog_key"],
            "enabled": row["enabled"],
            "options": _json(row["options"]),
            "unknown_delta": float(row["unknown_delta"]),
            "non_negotiable": _json(row["non_negotiable"])
            if row["non_negotiable"] is not None
            else None,
            "is_bonus": row["is_bonus"],
            "position": row["position"],
        }
        for row in rows
    ]


async def install_dev_rubric(
    conn: asyncpg.Connection,
    *,
    template: DevRubricTemplate | None = None,
    force: bool = False,
) -> DevRubricInstallResult:
    template = template or load_dev_rubric()
    verify_dev_rubric_goldens(template)
    desired = _desired_rows(template)

    hunt_exists = await conn.fetchval(
        "select exists(select 1 from hunts where id = $1)", DEV_RUBRIC_HUNT_ID
    )
    if not hunt_exists:
        await conn.execute(
            """
            insert into hunts (id, name, owner_id, domain, rubric_version, settings)
            values ($1, $2, $3, 'rent', 0, $4::jsonb)
            """,
            DEV_RUBRIC_HUNT_ID,
            template.hunt_name,
            DEV_RUBRIC_OWNER_ID,
            json.dumps(template.settings),
        )
        await conn.execute(
            """
            insert into hunt_members (hunt_id, user_id, role)
            values ($1, $2, 'owner') on conflict (hunt_id, user_id) do nothing
            """,
            DEV_RUBRIC_HUNT_ID,
            DEV_RUBRIC_OWNER_ID,
        )

    current_rows = await conn.fetch(
        """
        select catalog_key, enabled, options, unknown_delta, non_negotiable, is_bonus, position
        from rubric_criteria where hunt_id = $1 order by position
        """,
        DEV_RUBRIC_HUNT_ID,
    )
    current = _persisted_rows(list(current_rows))
    if current == desired:
        return DevRubricInstallResult(
            status="unchanged",
            template_version=template.template_version,
            hunt_id=DEV_RUBRIC_HUNT_ID,
            criteria_count=len(desired),
        )
    if current and not force:
        raise DevRubricDriftError(
            "development Rubric differs from the checked-in template; "
            "refusing to overwrite local edits without --force"
        )

    await conn.execute("delete from rubric_criteria where hunt_id = $1", DEV_RUBRIC_HUNT_ID)
    for row in desired:
        await conn.execute(
            """
            insert into rubric_criteria
                (hunt_id, catalog_key, enabled, options, unknown_delta,
                 non_negotiable, is_bonus, position)
            values ($1, $2, $3, $4::jsonb, $5, null, $6, $7)
            """,
            DEV_RUBRIC_HUNT_ID,
            row["catalog_key"],
            row["enabled"],
            json.dumps(row["options"]),
            row["unknown_delta"],
            row["is_bonus"],
            row["position"],
        )
    await conn.execute(
        "update hunts set rubric_version = rubric_version + 1 where id = $1",
        DEV_RUBRIC_HUNT_ID,
    )
    await conn.execute(
        """
        insert into jobs (hunt_id, type, state, payload)
        values ($1, 'rescore', 'queued', $2::jsonb)
        """,
        DEV_RUBRIC_HUNT_ID,
        json.dumps({"hunt_id": str(DEV_RUBRIC_HUNT_ID)}),
    )
    return DevRubricInstallResult(
        status="installed",
        template_version=template.template_version,
        hunt_id=DEV_RUBRIC_HUNT_ID,
        criteria_count=len(desired),
    )
