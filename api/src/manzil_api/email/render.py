from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

TEMPLATES = Path(__file__).with_name("templates")
_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(("html", "xml")),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


def render_email(event_type: str, context: dict[str, Any]) -> RenderedEmail:
    template = _env.get_template(f"{event_type}.html")
    subjects = {
        "hunt_invited": lambda: (
            f"{context['inviter_name']} invited you to {context['hunt_name']} on Manzil"
        ),
        "checkpoint_waiting": lambda: f"{context['property_name']} needs your input on Manzil",
        "run_failed": lambda: f"A Manzil run failed for {context['property_name']}",
        "listing_score_changed": lambda: f"Scores changed for {context['property_name']}",
        "comment_added": lambda: f"{context['actor_name']} commented on {context['property_name']}",
        "rating_changed": lambda: f"{context['actor_name']} rated {context['property_name']}",
    }
    subject_factory = subjects.get(event_type)
    if subject_factory is None:
        raise ValueError(f"Unknown notification event type: {event_type}")
    subject = " ".join(subject_factory().splitlines()).strip()
    html = template.render(context=context)
    text = _env.get_template(f"{event_type}.txt").render(context=context).strip()
    return RenderedEmail(subject=subject, html=html, text=text)
