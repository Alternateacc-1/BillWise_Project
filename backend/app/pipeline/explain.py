"""Turning a flag's evidence into a sentence. Templates in local mode.

The LLM variant (Phase 4) is held to exactly the same contract as these
templates: it may rephrase, and it may introduce NO number that is not
already in the evidence. That is enforceable precisely because the templates
exist first and define what a correct explanation looks like.

Language rules, non-negotiable (docs/ARCHITECTURE.md):
  never   illegal, fraud, cheating, overcharged
  always  "above the listed ceiling price", "may need clarification",
          "amount affected"
"""

from __future__ import annotations

from ..models import Flag, GrayReason, Severity

#: Words that must never appear in anything the user reads. Asserted by a test
#: over every generated explanation.
FORBIDDEN_WORDS = ("illegal", "fraud", "cheat", "overcharg", "scam", "rip off")


def _r5(flag: Flag) -> str:
    evidence = flag.evidence
    reference = evidence.get("reference", {})
    interpretations = evidence.get("interpretations", [])
    decisive = min(
        interpretations, key=lambda i: float(i["billed_per_unit"])
    ) if interpretations else {}

    lines = []
    if flag.severity is Severity.RED:
        lines.append(
            f"This item appears to be billed above the listed ceiling price. "
            f"The published ceiling is Rs {evidence.get('ceiling_ex_gst')} per "
            f"{evidence.get('ceiling_unit')} excluding taxes, which allows up to "
            f"Rs {evidence.get('amber_threshold')} per unit once GST of "
            f"{evidence.get('gst_percent')}% is added."
        )
    else:
        lines.append(
            f"This item is close to the listed ceiling price and may need "
            f"clarification. The published ceiling is Rs "
            f"{evidence.get('ceiling_ex_gst')} per {evidence.get('ceiling_unit')} "
            f"excluding taxes, allowing up to Rs {evidence.get('amber_threshold')} "
            f"per unit with GST of {evidence.get('gst_percent')}%."
        )

    if decisive:
        lines.append(
            f"This line works out to Rs {decisive.get('billed_per_unit')} per unit, "
            f"which is {decisive.get('excess_over_ceiling_pct')}% above the ceiling. "
            f"Amount affected: Rs {flag.amount_affected}."
        )

    if evidence.get("pack_size_note"):
        lines.append(evidence["pack_size_note"])
    if evidence.get("form_modifier_unknown"):
        lines.append(
            "The bill did not state the exact form of this product, so the "
            "highest applicable ceiling was used."
        )
    if reference:
        lines.append(
            f"Reference: {reference.get('formulation')} "
            f"({reference.get('strength')}), S.O. {reference.get('so_number')} "
            f"dated {reference.get('so_date')}."
        )
    return " ".join(lines)


def _r1(flag: Flag) -> str:
    evidence = flag.evidence
    return (
        f"The arithmetic on this line does not add up. {evidence.get('arithmetic')}, "
        f"but the line total reads Rs {evidence.get('printed_line_total')}. "
        f"Amount affected: Rs {flag.amount_affected}. This may simply be a "
        f"rounding or data-entry difference worth confirming."
    )


def _r2(flag: Flag) -> str:
    evidence = flag.evidence
    return (
        f"The individual lines on this bill add up to Rs "
        f"{evidence.get('sum_of_line_totals')}, while the printed total reads Rs "
        f"{evidence.get('printed_grand_total')}. Amount affected: Rs "
        f"{flag.amount_affected}. This difference may need clarification."
    )


def _r3(flag: Flag) -> str:
    evidence = flag.evidence
    lines = evidence.get("appears_on_lines", [])
    return (
        f"This item appears {evidence.get('occurrences')} times on the bill with "
        f"the same quantity (lines {', '.join(str(n) for n in lines)}). Repeat "
        f"entries can be legitimate, so this may simply need confirming. "
        f"Amount affected: Rs {flag.amount_affected}."
    )


def _r4(flag: Flag) -> str:
    evidence = flag.evidence
    return (
        f"This line closely resembles line {evidence.get('similar_to_line')} "
        f"(\"{evidence.get('similar_to_name')}\") and carries the same rate of Rs "
        f"{evidence.get('same_unit_price')}. It may be a separate item, or the "
        f"same one entered twice. Amount affected: Rs {flag.amount_affected}."
    )


def _r9(flag: Flag) -> str:
    # The two gray reasons say opposite things and are worded to match.
    if flag.gray_reason is GrayReason.NO_PUBLIC_CEILING:
        return (
            "No public price ceiling exists for this item, so there is no "
            "published rate to compare it against. We checked it for "
            "duplication and arithmetic only."
        )
    return (
        "We could not confidently identify this item, so we have not compared "
        "its price against any published ceiling. It was still checked for "
        "duplication and arithmetic."
    )


_TEMPLATES = {"R1": _r1, "R2": _r2, "R3": _r3, "R4": _r4, "R5": _r5, "R9": _r9}


def explain(flag: Flag) -> str:
    """One flag's explanation. Never invents a number absent from evidence."""
    if flag.severity is Severity.GREEN:
        return "This item's price is within the published ceiling."
    template = _TEMPLATES.get(flag.rule_id)
    if template is None:
        return flag.explanation or ""
    return template(flag)


def explain_all(flags: list[Flag]) -> list[Flag]:
    for flag in flags:
        flag.explanation = explain(flag)
    return flags
