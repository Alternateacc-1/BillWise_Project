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



def _readers_disagreed_on_numbers(item: VerifiedItem) -> bool:
    """Did the two readers differ on quantity, rate or line total?

    A name disagreement is not enough to silence R1 -- the arithmetic does not
    depend on the name. A NUMBER disagreement is, because we then do not know
    which number to do arithmetic with.
    """
    return any(
        r.startswith(("readers_disagree_on_quantity",
                      "readers_disagree_on_unit_price",
                      "readers_disagree_on_line_total"))
        for r in item.reasons
    )


def _line_exceeds_whole_bill(
    item: VerifiedItem, grand_total: Decimal | None
) -> bool:
    """A single line cannot be worth more than the entire bill.

    When it appears to be, OUR READING is wrong -- not the bill. Measured on
    the deployed stack 2026-09-19: Textract read 72.00 as "7200", and a
    Rs 7,200 line appeared on a Rs 190 bill. Reporting that as a Rs 7,130
    arithmetic discrepancy blames the pharmacy for our own lost decimal point.

    Deliberately generous: only fires when the line EXCEEDS the printed total,
    not when it is merely a large share of it. A single expensive item can
    legitimately dominate a bill.
    """
    if grand_total is None or item.line_total is None:
        return False
    return item.line_total > grand_total


# --------------------------------------------------------------------------
# R1 -- line arithmetic
# --------------------------------------------------------------------------

def rule_r1_line_arithmetic(
    item: VerifiedItem, grand_total: Decimal | None = None
) -> Flag | None:
    """Check qty x rate == line total, but ONLY on a line we trust.

    THE CONFIDENCE GATE IS NOT OPTIONAL, and it was missing until 2026-09-19.
    Measured on the deployed stack: Textract read 7.20 as "7" and 72.00 as
    "7200" -- a lost decimal point, a 100x error -- and this rule faithfully
    reported a Rs 7,130 discrepancy on a bill whose true total was Rs 190.

    The arithmetic was correct. The input was nonsense. R5 already refuses to
    price a line whose confidence is unverified_reading; this rule did not
    refuse to do arithmetic on one, and THAT ASYMMETRY WAS THE BUG. The
    two-reader check protects the price rules by catching name disagreement,
    but two readers cannot disagree about numbers that are internally
    consistent nonsense, so nothing protected the arithmetic rules.

    A line we could not read reliably cannot support a claim about its own
    arithmetic. It is already reported as could_not_read; adding a confident
    rupee figure on top of that says two contradictory things at once.

    THE GATE IS NOT `is_high`, AND THAT MATTERS. verify.py sets HIGH only when
    `agrees and arithmetic is True and bounds_ok`, so a line whose arithmetic
    fails is NEVER high confidence -- gating on it would make this rule dead
    code that can only fire where there is nothing to report. The first
    attempt at this fix did exactly that and the eval caught it immediately.

    The gate is instead the two things that distinguish a real arithmetic
    error from a misread:
      1. the readers AGREED on the numbers -- if they disagree we do not know
         what the numbers are, so we cannot say the arithmetic is wrong;
      2. the line is PLAUSIBLE -- see _line_is_implausible().
    """
    if item.quantity is None or item.unit_price is None or item.line_total is None:
        return None
    if _readers_disagreed_on_numbers(item):
        return None
    if _line_exceeds_whole_bill(item, grand_total):
        return None
    computed = item.quantity * item.unit_price - item.discount + item.tax
    difference = computed - item.line_total
    if abs(difference) <= config.ARITHMETIC_TOLERANCE:
        return None

    # THE DIRECTION OF THE DIFFERENCE IS THE WHOLE POINT -- THE SAME RULE R2
    # APPLIES TO THE BILL TOTAL, ONE SCALE DOWN.
    #
    # `difference > 0` means qty x rate comes to MORE than the line charges.
    # The patient is being asked for LESS than the line itemises, which is
    # what a per-line discount column looks like when we did not read it.
    # Querying that is asking a pharmacy to explain its own discount.
    #
    # Class F in FORMAT_FINDINGS.md, and it was the last of the three scales
    # of one bug still live: bill totals (Class B), section subtotals read as
    # line items (Class E), and line adjustments (this). B and E fell to the
    # directional rule in R2; measured 2026-09-19 by eval/class_b_probe.py,
    # which found this one still firing `R1 amber Rs 12.00` on a correct line
    # carrying a 10% line discount.
    #
    # THIS NARROWS THE RULE, so it cannot introduce a false red. The direction
    # worth a question -- the line charging MORE than it itemises -- is
    # untouched, which is why bill_01 line 13 (125.00 computed, 130.00
    # printed) still fires.
    if difference > 0:
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

