"""The clarification letter. Deterministic template in local mode.

Contract, identical to the explainer's: introduces no number that is not
already in a flag's evidence, makes no legal threat, and demands no money.
It asks a question. See backend/app/prompts/letter.md.
"""

from __future__ import annotations

from decimal import Decimal

from ..models import BillReport, Flag, Severity
from ..money import format_inr

#: Points worth raising, worst first. Green and gray never appear in a letter
#: -- there is nothing to ask about.
_RAISEABLE = (Severity.RED, Severity.AMBER)


def _point(flag: Flag, item_name: str) -> str:
    question = flag.suggested_question or flag.explanation
    return f"{item_name}: {question}".strip()


def compose(report: BillReport) -> str:
    """Return the letter body as plain text."""
    names = {i.index: i.name for i in report.items}

    points = [f for f in report.flags if f.severity in _RAISEABLE]
    points.sort(key=lambda f: (f.severity is not Severity.RED, f.item_index))

    total = sum((f.amount_affected for f in points), Decimal("0"))

    lines: list[str] = []
    lines.append("To the Billing Department,")
    lines.append(f"{report.hospital_name or 'the hospital'}")
    lines.append("")
    # NEVER the internal bill id. It is a random token that means nothing to
    # the hospital and looks like a system leak in a letter a patient sends.
    # The bill date is what identifies the bill to its issuer.
    lines.append(
        (
            f"I am writing about my bill dated {report.bill_date}"
            if report.bill_date
            else "I am writing about a recent bill from your hospital"
        )
        + ". I have reviewed it against the ceiling prices published by the "
        "National Pharmaceutical Pricing Authority, and a few items may need "
        "clarification. I may well have misread something, and I would be "
        "grateful for your explanation."
    )
    lines.append("")

    if points:
        lines.append("The points I would like to understand better:")
        lines.append("")
        for n, flag in enumerate(points, start=1):
            name = names.get(flag.item_index, "the bill total")
            lines.append(f"{n}. {_point(flag, name)}")
            reference = flag.evidence.get("reference") or {}
            if reference.get("so_number"):
                lines.append(
                    f"   Reference: {reference.get('formulation')} "
                    f"({reference.get('strength')}), ceiling price "
                    f"{format_inr(flag.evidence.get('ceiling_ex_gst'))} per "
                    f"{flag.evidence.get('ceiling_unit')} excluding taxes, "
                    f"S.O. {reference['so_number']} dated {reference['so_date']}."
                )
            if flag.amount_affected > 0:
                lines.append(f"   Amount affected: {format_inr(flag.amount_affected)}.")
            lines.append("")
        lines.append(
            f"Total amount affected across these points: {format_inr(total)}."
        )
    else:
        lines.append(
            "I did not find anything on this bill that needs clarification. "
            "I am writing only to request an itemised copy for my records."
        )

    lines.append("")
    lines.append(
        "Could you please share an itemised explanation of how these amounts "
        "were arrived at? If I have misunderstood any of them, I would "
        "appreciate the correction."
    )
    lines.append("")
    lines.append("Thank you for your time.")
    lines.append("")
    if report.reference_retrieved_on:
        lines.append(
            f"(Prices compared against NPPA data retrieved "
            f"{report.reference_retrieved_on}.)"
        )
    return "\n".join(lines)
