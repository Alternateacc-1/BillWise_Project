"""The rules. Pure Python, always local, never an LLM.

Code decides every verdict. The model only writes prose about a verdict that
has already been reached, from evidence that has already been computed.

Phase 1 implements R1-R5 and R9. R6-R8 follow once this pass is solid.

  R1  qty x unit_price - discount + tax != line_total (+/- Rs 1)     amber
  R2  sum of line totals != printed grand total (+/- Rs 1)           amber
  R3  same normalised name + same quantity, more than once           amber
  R4  name similarity >= 92 + same unit price                        amber
  R5  price per base unit above the ceiling threshold                RED
  R9  no confident match, reading not HIGH, or no public ceiling     gray

Every price flag carries the full arithmetic in its evidence so the user can
check it by hand, and the excess percentage so the 0-25% amber band is
visible rather than implied.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from rapidfuzz import fuzz

from .. import config
from ..money import format_inr
from ..models import (
    CeilingMatch,
    Flag,
    GrayDetail,
    GrayReason,
    ItemCategory,
    NO_CEILING_CATEGORIES,
    NormalizedItem,
    ReadingStats,
    Reconciliation,
    Severity,
    VerifiedItem,
)
from .match import select_ceiling
from .salt_synonyms import normalise_spelling

DUPLICATE_NAME_SIMILARITY = 92


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct(value: Decimal) -> Decimal:
    return (value * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def format_unit(qty: Decimal, basis: str) -> str:
    """"tablet", not "1 tablet". "500 ml" when the quantity carries meaning."""
    if qty == 1:
        return basis
    normalised = qty.normalize()
    return f"{normalised:f} {basis}"


# --------------------------------------------------------------------------
# R1 -- line arithmetic
# --------------------------------------------------------------------------

def rule_r1_line_arithmetic(item: VerifiedItem) -> Flag | None:
    if item.quantity is None or item.unit_price is None or item.line_total is None:
        return None
    computed = item.quantity * item.unit_price - item.discount + item.tax
    difference = computed - item.line_total
    if abs(difference) <= config.ARITHMETIC_TOLERANCE:
        return None
    return Flag(
        rule_id="R1",
        severity=Severity.AMBER,
        item_index=item.index,
        amount_affected=_money(abs(difference)),
        evidence={
            "quantity": str(item.quantity),
            "unit_price": str(item.unit_price),
            "discount": str(item.discount),
            "tax": str(item.tax),
            "arithmetic": (
                f"{item.quantity} x {item.unit_price} - {item.discount} "
                f"+ {item.tax} = {_money(computed)}"
            ),
            "computed_total": str(_money(computed)),
            "printed_line_total": str(item.line_total),
            "difference": str(_money(difference)),
            "tolerance": str(config.ARITHMETIC_TOLERANCE),
        },
        suggested_question=(
            "Could you confirm how the total for this line was calculated? "
            f"The quantity and rate shown come to {format_inr(_money(computed))}, "
            f"while the line shows {format_inr(item.line_total)}."
        ),
    )


# --------------------------------------------------------------------------
# R2 -- bill reconciliation
# --------------------------------------------------------------------------

def rule_r2_bill_total(stats: ReadingStats) -> Flag | None:
    if stats.reconciliation is not Reconciliation.MISMATCH:
        return None
    if stats.sum_of_line_totals is None or stats.printed_grand_total is None:
        return None
    difference = stats.sum_of_line_totals - stats.printed_grand_total
    return Flag(
        rule_id="R2",
        severity=Severity.AMBER,
        item_index=-1,  # bill-level, not tied to one line
        amount_affected=_money(abs(difference)),
        evidence={
            "sum_of_line_totals": str(_money(stats.sum_of_line_totals)),
            "printed_grand_total": str(_money(stats.printed_grand_total)),
            "difference": str(_money(difference)),
            "arithmetic": (
                f"{_money(stats.sum_of_line_totals)} (sum of lines) - "
                f"{_money(stats.printed_grand_total)} (printed total) = "
                f"{_money(difference)}"
            ),
            "tolerance": str(config.ARITHMETIC_TOLERANCE),
        },
        suggested_question=(
            "Could you help us reconcile the bill total? The individual lines "
            f"add up to {format_inr(_money(stats.sum_of_line_totals))}, while the "
            f"printed total is {format_inr(_money(stats.printed_grand_total))}."
        ),
    )


# --------------------------------------------------------------------------
# R3 / R4 -- possible duplicates
# --------------------------------------------------------------------------

def rule_r3_exact_duplicates(items: list[VerifiedItem]) -> list[Flag]:
    groups: dict[tuple, list[VerifiedItem]] = defaultdict(list)
    for item in items:
        groups[(normalise_spelling(item.name), str(item.quantity))].append(item)

    flags = []
    for (name, _quantity), members in groups.items():
        if len(members) < 2 or not name:
            continue
        for duplicate in members[1:]:
            flags.append(Flag(
                rule_id="R3",
                severity=Severity.AMBER,
                item_index=duplicate.index,
                amount_affected=_money(duplicate.line_total or Decimal("0")),
                evidence={
                    "normalised_name": name,
                    "quantity": str(duplicate.quantity),
                    "appears_on_lines": [m.index for m in members],
                    "occurrences": len(members),
                },
                suggested_question=(
                    "This item appears more than once with the same quantity. "
                    "Could you confirm whether both entries are correct?"
                ),
            ))
    return flags


def rule_r4_near_duplicates(items: list[VerifiedItem]) -> list[Flag]:
    flags = []
    seen_pairs = set()
    for i, left in enumerate(items):
        for right in items[i + 1:]:
            if left.unit_price is None or left.unit_price != right.unit_price:
                continue
            left_norm = normalise_spelling(left.name)
            right_norm = normalise_spelling(right.name)
            if not left_norm or left_norm == right_norm:
                continue  # exact repeats are R3's job
            similarity = fuzz.token_sort_ratio(left_norm, right_norm)
            if similarity < DUPLICATE_NAME_SIMILARITY:
                continue
            key = (left.index, right.index)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            flags.append(Flag(
                rule_id="R4",
                severity=Severity.AMBER,
                item_index=right.index,
                amount_affected=_money(right.line_total or Decimal("0")),
                evidence={
                    "this_line": right.name,
                    "similar_to_line": left.index,
                    "similar_to_name": left.name,
                    "name_similarity": f"{similarity:.0f}",
                    "same_unit_price": str(left.unit_price),
                },
                suggested_question=(
                    "Two lines with very similar descriptions carry the same "
                    "rate. Could you confirm they are separate items?"
                ),
            ))
    return flags


# --------------------------------------------------------------------------
# R5 -- above the published ceiling
# --------------------------------------------------------------------------

def _interpretations(item: VerifiedItem, normalized: NormalizedItem) -> list[dict]:
    """The two readings of an ambiguous quantity.

    "Augmentin 625, Qty 1, Rs 223" is one strip or one tablet. We compute
    both and only raise red when BOTH exceed the threshold. If only one does,
    it is amber with the pack-size ambiguity stated.
    """
    if item.line_total is None or not item.quantity or item.quantity <= 0:
        return []

    out = [{
        "label": "per_billed_unit",
        "description": "quantity is the number of base units",
        "divisor": item.quantity,
        "per_unit": item.line_total / item.quantity,
    }]

    # The dual interpretation exists ONLY when the pack size was INFERRED.
    # When the bill states it outright ("Injection 500 ml"), the quantity is
    # not ambiguous and a second reading would be invented, not discovered.
    if normalized.pack_count_source == "bill_text" and normalized.pack_count:
        return [{
            "label": "per_stated_unit",
            "description": (
                f"the bill states a pack of {normalized.pack_count} "
                f"{normalized.pack_unit or 'units'}"
            ),
            "divisor": item.quantity * normalized.pack_count,
            "per_unit": item.line_total / (item.quantity * normalized.pack_count),
        }]

    if normalized.pack_count and normalized.pack_count > 0:
        divisor = item.quantity * normalized.pack_count
        out.append({
            "label": "per_pack_unit",
            "description": (
                f"quantity is packs of {normalized.pack_count} "
                f"{normalized.pack_unit or 'units'}"
            ),
            "divisor": divisor,
            "per_unit": item.line_total / divisor,
        })
    return out


def rule_r5_above_ceiling(
    item: VerifiedItem, normalized: NormalizedItem, ceiling: CeilingMatch,
) -> Flag | None:
    """Compare the billed per-unit price against the ceiling threshold.

    Four guards stand between a price difference and a red flag, and all four
    err toward silence. See docs/ARCHITECTURE.md for why each number is what
    it is.
    """
    interpretations = _interpretations(item, normalized)
    if not interpretations:
        return None

    amber_at = config.amber_threshold(ceiling.per_base_unit)
    red_at = config.red_threshold(ceiling.per_base_unit)

    for interpretation in interpretations:
        per_unit = interpretation["per_unit"]
        excess = (per_unit - ceiling.per_base_unit) / ceiling.per_base_unit
        interpretation["per_unit_str"] = str(_money(per_unit))
        interpretation["excess_over_ceiling_pct"] = str(_pct(excess))
        interpretation["above_amber_threshold"] = per_unit > amber_at
        interpretation["above_red_threshold"] = per_unit > red_at
        interpretation["ratio_to_ceiling"] = str(
            (per_unit / ceiling.per_base_unit).quantize(Decimal("0.01"))
        )

    # The interpretation LEAST favourable to a flag decides. Using the
    # minimum per-unit price means an ambiguous pack size can never be the
    # reason an item turns red.
    decisive = min(interpretations, key=lambda i: i["per_unit"])
    every_reading_above_red = all(i["above_red_threshold"] for i in interpretations)
    any_reading_above_amber = any(i["above_amber_threshold"] for i in interpretations)

    if not any_reading_above_amber:
        return None

    highest_per_unit = max(i["per_unit"] for i in interpretations)
    billed_units = decisive["divisor"]
    amount_affected = _money(
        max(Decimal("0"), (decisive["per_unit"] - amber_at) * billed_units)
    )
    ratio = highest_per_unit / ceiling.per_base_unit

    evidence = {
        "ceiling_ex_gst": str(ceiling.price_ex_gst),
        "ceiling_per_base_unit": str(ceiling.per_base_unit.quantize(Decimal("0.0001"))),
        "ceiling_unit": format_unit(ceiling.unit_qty, ceiling.unit_basis),
        "gst_percent": str(config.GST_PERCENT),
        "gst_multiplier": str(config.gst_multiplier()),
        "amber_threshold": str(_money(amber_at)),
        "red_threshold": str(_money(red_at)),
        "red_excess_fraction": str(config.RED_EXCESS_FRACTION),
        "arithmetic": (
            f"ceiling {ceiling.per_base_unit.quantize(Decimal('0.0001'))} "
            f"x GST {config.gst_multiplier()} = {_money(amber_at)}; "
            f"x red margin {1 + config.RED_EXCESS_FRACTION} = {_money(red_at)}"
        ),
        "interpretations": [
            {
                "label": i["label"],
                "description": i["description"],
                "billed_per_unit": i["per_unit_str"],
                "excess_over_ceiling_pct": i["excess_over_ceiling_pct"],
                "ratio_to_ceiling": i["ratio_to_ceiling"],
                "above_red_threshold": i["above_red_threshold"],
            }
            for i in interpretations
        ],
        "reference": {
            "ref_id": ceiling.ref_id,
            "source": ceiling.source,
            "match_tier": ceiling.tier,
            "formulation": ceiling.formulation_raw,
            "strength": ceiling.strength_raw,
            "so_number": ceiling.so_number,
            "so_date": ceiling.so_date,
        },
    }
    if ceiling.modifier_was_unknown:
        evidence["form_modifier_unknown"] = (
            "the bill did not state a release form, so the highest ceiling "
            "among the possible variants was used"
        )

    # --- the four guards -------------------------------------------------
    blocked: list[str] = []
    if not normalized.eligible_for_red:
        blocked.append(f"match_type_is_{normalized.match_type.value}_not_exact")
    if not item.is_high:
        blocked.append("reading_not_high_confidence")
    if not every_reading_above_red:
        blocked.append("pack_size_ambiguous_only_one_interpretation_exceeds_threshold")
    if amount_affected < config.RED_MIN_AMOUNT_AFFECTED:
        blocked.append(
            f"amount_affected_below_minimum_{config.RED_MIN_AMOUNT_AFFECTED}"
        )
    if ratio > config.RED_MAX_RATIO:
        blocked.append(
            f"ratio_{ratio.quantize(Decimal('0.1'))}_exceeds_{config.RED_MAX_RATIO}"
            "_suggesting_a_misread_rather_than_a_price_difference"
        )

    severity = Severity.AMBER if blocked else Severity.RED
    if blocked:
        evidence["not_red_because"] = blocked

    if severity is Severity.AMBER and len(interpretations) > 1 and not every_reading_above_red:
        note = (
            "The pack size on this line is unclear, so we cannot say which "
            "per-unit price applies."
        )
    else:
        note = ""
    if note:
        evidence["pack_size_note"] = note

    return Flag(
        rule_id="R5",
        severity=severity,
        item_index=item.index,
        amount_affected=amount_affected,
        evidence=evidence,
        suggested_question=(
            "Could you share how the rate for this item was arrived at? "
            f"The published ceiling price is {format_inr(ceiling.price_ex_gst)} per "
            f"{format_unit(ceiling.unit_qty, ceiling.unit_basis)} excluding taxes, under "
            f"S.O. {ceiling.so_number} dated {ceiling.so_date}."
        ),
    )


# --------------------------------------------------------------------------
# R9 -- gray, with a machine-readable reason
# --------------------------------------------------------------------------

def rule_r9_gray(item: VerifiedItem, normalized: NormalizedItem) -> Flag:
    """Why this item has no price verdict.

    The two reasons mean opposite things and must never be conflated.
    """
    if normalized.category in NO_CEILING_CATEGORIES:
        return Flag(
            rule_id="R9",
            severity=Severity.GRAY,
            item_index=item.index,
            gray_reason=GrayReason.NO_PUBLIC_CEILING,
            evidence={
                "category": normalized.category.value,
                "checked_for": ["arithmetic", "duplication"],
            },
            explanation=(
                "No public price ceiling exists for this item; we checked it "
                "for duplication and arithmetic only."
            ),
        )

    detail = list(normalized.notes)

    # Reading and identification are different failures and must not be
    # reported as one. "The two readers disagreed" is not "we do not know what
    # this medicine is", and a user can act on the first but not the second.
    if not item.is_high:
        detail.append("reading_not_high_confidence")
        gray_detail = GrayDetail.COULD_NOT_READ
        explanation = (
            "We could not read this line reliably, so we have not compared "
            "its price. It was still checked for duplication and arithmetic."
        )
    else:
        gray_detail = GrayDetail.COULD_NOT_IDENTIFY
        explanation = (
            "We read this line clearly, but could not identify which medicine "
            "it is, so we have not compared its price. It was still checked "
            "for duplication and arithmetic."
        )

    return Flag(
        rule_id="R9",
        severity=Severity.GRAY,
        item_index=item.index,
        gray_reason=GrayReason.COULD_NOT_VERIFY,
        gray_detail=gray_detail,
        evidence={
            "category": normalized.category.value,
            "match_type": normalized.match_type.value,
            "reading_confidence": item.confidence.value,
            "detail": detail,
            "checked_for": ["arithmetic", "duplication"],
        },
        explanation=explanation,
    )


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def audit(
    items: list[VerifiedItem],
    normalized: list[NormalizedItem],
    stats: ReadingStats,
) -> list[Flag]:
    """Run every Phase 1 rule. Pure: same input, same output, no network."""
    by_index = {n.index: n for n in normalized}
    flags: list[Flag] = []

    bill_total_flag = rule_r2_bill_total(stats)
    if bill_total_flag:
        flags.append(bill_total_flag)

    flags.extend(rule_r3_exact_duplicates(items))
    flags.extend(rule_r4_near_duplicates(items))

    for item in items:
        norm = by_index.get(item.index) or NormalizedItem(index=item.index)

        arithmetic_flag = rule_r1_line_arithmetic(item)
        if arithmetic_flag:
            flags.append(arithmetic_flag)

        priced = False
        # A non-HIGH reading is excluded from every price rule, and a
        # service or consumable has no ceiling to be compared against.
        if item.is_high and norm.category not in NO_CEILING_CATEGORIES and norm.salt_components:
            ceiling = select_ceiling(
                salt_components=norm.salt_components,
                dosage_form=norm.dosage_form,
                strength_mg=norm.strength_mg,
                strength_kind=norm.strength_kind,
                unit_basis=norm.unit_basis or _unit_basis_for(norm),
                unit_qty=norm.pack_count if norm.pack_count_source == "bill_text" else Decimal("1"),
                form_modifier=norm.form_modifier,
            )
            if ceiling is not None:
                priced = True
                price_flag = rule_r5_above_ceiling(item, norm, ceiling)
                if price_flag:
                    flags.append(price_flag)
                else:
                    flags.append(Flag(
                        rule_id="R5",
                        severity=Severity.GREEN,
                        item_index=item.index,
                        evidence={
                            "ceiling_ex_gst": str(ceiling.price_ex_gst),
                            "ceiling_unit": format_unit(ceiling.unit_qty, ceiling.unit_basis),
                            "so_number": ceiling.so_number,
                            "so_date": ceiling.so_date,
                            "ref_id": ceiling.ref_id,
                        },
                        explanation=(
                            "This item's price is within the published ceiling."
                        ),
                    ))

        if not priced:
            flags.append(rule_r9_gray(item, norm))

    return flags


def _unit_basis_for(norm: NormalizedItem) -> str:
    """The base unit a ceiling would be quoted in for this item."""
    if norm.pack_unit:
        return norm.pack_unit
    return {
        "tablet": "tablet",
        "capsule": "capsule",
        "injection": "vial",
    }.get(norm.dosage_form, norm.dosage_form or "tablet")