def rule_r2_bill_total(
    stats: ReadingStats, any_line_implausible: bool = False
) -> Flag | None:
    """Reconcile the line sum against the printed total, when both are trusted.

    ABSTAINS when any line was read unreliably. A sum is only as sound as its
    weakest term: one misread line total poisons it completely, and the
    resulting "discrepancy" is our own reading error reported as the bill's.

    Measured 2026-09-19 on the deployed stack: a single lost decimal
    (72.00 -> 7200) produced a false Rs 7,018 reconciliation failure on a
    Rs 190 bill. Class A's rule at bill level -- a check that cannot run
    should abstain, not fail.

    ONLY FIRES WHEN THE PRINTED TOTAL EXCEEDS THE LINE SUM. The opposite
    direction is `BELOW_LINE_SUM`, not a finding: a bill charging LESS than
    it itemises has discounted the patient, and asking them to query it is
    both useless and embarrassing. verify.py classifies the direction; this
    rule simply never sees the harmless one, because a bill that asks for
    less than its own lines is not a bill worth questioning.
    """
    if any_line_implausible:
        return None
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

#: How well we know what one billed unit contains. This is the difference
#: between a verdict and a guess.
CERTAIN = "certain"          # the bill states the pack size outright
BOUNDED = "bounded"          # inferred from a pack label; two readings, both computed
UNKNOWN = "unknown"          # we do not know, and line_total/qty is only a CEILING


def pack_certainty(normalized: NormalizedItem) -> str:
    if normalized.pack_count_source == "bill_text" and normalized.pack_count:
        return CERTAIN
    if normalized.pack_count and normalized.pack_count > 0:
        return BOUNDED
    return UNKNOWN


#: Unit bases that are CONTINUOUS MEASURES rather than counts of discrete
#: things. The distinction decides whether a stated pack size is the ceiling
#: row's own unit quantity or merely how many items came in the box.
#:
#:   "Injection 500 ml"  -> the ceiling row IS priced per 500 ml, so the
#:                          stated 500 is the row's unit quantity.
#:   "Tablet, PACK 15"   -> the ceiling row is priced per 1 TABLET. The 15 is
#:                          a pack count and must NOT be used as the row's
#:                          unit quantity, or the lookup searches for a
#:                          ceiling priced per-fifteen-tablets and finds none.
#:
#: Today only the first case reaches this code, because pack_count_source is
#: "bill_text" only when a volume appears in the item name. Class C will make
#: the second case reachable by reading the PACK column, and without this
#: guard every packed tablet would silently lose its ceiling and go gray.
MEASURE_UNIT_BASES = frozenset({"ml", "gm", "g", "mg", "litre", "l"})


def ceiling_row_unit_qty_for(normalized: NormalizedItem) -> Decimal:
    """The CEILING ROW's unit quantity for this item -- never a pack count."""
    if (
        normalized.pack_count_source == "bill_text"
        and normalized.pack_count
        and normalized.unit_basis in MEASURE_UNIT_BASES
    ):
        return normalized.pack_count
    return Decimal("1")


