"""Model-bench comparison (P0-13, DESIGN §11.2).

Reads two or more bench-run reports (same labels, different models — produced
via `MANZIL_MODEL_<STAGE>` overrides) and renders the side-by-side table the
§11.2 decision needs: verification pass-rate proxies (gate/criterion
accuracy, evidence flags), cost, latency. The decision itself — rewriting the
pins in `llm/config.py` and adopting a non-Anthropic default — requires this
evidence AND a DESIGN §20 entry (P0-14); the table never edits config.
"""

from __future__ import annotations

import json
from pathlib import Path

from manzil_worker.evals.harness import BenchReport

_ROWS: list[tuple[str, str]] = [
    ("gate_accuracy", "gate accuracy"),
    ("criterion_accuracy", "criterion accuracy"),
    ("unknown_accuracy", "unknown accuracy"),
    ("plan_field_accuracy", "plan field accuracy"),
    ("scoped_claim_accuracy", "scoped claim accuracy"),
    ("exact_target_recall", "exact target recall"),
    ("wrong_exact_associations", "wrong exact associations"),
    ("evidence_flag_rate", "evidence flag rate"),
    ("total_cost_usd", "total cost $"),
    ("mean_latency_s", "mean latency s"),
    ("failed", "failed listings"),
]


def load_report(path: Path) -> BenchReport:
    return BenchReport.model_validate(json.loads(path.read_text()))


def compare_table(reports: dict[str, BenchReport]) -> str:
    """Markdown table, one column per report. Quality wins any tie (§11.2)."""
    names = list(reports)
    lines = [
        "| metric | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
        "| extract model | "
        + " | ".join(reports[n].models.get("extract", "?") for n in names)
        + " |",
        "| verify model | "
        + " | ".join(reports[n].models.get("verify", "?") for n in names)
        + " |",
        "| llm mode | " + " | ".join(reports[n].llm_mode for n in names) + " |",
    ]
    for key, title in _ROWS:
        cells = []
        for name in names:
            value = reports[name].summary.get(key)
            cells.append("—" if value is None else str(value))
        lines.append(f"| {title} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
