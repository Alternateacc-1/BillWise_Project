"""Turning a flag's evidence into a sentence. Templates in local mode.

The LLM variant is held to exactly the same contract as these
templates: it may rephrase, and it may introduce NO number that is not
already in the evidence. That is enforceable precisely because the templates
exist first and define what a correct explanation looks like.

Language rules, non-negotiable (docs/ARCHITECTURE.md):
  never   illegal, fraud, cheating, overcharged
  always  "above the listed ceiling price", "may need clarification",
          "amount affected"
"""

from __future__ import annotations

from ..models import Flag, GrayDetail, GrayReason, Severity
from ..money import format_inr

#: Words that must never appear in anything the user reads. Pinned by
#: test_no_forbidden_word_reaches_anything_a_user_reads, which walks the
#: serialised report and the letter for every fixture.
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
            f"The published ceiling is {format_inr(evidence.get('ceiling_ex_gst'))} per "
            f"{evidence.get('ceiling_unit')} excluding taxes, which allows up to "
            f"{format_inr(evidence.get('amber_threshold'))} per unit once GST of "
            f"{evidence.get('gst_percent')}% is added."
        )
    else:
        lines.append(
            f"This item is close to the listed ceiling price and may need "
            f"clarification. The published ceiling is "
            f"{format_inr(evidence.get('ceiling_ex_gst'))} per {evidence.get('ceiling_unit')} "
            f"excluding taxes, allowing up to {format_inr(evidence.get('amber_threshold'))} "
            f"per unit with GST of {evidence.get('gst_percent')}%."
        )

    if decisive:
        lines.append(
            f"This line works out to {format_inr(decisive.get('billed_per_unit'))} per unit, "
            f"which is {decisive.get('excess_over_allowance_pct')}% above the "
            f"{format_inr(evidence.get('amber_threshold'))} allowed once GST is added. "
            f"Amount affected: {format_inr(flag.amount_affected)}."
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
        f"but the line total reads {format_inr(evidence.get('printed_line_total'))}. "
        f"Amount affected: {format_inr(flag.amount_affected)}. This may simply be a "
        f"rounding or data-entry difference worth confirming."
    )


def _r2(flag: Flag) -> str:
    evidence = flag.evidence
    return (
        f"The individual lines on this bill add up to "
        f"{format_inr(evidence.get('sum_of_line_totals'))}, while the printed total "
        f"reads {format_inr(evidence.get('printed_grand_total'))}. Amount affected: "
        f"{format_inr(flag.amount_affected)}. This difference may need clarification."
    )


def _r3(flag: Flag) -> str:
    evidence = flag.evidence
    lines = evidence.get("appears_on_lines", [])
    return (
        f"This item appears {evidence.get('occurrences')} times on the bill with "
        f"the same quantity (lines {', '.join(str(n) for n in lines)}). Repeat "
        f"entries can be legitimate, so this may simply need confirming. "
        f"Amount affected: {format_inr(flag.amount_affected)}."
    )


def _r4(flag: Flag) -> str:
    evidence = flag.evidence
    return (
        f"This line closely resembles line {evidence.get('similar_to_line')} "
        f"(\"{evidence.get('similar_to_name')}\") and carries the same rate of "
        f"{format_inr(evidence.get('same_unit_price'))}. It may be a separate item, or "
        f"the same one entered twice. Amount affected: {format_inr(flag.amount_affected)}."
    )


def _r5_gray_pack_size_unknown(flag: Flag) -> str:
    e = flag.evidence
    return (
        f"We could not tell how many units this line is charging for. The "
        f"published ceiling allows {format_inr(e.get('allowance_per_unit'))} per "
        f"{e.get('ceiling_unit')} once GST is added, and this line works out to "
        f"{format_inr(e.get('upper_bound_per_unit'))} per item billed — but "
        f"if one item billed is a pack rather than a single "
        f"{e.get('ceiling_unit')}, the real price per {e.get('ceiling_unit')} "
        f"would be lower and may be well within the ceiling. Because the bill "
        f"does not say which, we have not compared its price. It was still "
        f"checked for duplication and arithmetic."
    )


def _r9(flag: Flag) -> str:
    # Three distinct situations, three distinct sentences. The auditor already
    # chose the right one; repeating the branch here would let them drift.
    if flag.gray_reason is GrayReason.NO_PUBLIC_CEILING:
        return (
            "No public price ceiling exists for this item, so there is no "
            "published rate to compare it against. We checked it for "
            "duplication and arithmetic only."
        )
    if flag.gray_detail is GrayDetail.COULD_NOT_READ:
        return (
            "We could not read this line reliably, so we have not compared "
            "its price. It was still checked for duplication and arithmetic."
        )
    return (
        "We read this line clearly, but could not identify which medicine it "
        "is, so we have not compared its price. It was still checked for "
        "duplication and arithmetic."
    )


_TEMPLATES = {"R1": _r1, "R2": _r2, "R3": _r3, "R4": _r4, "R5": _r5, "R9": _r9}


def explain(flag: Flag) -> str:
    """One flag's explanation. Never invents a number absent from evidence."""
    if flag.severity is Severity.GREEN:
        if flag.evidence.get("holds_for_every_pack_size"):
            # The strongest thing this system can say about a price. Worth
            # saying in plain words rather than burying in an evidence key.
            return (
                "This item's price is within the published ceiling — and it "
                "stays within it however the quantity is counted. Even if every "
                f"unit billed were a single {flag.evidence.get('ceiling_unit')}, "
                f"the price would still be under the "
                f"{format_inr(flag.evidence.get('allowance_per_unit'))} allowed "
                "once GST is added."
            )
        return "This item's price is within the published ceiling."

    if flag.rule_id == "R5" and flag.gray_detail is GrayDetail.PACK_SIZE_UNKNOWN:
        return _r5_gray_pack_size_unknown(flag)
    template = _TEMPLATES.get(flag.rule_id)
    if template is None:
        return flag.explanation or ""
    return template(flag)


def explain_all(flags: list[Flag]) -> list[Flag]:
    for flag in flags:
        flag.explanation = explain(flag)
    return flags