def _trusted_interpretations(
    interpretations: list[dict], normalized: NormalizedItem
) -> list[dict]:
    """Drop readings we hold EVIDENCE AGAINST. See D11.

    `per_billed_unit` treats the billed quantity as a count of base units --
    one strip read as one tablet. When pack_count is known that reading is not
    merely unlikely, it is CONTRADICTED: a strip of 10 is not 1 tablet, and we
    know it is 10.

    Measured 2026-09-19 in the adversarial audit: a compliant line (10 tablets
    at Rs 1.00 against a Rs 1.0416 allowance) was flagged AMBER for Rs 0.00,
    solely because the contradicted reading of Rs 10.00/tablet exceeded.

    Kept when pack_count == 1, where the two readings coincide anyway.
    """
    if not normalized.pack_count or normalized.pack_count <= 1:
        return interpretations
    kept = [i for i in interpretations if i["label"] != "per_billed_unit"]
    return kept or interpretations


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

    # ----------------------------------------------------------------------
    # THE UPPER-BOUND GATE. This is the strongest correctness claim in the
    # project, and it exists because a bill that says "Qty 10" often does not
    # say ten of WHAT.
    #
    # If one billed unit contains N base units, then
    #
    #     price per base unit  =  line_total / (qty x N)   for some N >= 1
    #                          <= line_total / qty
    #
    # So line_total/qty is an UPPER BOUND on the real per-unit price, never
    # the price itself. Two consequences, and they are not symmetric:
    #
    #   bound <= allowance  ->  the item is within the ceiling FOR EVERY
    #                           possible N. We can say green and be right
    #                           whatever the pack turns out to be.
    #
    #   bound >  allowance  ->  nothing follows. N=1 might be above the cap
    #                           and N=10 comfortably under it. Any verdict
    #                           here is a guess dressed as a finding.
    #
    # Treating the bound as if it were the price is what produced a RED flag
    # on a real wholesale invoice line priced at Rs 36 per STRIP against a
    # Rs 0.93 per-TABLET ceiling -- 38.7x, which slipped under the 50x
    # misread guard. See test_wholesale_strip_price_is_never_red.
    # ----------------------------------------------------------------------
    if pack_certainty(normalized) == UNKNOWN:
        upper_bound = min(i["per_unit"] for i in interpretations)
        if upper_bound <= amber_at:
            return None  # provably within the ceiling for every pack size
        return Flag(
            rule_id="R5",
            severity=Severity.GRAY,
            item_index=item.index,
            gray_reason=GrayReason.COULD_NOT_VERIFY,
            gray_detail=GrayDetail.PACK_SIZE_UNKNOWN,
            evidence={
                "ceiling_ex_gst": str(ceiling.price_ex_gst),
                "ceiling_unit": format_unit(ceiling.unit_qty, ceiling.unit_basis),
                "gst_percent": str(config.GST_PERCENT),
                "allowance_per_unit": str(_money(amber_at)),
                "upper_bound_per_unit": str(_money(upper_bound)),
                "why_undetermined": (
                    f"The bill shows a quantity of {item.quantity} but does not "
                    f"say how many {ceiling.unit_basis}s are in one of them. At "
                    f"{format_inr(_money(upper_bound))} per billed unit the price "
                    f"is above the {format_inr(_money(amber_at))} allowed for a "
                    f"single {ceiling.unit_basis}, but if one billed unit is a "
                    f"pack, the per-{ceiling.unit_basis} price would be lower "
                    f"and could be well within the ceiling."
                ),
                "reference": {
                    "ref_id": ceiling.ref_id,
                    "so_number": ceiling.so_number,
                    "so_date": ceiling.so_date,
                },
                "checked_for": ["arithmetic", "duplication"],
            },
        )

    for interpretation in interpretations:
        per_unit = interpretation["per_unit"]

        # TWO BASES, and they are not interchangeable.
        #
        # The GATE is defined against the GST-INCLUSIVE allowance: red needs
        # RED_EXCESS_FRACTION above `amber_at`, and amount_affected is
        # measured from `amber_at`. So the percentage we SHOW must use that
        # same base, or the number on the card is not the number we gated on.
        #
        # The ex-GST figure is kept because it is what a reader comparing
        # against the published NPPA table will compute by hand, and omitting
        # it would look like we were hiding the gap. Both are labelled.
        excess_over_allowance = (per_unit - amber_at) / amber_at
        excess_over_ceiling = (per_unit - ceiling.per_base_unit) / ceiling.per_base_unit

        interpretation["per_unit_str"] = str(_money(per_unit))
        interpretation["excess_over_allowance_pct"] = str(_pct(excess_over_allowance))
        interpretation["excess_over_ceiling_ex_gst_pct"] = str(_pct(excess_over_ceiling))
        interpretation["above_amber_threshold"] = per_unit > amber_at
        interpretation["above_red_threshold"] = per_unit > red_at
        interpretation["ratio_to_ceiling"] = str(
            (per_unit / ceiling.per_base_unit).quantize(Decimal("0.01"))
        )

    # The interpretation LEAST favourable to a flag decides. Using the
    # minimum per-unit price means an ambiguous pack size can never be the
    # reason an item turns red.
    # D11, AND THE DIRECTION IS DELIBERATELY ASYMMETRIC.
    #
    # Newly-trusted pack evidence may REMOVE a flag immediately. It may not
    # RAISE one tonight: suppression can only narrow what we say, while
    # promotion opens a new path to red and deserves its own validation pass.
    # A false accusation destroys the product; silence does not.
    #
    #   any_reading_above_amber -> computed on the TRUSTED set, so a
    #       contradicted reading can no longer raise a flag at all.
    #   every_reading_above_red -> computed on the FULL set, so dropping a
    #       reading can never turn an amber into a red.
    trusted = _trusted_interpretations(interpretations, normalized)

    decisive = min(trusted, key=lambda i: i["per_unit"])
    every_reading_above_red = all(i["above_red_threshold"] for i in interpretations)
    any_reading_above_amber = any(i["above_amber_threshold"] for i in trusted)

    # WHY THERE IS NO "UPGRADE WITHHELD" BRANCH HERE.
    #
    # Dropping per_billed_unit is STRUCTURALLY INCAPABLE of promoting an amber
    # to a red through this variable, and proving that is better than gating
    # it. per_billed_unit divides by qty; per_pack_unit divides by
    # qty * pack_count. With pack_count > 1 the dropped reading is always the
    # HIGHER one, and removing the largest element from a set can only make
    # `all(above_threshold)` stay the same or become False -- never True.
    #
    # The real promotion lever is elsewhere: `ratio` below uses the HIGHEST
    # per-unit reading, and narrowing THAT would shrink the ratio and let a
    # line past the 50x misread guard. It is deliberately left on the FULL
    # set, so the guard stays exactly as hard as it was before D11.

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
                # The gate basis -- this is what the card displays.
                "excess_over_allowance_pct": i["excess_over_allowance_pct"],
                "excess_basis": (
                    f"vs the GST-inclusive allowance of "
                    f"{_money(amber_at)}/unit, which is what the "
                    f"{_pct(config.RED_EXCESS_FRACTION)}% red threshold is "
                    f"measured against"
                ),
                # Informational: what you get comparing straight to the
                # published NPPA table, before GST is added.
                "excess_over_ceiling_ex_gst_pct": i["excess_over_ceiling_ex_gst_pct"],
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

def _resolution_is_complete(normalized: NormalizedItem) -> bool:
    """Did we resolve enough to make an ABSENCE meaningful?

    Claiming "no published ceiling exists for this item" is a claim about
    NPPA's coverage. We may only make it when we know WHICH item -- salt set,
    dosage form AND strength. With any of those missing, an empty search
    result does not prove absence; it proves we did not look precisely enough.

    D1 applies to claims about ourselves too: "there is no ceiling" and "we
    could not find a ceiling" are different statements, and only one of them
    is honest when the resolution is partial.
    """
    if not normalized.salt_components:
        return False
    if not normalized.dosage_form:
        return False
    has_strength = bool(normalized.strength_mg) or normalized.strength_kind not in (
        "", "none", None
    )
    return has_strength


def rule_r9_gray(
    item: VerifiedItem,
    normalized: NormalizedItem,
    ceiling_search_exhausted: bool = False,
) -> Flag:
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
        # A LINE NOBODY CHECKED IS NOT A LINE WE MISREAD.
        #
        # `is_high` is withheld for several different reasons and they are not
        # equally our fault. When the ONLY thing missing is a second reader --
        # the arithmetic holds, the figures are sane, there is money on the
        # line -- we have no evidence the reading is wrong, just nothing
        # confirming it is right. Saying "we could not read this reliably"
        # there is a false confession, and on a bill read perfectly it fills
        # the screen with them.
        reasons = set(item.reasons)
        unconfirmed = (
            "only_one_reader_ran" in reasons
            and "arithmetic_does_not_hold" not in reasons
            and "outside_sanity_bounds" not in reasons
            and item.line_total is not None
        )
        if unconfirmed:
            gray_detail = GrayDetail.NOT_CROSS_CHECKED
            explanation = (
                "Only one reader ran on this bill, so nothing confirmed this "
                "line and we have not compared its price. This is not a sign "
                "the line was read wrongly -- it means it was not "
                "double-checked. It was still checked for duplication and "
                "arithmetic."
            )
        else:
            gray_detail = GrayDetail.COULD_NOT_READ
            explanation = (
                "We could not read this line reliably, so we have not compared "
                "its price. It was still checked for duplication and arithmetic."
            )
    elif ceiling_search_exhausted and _resolution_is_complete(normalized):
        # WE KNOW WHAT THIS IS, AND INDIA DOES NOT PUBLISH A CEILING FOR IT.
        #
        # Reporting that as could_not_identify was a false statement about our
        # own system: we had the molecules, the strengths, the form and the
        # pack size. The DPCO schedule covers 915 formulations and this is not
        # one of them -- a limit of the SCHEDULE, not of the reading.
        #
        # Combination products are the common case. Pantoprazole alone has a
        # ceiling; pantoprazole + domperidone SR capsule does not.
        return Flag(
            rule_id="R9",
            severity=Severity.GRAY,
            item_index=item.index,
            gray_reason=GrayReason.NO_PUBLIC_CEILING,
            evidence={
                "category": normalized.category.value,
                "resolved_salts": list(normalized.salt_components),
                "resolved_form": normalized.dosage_form,
                "resolved_strength": [str(x) for x in normalized.strength_mg],
                "ceiling_search": "no_matching_row_in_published_list",
                "checked_for": ["arithmetic", "duplication"],
            },
            explanation=(
                "We identified this medicine, but India's published ceiling "
                "list does not cover this formulation, so there is no "
                "published price to compare it against. That means this item "
                "is not price-controlled — not that its price is correct. "
                "It was still checked for duplication and arithmetic."
            ),
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

    # A line worth more than the whole bill is a misread, and it poisons both
    # the line arithmetic and the reconciliation. Computed once, used by both.
    grand_total = stats.printed_grand_total
    any_line_implausible = any(
        _line_exceeds_whole_bill(i, grand_total) for i in items
    )

    bill_total_flag = rule_r2_bill_total(stats, any_line_implausible)
    if bill_total_flag:
        flags.append(bill_total_flag)

    flags.extend(rule_r3_exact_duplicates(items))
    flags.extend(rule_r4_near_duplicates(items))

    for item in items:
        norm = by_index.get(item.index) or NormalizedItem(index=item.index)

        arithmetic_flag = rule_r1_line_arithmetic(item, grand_total)
        if arithmetic_flag:
            flags.append(arithmetic_flag)

        priced = False
        # Did we actually RUN a ceiling search and come back empty? Only then
        # can an absence be reported as an absence. A search we never ran
        # proves nothing about NPPA's coverage.
        ceiling_search_exhausted = False
        # A non-HIGH reading is excluded from every price rule, and a
        # service or consumable has no ceiling to be compared against.
        if item.is_high and norm.category not in NO_CEILING_CATEGORIES and norm.salt_components:
            ceiling = select_ceiling(
                salt_components=norm.salt_components,
                dosage_form=norm.dosage_form,
                strength_mg=norm.strength_mg,
                strength_kind=norm.strength_kind,
                unit_basis=norm.unit_basis or _unit_basis_for(norm),
                ceiling_row_unit_qty=ceiling_row_unit_qty_for(norm),
                form_modifier=norm.form_modifier,
            )
            ceiling_search_exhausted = ceiling is None
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
                            "allowance_per_unit": str(_money(
                                config.amber_threshold(ceiling.per_base_unit)
                            )),
                            "gst_percent": str(config.GST_PERCENT),
                            "pack_size_certainty": pack_certainty(norm),
                            # A green reached through the upper-bound gate is
                            # STRONGER than an ordinary one: it holds for every
                            # possible pack size, so learning what the pack was
                            # could never overturn it.
                            "holds_for_every_pack_size":
                                pack_certainty(norm) == UNKNOWN,
                            "so_number": ceiling.so_number,
                            "so_date": ceiling.so_date,
                            "ref_id": ceiling.ref_id,
                        },
                    ))

        if not priced:
            flags.append(rule_r9_gray(item, norm, ceiling_search_exhausted))

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
