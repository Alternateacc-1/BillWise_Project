"""Phase 1: verifier, matcher, rules, explainer, and the end-to-end CLI path."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app import config
from app.cli import run_audit
from app.models import (
    BillInput,
    Flag,
    GrayDetail,
    GrayReason,
    ItemCategory,
    MatchType,
    NormalizedItem,
    ReaderItem,
    ReadingConfidence,
    Reconciliation,
    Severity,
    VerifiedItem,
)
from app.pipeline import explain as explain_mod
from app.pipeline.audit import audit, rule_r1_line_arithmetic, rule_r5_above_ceiling
from app.pipeline.match import select_ceiling
from app.pipeline.normalize import categorise, normalize_bill
from app.pipeline.verify import verify_bill, verify_item

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "eval" / "fixtures" / "bill_01.json"


def reader_item(**kwargs) -> ReaderItem:
    base = dict(
        index=1, name="Paracetamol 500mg Tablet", quantity=Decimal("10"),
        unit_price=Decimal("1.00"), line_total=Decimal("10.00"), confidence=Decimal("98"),
    )
    base.update(kwargs)
    return ReaderItem(**base)


# --------------------------------------------------------------------------
# The unknown-modifier ruling
# --------------------------------------------------------------------------

def test_unknown_modifier_selects_the_highest_ceiling():
    """Unknown resolves in the hospital's favour.

    Acetylsalicylic acid 75 mg exists as a plain tablet (Rs 0.39) and, under
    the ASPIRIN spelling, as a dispersible tablet (Rs 0.36). A bill line that
    does not state the form must gate against the HIGHER of the candidates.
    """
    unknown = select_ceiling(
        ["ACETYLSALICYLIC ACID"], "tablet", [75.0], "mg", "tablet",
        Decimal("1"), form_modifier=None,
    )
    assert unknown is not None
    assert unknown.price_ex_gst == Decimal("0.39")


def test_explicitly_stated_modifier_is_matched_exactly():
    """"" means PLAIN, and is not the same as unknown."""
    plain = select_ceiling(
        ["ACETYLSALICYLIC ACID"], "tablet", [75.0], "mg", "tablet",
        Decimal("1"), form_modifier="",
    )
    assert plain.price_ex_gst == Decimal("0.39")

    dispersible = select_ceiling(
        ["ASPIRIN"], "tablet", [75.0], "mg", "tablet",
        Decimal("1"), form_modifier="dispersible",
    )
    assert dispersible.price_ex_gst == Decimal("0.36")


def test_unknown_modifier_is_flagged_only_when_it_mattered():
    """A stent has no release variants, so the note must not appear."""
    stent = select_ceiling(
        ["BARE METAL STENTS"], "device", [], "none", "unit",
        Decimal("1"), form_modifier=None,
    )
    assert stent is not None
    assert stent.modifier_was_unknown is False


def test_unknown_modifier_never_lowers_the_ceiling():
    """Widening must be monotonic: it can only ever raise the ceiling."""
    for salts, strengths in ([["PARACETAMOL"], [500.0]], [["PARACETAMOL"], [650.0]]):
        plain = select_ceiling(salts, "tablet", strengths, "mg", "tablet", Decimal("1"), "")
        unknown = select_ceiling(salts, "tablet", strengths, "mg", "tablet", Decimal("1"), None)
        assert unknown is not None
        if plain is not None:
            assert unknown.per_base_unit >= plain.per_base_unit


# --------------------------------------------------------------------------
# Verifier
# --------------------------------------------------------------------------

def test_agreeing_readers_with_sound_arithmetic_are_high():
    item = verify_item(reader_item(), reader_item())
    assert item.confidence is ReadingConfidence.HIGH


def test_disagreeing_line_totals_are_not_high():
    item = verify_item(reader_item(), reader_item(line_total=Decimal("99.00")))
    assert item.confidence is ReadingConfidence.UNVERIFIED
    assert "readers_disagree_on_line_total" in item.reasons


def test_broken_arithmetic_is_not_high():
    a = reader_item(line_total=Decimal("25.00"))
    item = verify_item(a, a)
    assert item.confidence is ReadingConfidence.UNVERIFIED
    assert "arithmetic_does_not_hold" in item.reasons


def test_single_reader_needs_95_confidence():
    high = verify_item(reader_item(confidence=Decimal("96")), None)
    assert high.confidence is ReadingConfidence.HIGH
    low = verify_item(reader_item(confidence=Decimal("80")), None)
    assert low.confidence is ReadingConfidence.UNVERIFIED


@pytest.mark.parametrize(
    "quantity, unit_price",
    [
        (Decimal("0"), Decimal("1.00")),        # below quantity floor
        (Decimal("900"), Decimal("1.00")),      # above quantity ceiling
        (Decimal("10"), Decimal("0.01")),       # below price floor
        (Decimal("10"), Decimal("900000")),     # above price ceiling
    ],
)
def test_sanity_bounds_reject_implausible_values(quantity, unit_price):
    a = reader_item(
        quantity=quantity, unit_price=unit_price, line_total=quantity * unit_price
    )
    assert verify_item(a, a).confidence is ReadingConfidence.UNVERIFIED


def test_a_line_with_no_money_on_it_is_never_well_read():
    """No line total means no charge to audit.

    Narrowed from "missing values never count as agreement" when Class A
    landed. That older, broader rule ALSO rejected a line that simply had no
    unit-price column, which is the commonest retail pharmacy layout in India
    -- on the deployed stack it made all six lines of such a bill unreadable.

    The distinction that survives: a missing UNIT PRICE is recoverable,
    because line_total/qty still bounds the per-unit price. A missing LINE
    TOTAL is not -- there is no money on the line at all, and calling it
    well-read would be a claim about a name and a quantity.
    """
    a = reader_item(unit_price=None, line_total=None)
    assert verify_item(a, a).confidence is ReadingConfidence.UNVERIFIED


def test_two_readers_agreeing_a_field_is_absent_is_agreement():
    """CLASS A. The bill prints MRP/PACK/QTY/TOTAL and no unit-price column.

    Both readers correctly report no unit price. That is agreement, and the
    line is fully auditable: line_total/qty bounds the per-unit price, which
    is exactly what the upper-bound gate consumes. Previously
    `_close(None, None)` was False, `arithmetic_holds()` returned None where
    True was demanded, and `within_sanity_bounds()` failed on the missing
    value -- three separate rejections of one ordinary bill format.
    """
    a = reader_item(unit_price=None, line_total=Decimal("134.48"),
                    quantity=Decimal("8"))
    assert verify_item(a, a).confidence is ReadingConfidence.HIGH


# --------------------------------------------------------------------------
# Categorisation and the two gray reasons
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name, category",
    [
        ("Room Rent - Semi Private Ward", ItemCategory.SERVICE),
        ("Nursing Charges", ItemCategory.SERVICE),
        ("OT Charges - Minor Procedure", ItemCategory.SERVICE),
        ("CBC - Complete Blood Count", ItemCategory.SERVICE),
        ("Disposable Syringe 5ml", ItemCategory.CONSUMABLE),
        ("IV Set with Cannula", ItemCategory.CONSUMABLE),
        ("Surgical Gloves Pair", ItemCategory.CONSUMABLE),
        ("Paracetamol 500mg Tablet", ItemCategory.DRUG),
        ("Inj Ceftriaxone 1g", ItemCategory.DRUG),
    ],
)
def test_categorisation(name, category):
    assert categorise(name) == category


def test_services_and_consumables_get_no_public_ceiling():
    """The reason that is a FEATURE, not a failure."""
    items = [
        VerifiedItem(index=1, name="Room Rent - Private Ward",
                     quantity=Decimal("1"), unit_price=Decimal("3500"),
                     line_total=Decimal("3500"), confidence=ReadingConfidence.HIGH),
        VerifiedItem(index=2, name="Disposable Syringe 5ml",
                     quantity=Decimal("2"), unit_price=Decimal("18"),
                     line_total=Decimal("36"), confidence=ReadingConfidence.HIGH),
    ]
    flags = audit(items, normalize_bill(items), _stats())
    grays = [f for f in flags if f.rule_id == "R9"]
    assert len(grays) == 2
    assert all(f.gray_reason is GrayReason.NO_PUBLIC_CEILING for f in grays)


def test_unreadable_drug_line_gets_could_not_verify():
    """The reason that IS a failure, and must not be confused with the other."""
    items = [VerifiedItem(
        index=1, name="Zxqv 250mg Tablet", quantity=Decimal("1"),
        unit_price=Decimal("50"), line_total=Decimal("50"),
        confidence=ReadingConfidence.UNVERIFIED,
    )]
    flags = audit(items, normalize_bill(items), _stats())
    gray = next(f for f in flags if f.rule_id == "R9")
    assert gray.gray_reason is GrayReason.COULD_NOT_VERIFY


def test_the_two_gray_reasons_are_never_the_same_value():
    assert GrayReason.NO_PUBLIC_CEILING.value != GrayReason.COULD_NOT_VERIFY.value


# --------------------------------------------------------------------------
# R1 and R5
# --------------------------------------------------------------------------

def test_r1_catches_a_line_that_does_not_add_up():
    item = VerifiedItem(
        index=1, name="Pantop 40mg Tablet", quantity=Decimal("10"),
        unit_price=Decimal("12.50"), line_total=Decimal("130.00"),
        confidence=ReadingConfidence.HIGH,
    )
    flag = rule_r1_line_arithmetic(item)
    assert flag is not None
    assert flag.severity is Severity.AMBER
    assert flag.amount_affected == Decimal("5.00")
    assert "125.00" in flag.evidence["arithmetic"]


def test_r1_abstains_when_the_line_charges_LESS_than_qty_times_rate():
    """CLASS F. A per-line discount column is not an arithmetic error.

    10 x 12.00 = 120.00 while the line charges 108.00, because the bill shows
    a 10% discount on the line. Querying that asks a pharmacy to explain its
    own discount -- the same wrong question R2 used to ask about a bill-level
    discount, one scale down.

    This is the third and last scale of one bug: bill totals (Class B),
    section subtotals read as line items (Class E) and line adjustments
    (Class F). The rule at every scale is the direction, not a subtotal
    detector: a computed amount ABOVE the printed one means we failed to read
    a deduction, not that the bill is wrong.
    """
    item = VerifiedItem(
        index=1, name="X", quantity=Decimal("10"),
        unit_price=Decimal("12.00"), line_total=Decimal("108.00"),
        confidence=ReadingConfidence.HIGH,
    )
    assert rule_r1_line_arithmetic(item) is None


def test_r1_still_fires_when_the_line_charges_MORE_than_qty_times_rate():
    """The other direction, pinned so the Class F fix cannot silence R1.

    The narrowing is only safe because this case survives it. A line asking
    for more than it itemises is the direction worth a question, and it is
    what bill_01 line 13 is in the eval.
    """
    item = VerifiedItem(
        index=1, name="X", quantity=Decimal("10"),
        unit_price=Decimal("12.00"), line_total=Decimal("132.00"),
        confidence=ReadingConfidence.HIGH,
    )
    flag = rule_r1_line_arithmetic(item)
    assert flag is not None
    assert flag.amount_affected == Decimal("12.00")


def test_r1_tolerates_rounding_within_one_rupee():
    item = VerifiedItem(
        index=1, name="X", quantity=Decimal("3"), unit_price=Decimal("3.33"),
        line_total=Decimal("10.00"), confidence=ReadingConfidence.HIGH,
    )
    assert rule_r1_line_arithmetic(item) is None


def _drug(index=1, **kwargs) -> NormalizedItem:
    # pack_count 1 from bill_text = the pack size is CERTAIN, so these tests
    # exercise the four red guards rather than the upper-bound gate, which
    # has its own tests below.
    base = dict(
        index=index, category=ItemCategory.DRUG, match_type=MatchType.EXACT,
        salt_components=["PARACETAMOL"], strength_mg=[500.0], strength_kind="mg",
        dosage_form="tablet", unit_basis="tablet", form_modifier=None,
        pack_count=Decimal("1"), pack_unit="tablet", pack_count_source="bill_text",
    )
    base.update(kwargs)
    return NormalizedItem(**base)


def _item(index=1, **kwargs) -> VerifiedItem:
    base = dict(
        index=index, name="Paracetamol 500mg Tablet", quantity=Decimal("10"),
        unit_price=Decimal("1.00"), line_total=Decimal("10.00"),
        confidence=ReadingConfidence.HIGH,
    )
    base.update(kwargs)
    return VerifiedItem(**base)


def _ceiling():
    return select_ceiling(
        ["PARACETAMOL"], "tablet", [500.0], "mg", "tablet", Decimal("1"), None
    )


def test_r5_stays_silent_within_the_ceiling():
    # ceiling 0.93 -> amber above 1.0416
    assert rule_r5_above_ceiling(
        _item(line_total=Decimal("10.00")), _drug(), _ceiling()
    ) is None


def test_r5_is_amber_inside_the_25_percent_band():
    """The band you asked the eval runner to report separately."""
    flag = rule_r5_above_ceiling(
        _item(line_total=Decimal("11.00")), _drug(), _ceiling()
    )
    assert flag is not None
    assert flag.severity is Severity.AMBER
    excess = flag.evidence["interpretations"][0]["excess_over_allowance_pct"]
    assert Decimal(excess) > 0


def test_r5_shows_the_full_arithmetic_and_excess_percentage():
    flag = rule_r5_above_ceiling(
        _item(line_total=Decimal("40.00")), _drug(), _ceiling()
    )
    evidence = flag.evidence
    for key in ("ceiling_ex_gst", "gst_percent", "gst_multiplier",
                "amber_threshold", "red_threshold", "arithmetic"):
        assert key in evidence, key
    assert "excess_over_allowance_pct" in evidence["interpretations"][0]
    assert evidence["reference"]["so_number"]
    assert evidence["reference"]["so_date"]


def test_r5_requires_a_high_confidence_reading():
    flag = rule_r5_above_ceiling(
        _item(line_total=Decimal("400.00"), confidence=ReadingConfidence.UNVERIFIED),
        _drug(), _ceiling(),
    )
    assert flag.severity is Severity.AMBER
    assert "reading_not_high_confidence" in flag.evidence["not_red_because"]


def test_r5_requires_an_exact_match_type():
    flag = rule_r5_above_ceiling(
        _item(line_total=Decimal("400.00")),
        _drug(match_type=MatchType.PROBABLE), _ceiling(),
    )
    assert flag.severity is Severity.AMBER
    assert any("match_type" in r for r in flag.evidence["not_red_because"])


def test_r5_respects_the_minimum_amount_affected():
    flag = rule_r5_above_ceiling(
        _item(quantity=Decimal("1"), unit_price=Decimal("2"), line_total=Decimal("2.00")),
        _drug(), _ceiling(),
    )
    assert flag.severity is Severity.AMBER
    assert any("amount_affected_below_minimum" in r for r in flag.evidence["not_red_because"])


def test_r5_treats_an_absurd_ratio_as_our_own_misread():
    """Above 50x we assume the reading is wrong, not the bill."""
    flag = rule_r5_above_ceiling(
        _item(quantity=Decimal("10"), line_total=Decimal("10000.00")),
        _drug(), _ceiling(),
    )
    assert flag.severity is Severity.AMBER
    assert any("suggesting_a_misread" in r for r in flag.evidence["not_red_because"])


def test_r5_dual_interpretation_needs_both_readings_above_red():
    """An ambiguous pack size can never be the reason an item turns red.

    Qty 1 at Rs 223 is either one tablet (well above the ceiling) or one
    strip of 10 (below it). Only one reading exceeds the threshold, so this
    is amber with the ambiguity stated -- never red.
    """
    normalized = _drug(
        salt_components=["AMOXICILLIN", "CLAVULANIC ACID"],
        strength_mg=[500.0, 125.0],
        pack_count=Decimal("10"), pack_unit="tablet",
        pack_count_source="brand_index",
    )
    ceiling = select_ceiling(
        ["AMOXICILLIN", "CLAVULANIC ACID"], "tablet", [500.0, 125.0], "mg",
        "tablet", Decimal("1"), None,
    )
    flag = rule_r5_above_ceiling(
        _item(quantity=Decimal("1"), unit_price=Decimal("223"),
              line_total=Decimal("223.00")),
        normalized, ceiling,
    )
    assert flag is not None
    assert flag.severity is Severity.AMBER
    assert "pack_size_ambiguous_only_one_interpretation_exceeds_threshold" in \
        flag.evidence["not_red_because"]
    assert len(flag.evidence["interpretations"]) == 2
    assert "pack_size_note" in flag.evidence


def test_r5_goes_red_when_both_interpretations_exceed_the_threshold():
    normalized = _drug(
        salt_components=["AMOXICILLIN", "CLAVULANIC ACID"],
        strength_mg=[500.0, 125.0],
        pack_count=Decimal("10"), pack_unit="tablet",
        pack_count_source="brand_index",
    )
    ceiling = select_ceiling(
        ["AMOXICILLIN", "CLAVULANIC ACID"], "tablet", [500.0, 125.0], "mg",
        "tablet", Decimal("1"), None,
    )
    flag = rule_r5_above_ceiling(
        _item(quantity=Decimal("2"), unit_price=Decimal("640"),
              line_total=Decimal("1280.00")),
        normalized, ceiling,
    )
    assert flag.severity is Severity.RED
    assert "not_red_because" not in flag.evidence


def test_a_stated_pack_size_produces_only_one_interpretation():
    """"Injection 500 ml" is not ambiguous, so no second reading is invented."""
    normalized = _drug(
        salt_components=["RINGER LACTATE"], strength_mg=[], strength_kind="none",
        dosage_form="injection", unit_basis="ml",
        pack_count=Decimal("500"), pack_unit="ml", pack_count_source="bill_text",
    )
    ceiling = select_ceiling(
        ["RINGER LACTATE"], "injection", [], "none", "ml", Decimal("500"), None
    )
    flag = rule_r5_above_ceiling(
        _item(quantity=Decimal("4"), unit_price=Decimal("200"),
              line_total=Decimal("800.00")),
        normalized, ceiling,
    )
    assert flag is not None
    assert len(flag.evidence["interpretations"]) == 1


# --------------------------------------------------------------------------
# The upper-bound gate: the strongest correctness claim in the project
# --------------------------------------------------------------------------

def _unknown_pack(**kwargs) -> NormalizedItem:
    """A resolved drug whose pack size the bill never states."""
    return _drug(pack_count=None, pack_unit="", pack_count_source="", **kwargs)


def test_wholesale_strip_price_is_never_red():
    """REGRESSION. A real wholesale line produced a false RED.

    "Paracetamol 500 mg Tablet, Qty 10, Rs 360" is Rs 36 per STRIP -- an
    ordinary business-to-business price. Measured against a Rs 0.93
    per-TABLET ceiling it looked like 38.7x, which slipped under the 50x
    misread guard and fired red. The bill never said whether 10 meant
    tablets or strips.
    """
    flag = rule_r5_above_ceiling(
        _item(quantity=Decimal("10"), unit_price=Decimal("40"),
              discount=Decimal("40"), line_total=Decimal("360.00")),
        _unknown_pack(), _ceiling(),
    )
    assert flag is not None
    assert flag.severity is Severity.GRAY
    assert flag.gray_detail is GrayDetail.PACK_SIZE_UNKNOWN
    assert flag.severity is not Severity.RED


def test_under_the_allowance_is_green_whatever_the_pack_size():
    """The asymmetry. Under the allowance, the bound settles it for every N.

    If one billed unit contains N >= 1 tablets, the real per-tablet price is
    line_total/(qty*N) <= line_total/qty. So when the bound itself is under
    the cap, every possible N is under the cap too.
    """
    assert rule_r5_above_ceiling(
        _item(quantity=Decimal("20"), unit_price=Decimal("0.90"),
              line_total=Decimal("18.00")),
        _unknown_pack(), _ceiling(),
    ) is None


def test_over_the_allowance_with_an_unknown_pack_concludes_nothing():
    flag = rule_r5_above_ceiling(
        _item(quantity=Decimal("20"), unit_price=Decimal("1.50"),
              line_total=Decimal("30.00")),
        _unknown_pack(), _ceiling(),
    )
    assert flag.severity is Severity.GRAY
    assert flag.gray_detail is GrayDetail.PACK_SIZE_UNKNOWN
    assert "upper_bound_per_unit" in flag.evidence
    assert "why_undetermined" in flag.evidence


def test_an_unknown_pack_size_can_never_produce_red_or_amber_on_price():
    """Swept across four orders of magnitude. No price may reach red or amber."""
    for total in ["18.00", "30.00", "360.00", "3600.00", "36000.00"]:
        flag = rule_r5_above_ceiling(
            _item(quantity=Decimal("10"), unit_price=Decimal(total) / 10,
                  line_total=Decimal(total)),
            _unknown_pack(), _ceiling(),
        )
        if flag is not None:
            assert flag.severity is Severity.GRAY, f"{total} produced {flag.severity}"


def test_a_known_pack_size_still_reaches_red():
    """The gate must not disarm the rule it protects."""
    normalized = _drug(
        salt_components=["AMOXICILLIN", "CLAVULANIC ACID"],
        strength_mg=[500.0, 125.0], pack_count=Decimal("10"),
        pack_unit="tablet", pack_count_source="brand_index",
    )
    ceiling = select_ceiling(
        ["AMOXICILLIN", "CLAVULANIC ACID"], "tablet", [500.0, 125.0], "mg",
        "tablet", Decimal("1"), None,
    )
    flag = rule_r5_above_ceiling(
        _item(quantity=Decimal("2"), unit_price=Decimal("350"),
              line_total=Decimal("700.00")),
        normalized, ceiling,
    )
    assert flag.severity is Severity.RED


def test_the_green_explanation_states_the_stronger_claim():
    from app.pipeline.explain import explain
    flags = audit(
        [_item(quantity=Decimal("20"), unit_price=Decimal("0.90"),
               line_total=Decimal("18.00"), name="Paracetamol 500mg Tablet")],
        [_unknown_pack()], _stats(),
    )
    green = next(f for f in flags if f.severity is Severity.GREEN)
    assert green.evidence["holds_for_every_pack_size"] is True
    text = explain(green)
    assert "however the quantity is counted" in text


# --------------------------------------------------------------------------
# Explainer language rules
# --------------------------------------------------------------------------

def test_no_explanation_ever_accuses_anyone():
    bill = BillInput.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    items, stats = verify_bill(bill)
    flags = explain_mod.explain_all(audit(items, normalize_bill(items), stats))
    assert flags
    for flag in flags:
        text = f"{flag.explanation} {flag.suggested_question}".lower()
        for word in explain_mod.FORBIDDEN_WORDS:
            assert word not in text, f"{flag.rule_id}: {word!r} in {text!r}"


def test_explanations_introduce_no_number_absent_from_evidence():
    """The contract the Bedrock explainer will be held to in Phase 4."""
    import re
    bill = BillInput.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    items, stats = verify_bill(bill)
    flags = explain_mod.explain_all(audit(items, normalize_bill(items), stats))

    for flag in flags:
        available = set(re.findall(r"\d+(?:\.\d+)?", str(flag.evidence)))
        available |= set(re.findall(r"\d+(?:\.\d+)?", str(flag.amount_affected)))
        # Digit grouping is formatting, not a new number.
        for number in re.findall(r"\d+(?:\.\d+)?", flag.explanation.replace(",", "")):
            assert number in available, (
                f"{flag.rule_id} explanation cites {number!r}, which is not in "
                f"its evidence"
            )


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------

def _stats():
    from app.models import ReadingStats
    return ReadingStats(reconciliation=Reconciliation.NO_TOTAL_FOUND)


def test_the_fixture_produces_a_full_report():
    bill = BillInput.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    items, stats = verify_bill(bill)
    normalized = normalize_bill(items)
    flags = audit(items, normalized, stats)

    assert len(items) == 16
    assert stats.reconciliation is Reconciliation.RECONCILED
    assert any(f.severity is Severity.RED for f in flags)
    assert any(f.severity is Severity.AMBER for f in flags)
    assert any(f.severity is Severity.GREEN for f in flags)
    assert any(f.severity is Severity.GRAY for f in flags)

    # Both gray reasons must be present -- a realistic bill has both.
    reasons = {f.gray_reason for f in flags if f.gray_reason}
    assert GrayReason.NO_PUBLIC_CEILING in reasons
    assert GrayReason.COULD_NOT_VERIFY in reasons


def test_the_stent_is_red_and_the_ringer_bag_is_green():
    bill = BillInput.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    items, stats = verify_bill(bill)
    flags = audit(items, normalize_bill(items), stats)

    stent = [f for f in flags if f.item_index == 14 and f.rule_id == "R5"]
    assert stent and stent[0].severity is Severity.RED

    ringer = [f for f in flags if f.item_index == 12 and f.rule_id == "R5"]
    assert ringer and ringer[0].severity is Severity.GREEN


def test_duplicate_consumable_is_flagged_but_never_priced():
    bill = BillInput.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    items, stats = verify_bill(bill)
    flags = audit(items, normalize_bill(items), stats)
    for_line_9 = [f for f in flags if f.item_index == 9]
    assert any(f.rule_id == "R3" for f in for_line_9)
    assert all(f.severity is not Severity.RED for f in for_line_9)


def test_cli_runs_and_exits_zero(capsys):
    assert run_audit(FIXTURE) == 0
    out = capsys.readouterr().out
    assert "BillWise report" in out
    assert "no public price ceiling" in out.lower()
    assert "NPPA data retrieved" in out


def test_cli_json_output_is_machine_readable(capsys):
    import json
    assert run_audit(FIXTURE, as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["bill_id"] == "bill_01"
    assert payload["flags"]


def test_the_pipeline_is_deterministic():
    bill = BillInput.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    runs = []
    for _ in range(2):
        items, stats = verify_bill(bill)
        flags = audit(items, normalize_bill(items), stats)
        runs.append([(f.rule_id, f.severity, f.item_index, f.amount_affected) for f in flags])
    assert runs[0] == runs[1]


def test_config_thresholds_are_the_approved_values():
    assert config.GST_PERCENT == Decimal("12")
    assert config.RED_EXCESS_FRACTION == Decimal("0.25")
    assert config.RED_MIN_AMOUNT_AFFECTED == Decimal("50")
    assert config.RED_MAX_RATIO == Decimal("50")
    assert config.PROVIDER == "local"


# --------------------------------------------------------------------------
# A misread line must not become an accusation.
#
# These pin behaviour measured on the DEPLOYED stack on 2026-09-19, which is
# the only reason they exist as concrete numbers rather than invented ones.
# --------------------------------------------------------------------------

def _bill_from(items, printed_total):
    from app.models import ReaderOutput
    return BillInput(
        bill_id="t", hospital_name="", bill_date="",
        reader_a=ReaderOutput(source="textract", items=items,
                              printed_grand_total=printed_total),
    )


def _run(bill):
    from app.pipeline.audit import audit
    from app.pipeline.normalize import normalize_bill
    from app.pipeline.verify import verify_bill
    verified, stats = verify_bill(bill)
    return audit(verified, normalize_bill(verified), stats)


def test_a_lost_decimal_point_does_not_become_an_arithmetic_accusation():
    """REGRESSION, from real Textract output on eval/demo_bills/bill_05.jpg.

    Textract read 7.20 as "7" and 72.00 as "7200" -- a lost decimal point, a
    100x error. R1 then reported a Rs 7,130 discrepancy and R2 a Rs 7,018 one,
    on a bill whose printed total is Rs 190. Total amount affected came to
    Rs 14,148.80 on a Rs 190 bill.

    Both were arithmetically correct and both blamed the pharmacy for our own
    reading error. A single line cannot be worth more than the whole bill;
    when it appears to be, WE are wrong.
    """
    items = [
        ReaderItem(index=1, name="Paracetamol 500mg Tablet",
                   quantity=Decimal("10"), unit_price=Decimal("0.88"),
                   line_total=Decimal("8.80"), confidence=Decimal("99.27")),
        ReaderItem(index=2, name="Amaricillin 500mg Cap",
                   quantity=Decimal("10"), unit_price=Decimal("7"),
                   line_total=Decimal("7200"), confidence=Decimal("97.85")),
    ]
    flags = _run(_bill_from(items, Decimal("190")))

    assert not [f for f in flags if f.rule_id == "R1"], (
        "R1 fired on a line worth more than the entire bill"
    )
    assert not [f for f in flags if f.rule_id == "R2"], (
        "R2 reconciled against a sum poisoned by a misread line"
    )
    assert sum(Decimal(str(f.amount_affected)) for f in flags) == 0

    misread = [f for f in flags if f.item_index == 2]
    assert misread and misread[0].severity is Severity.GRAY
    assert misread[0].gray_detail is GrayDetail.COULD_NOT_READ


def test_a_genuine_arithmetic_error_is_still_caught():
    """The counterpart. The gate must not silence real findings.

    The first version of this fix gated R1 on `is_high`, which is CIRCULAR:
    verify.py only grants HIGH when `arithmetic is True`, so R1 could never
    fire on a line that had an arithmetic error -- it became dead code. The
    eval caught it. This test makes that mistake impossible to repeat.

    Here both readers agree on every number and the line is plausible, so the
    discrepancy is the BILL's and we say so.
    """
    items = [
        ReaderItem(index=1, name="Pantop 40mg Tablet", quantity=Decimal("10"),
                   unit_price=Decimal("12.50"), line_total=Decimal("130.00"),
                   confidence=Decimal("95")),
    ]
    flags = _run(_bill_from(items, Decimal("130.00")))

    r1 = [f for f in flags if f.rule_id == "R1"]
    assert r1, "a real arithmetic error on a well-read line must still flag"
    assert r1[0].amount_affected == Decimal("5.00")


def test_r1_abstains_when_the_readers_disagree_on_the_numbers():
    """A name disagreement is not enough to silence R1 -- arithmetic does not
    depend on the name. A NUMBER disagreement is, because we then do not know
    which number to compute with."""
    from app.models import ReaderOutput
    a = ReaderItem(index=1, name="Paracetamol 500mg Tablet",
                   quantity=Decimal("10"), unit_price=Decimal("12.50"),
                   line_total=Decimal("130.00"), confidence=Decimal("95"))
    b = ReaderItem(index=1, name="Paracetamol 500mg Tablet",
                   quantity=Decimal("10"), unit_price=Decimal("12.50"),
                   line_total=Decimal("125.00"), confidence=Decimal("95"))
    bill = BillInput(
        bill_id="t", hospital_name="", bill_date="",
        reader_a=ReaderOutput(source="textract", items=[a],
                              printed_grand_total=Decimal("130.00")),
        reader_b=ReaderOutput(source="vision", items=[b],
                              printed_grand_total=Decimal("130.00")),
    )
    assert not [f for f in _run(bill) if f.rule_id == "R1"]


def test_a_bill_charging_less_than_its_lines_is_not_a_finding():
    """REGRESSION, from real Textract output on eval/demo_bills/bill_06.pdf.

    Textract read the NET amount (431.00) as the grand total, while the six
    lines sum to the SUBTOTAL (453.94). We flagged the Rs 22.94 difference --
    which is exactly the pharmacy's own printed Discount (22.70) plus Round
    Off (0.24).

    We asked a patient to query a bill for charging them LESS. R2 exists to
    protect against being asked for MORE than the bill itemises; the opposite
    direction is a discount, not a harm.
    """
    from app.models import ReaderOutput
    lines = [("PANTOCID DSR CAP", "8", "134.48"), ("OFIVAY OZ TAB", "8", "107.20"),
             ("SINALATE TAB", "8", "54.00"), ("EFERIM SP TAB", "8", "78.32"),
             ("BECOSULE CAP", "4", "12.44"), ("MEDINOZE NASAL SPRAY", "1", "67.50")]
    items = [
        ReaderItem(index=n, name=nm, quantity=Decimal(q), unit_price=None,
                   line_total=Decimal(t), confidence=Decimal("88.65"))
        for n, (nm, q, t) in enumerate(lines, start=1)
    ]
    bill = BillInput(
        bill_id="t", hospital_name="", bill_date="",
        reader_a=ReaderOutput(source="textract", items=items,
                              printed_grand_total=Decimal("431.00")),
    )
    from app.pipeline.verify import verify_bill
    verified, stats = verify_bill(bill)

    assert stats.sum_of_line_totals == Decimal("453.94")
    assert stats.reconciliation is Reconciliation.BELOW_LINE_SUM

    flags = _run(bill)
    assert not [f for f in flags if f.rule_id == "R2"], (
        "queried a bill for charging the patient LESS than it itemises"
    )
    assert sum(Decimal(str(f.amount_affected)) for f in flags) == 0


def test_a_bill_asking_for_more_than_its_lines_is_still_a_finding():
    """The counterpart. The asymmetry must not silence the direction that
    actually costs a patient money."""
    from app.models import ReaderOutput
    items = [
        ReaderItem(index=1, name="Paracetamol 500mg Tablet", quantity=Decimal("10"),
                   unit_price=Decimal("0.90"), line_total=Decimal("9.00"),
                   confidence=Decimal("99")),
    ]
    bill = BillInput(
        bill_id="t", hospital_name="", bill_date="",
        reader_a=ReaderOutput(source="textract", items=items,
                              printed_grand_total=Decimal("109.00")),
    )
    from app.pipeline.verify import verify_bill
    _, stats = verify_bill(bill)
    assert stats.reconciliation is Reconciliation.MISMATCH

    r2 = [f for f in _run(bill) if f.rule_id == "R2"]
    assert r2, "a bill asking for Rs 100 more than its lines must be flagged"
    assert r2[0].amount_affected == Decimal("100.00")


# --------------------------------------------------------------------------
# Dosage-form abbreviation aliases (brand-index lookup only)
# --------------------------------------------------------------------------

def test_form_abbreviations_expand_for_lookup_only():
    """CAP -> capsule, TAB -> tablet, as INDEX KEYS.

    A real pharmacy bill writes "PANTOCID DSR CAP" while the brand index is
    keyed "pantocid dsr capsule". Three of six lines on a measured bill were
    lost to that spelling convention and labelled could_not_identify, which
    blames us for something that is not our failure.
    """
    from app.pipeline.normalize import brand_lookup_aliases

    assert brand_lookup_aliases("pantocid dsr cap") == ["pantocid dsr capsule"]
    assert brand_lookup_aliases("sinalate tab") == ["sinalate tablet"]
    assert brand_lookup_aliases("xyz inj") == ["xyz injection"]

    # No abbreviation present -> nothing extra to try. Never returns the
    # original, which would be a wasted second lookup of the same key.
    assert brand_lookup_aliases("paracetamol 500mg tablet") == []
    assert brand_lookup_aliases("medinoze nasal spray") == []


def test_the_alias_table_cannot_cross_a_release_modifier():
    """D5 MUST HOLD: form_modifier is product identity.

    NPPA prices release variants separately -- dispersible aspirin is Rs 0.36
    and plain aspirin is Rs 0.39 -- so an expansion that let a plain tablet
    reach a modified-release ceiling would reintroduce the Phase 0b bug.

    Two things prevent it, and this test pins both:

    1. NO ALIAS EXPANDS TO A MODIFIED FORM. Every value in the table is a bare
       dosage form. SR, ER and DT are release modifiers, not dosage forms, and
       are deliberately absent from the table.
    2. THE LOOKUP STAYS EXACT. "sinalate tab" produces the single key
       "sinalate tablet" and is matched against the index by equality, so it
       cannot reach "sinalate tablet sr" -- a different key entirely.
    """
    from app.pipeline.normalize import DOSAGE_FORM_ALIASES, brand_lookup_aliases

    modifiers = ("sr", "er", "xr", "dt", "cr", "la", "md", "sustained",
                 "extended", "dispersible", "modified")
    for abbrev, expansion in DOSAGE_FORM_ALIASES.items():
        assert not any(m in expansion.split() for m in modifiers), (
            f"{abbrev!r} expands to {expansion!r}, which carries a release "
            "modifier -- that is product identity, not a dosage form"
        )

    # A modifier present on the bill is CARRIED, never dropped: the key stays
    # distinct from the plain form, so the two can never collide.
    assert brand_lookup_aliases("glycomet tab sr") == ["glycomet tablet sr"]
    assert "glycomet tablet" not in brand_lookup_aliases("glycomet tab sr")


def test_expansion_never_rewrites_the_bills_own_text():
    """The printed string must survive into the report untouched.

    Expansion is a lookup alias. If it reached item.name, a flag would cite a
    string that is not on the patient's bill, and the evidence trail would
    quietly stop matching the page it came from.
    """
    from app.pipeline.normalize import normalize_item

    item = VerifiedItem(index=1, name="PANTOCID DSR CAP", quantity=Decimal("8"),
                        line_total=Decimal("134.48"),
                        confidence=ReadingConfidence.HIGH)
    normalize_item(item)
    assert item.name == "PANTOCID DSR CAP"


def test_absence_is_only_claimed_when_the_resolution_was_complete():
    """D1 applies to claims about ourselves.

    "No published ceiling exists for this item" is a claim about NPPA's
    COVERAGE. It may only be made when we know which item -- salt set, form
    AND strength. With a partial resolution, an empty search result proves
    only that we did not look precisely enough, and the honest label is
    could_not_identify.
    """
    from app.pipeline.audit import _resolution_is_complete

    complete = NormalizedItem(
        index=1, category=ItemCategory.DRUG, salt_components=["PANTOPRAZOLE"],
        strength_mg=[Decimal("40")], strength_kind="mg", dosage_form="tablet",
    )
    assert _resolution_is_complete(complete)

    # Salt only -- the combination or strength is unknown, so absence is not
    # proven. This is the case the third branch must NOT claim.
    assert not _resolution_is_complete(NormalizedItem(
        index=1, category=ItemCategory.DRUG, salt_components=["PANTOPRAZOLE"],
    ))
    # Form missing.
    assert not _resolution_is_complete(NormalizedItem(
        index=1, category=ItemCategory.DRUG, salt_components=["PANTOPRAZOLE"],
        strength_mg=[Decimal("40")], strength_kind="mg",
    ))
    # Nothing resolved at all.
    assert not _resolution_is_complete(NormalizedItem(index=1))


def test_a_partially_resolved_drug_is_still_could_not_identify():
    """End to end: partial resolution must never reach the absence claim."""
    from app.pipeline.audit import rule_r9_gray

    partial = NormalizedItem(
        index=1, category=ItemCategory.DRUG, salt_components=["SOMETHING"],
    )
    item = VerifiedItem(index=1, name="MYSTERY TAB", quantity=Decimal("1"),
                        line_total=Decimal("10"),
                        confidence=ReadingConfidence.HIGH)
    flag = rule_r9_gray(item, partial, ceiling_search_exhausted=True)
    assert flag.gray_reason is GrayReason.COULD_NOT_VERIFY
    assert flag.gray_detail is GrayDetail.COULD_NOT_IDENTIFY


def test_the_absence_wording_never_says_the_price_is_fine():
    """LIMIT 8. "Not price-controlled" is not "correct".

    This is the distinction a judge with a pharma background listens for, and
    the one a patient could most easily misread. The explanation must state
    the item is outside the published list WITHOUT implying its price has
    been approved.
    """
    from app.pipeline.audit import rule_r9_gray

    resolved = NormalizedItem(
        index=1, category=ItemCategory.DRUG,
        salt_components=["DOMPERIDONE", "PANTOPRAZOLE"],
        strength_mg=[Decimal("30"), Decimal("40")], strength_kind="mg",
        dosage_form="capsule",
    )
    item = VerifiedItem(index=1, name="PANTOCID DSR CAP", quantity=Decimal("8"),
                        line_total=Decimal("134.48"),
                        confidence=ReadingConfidence.HIGH)
    text = rule_r9_gray(item, resolved, ceiling_search_exhausted=True).explanation.lower()

    assert "not price-controlled" in text
    assert "not that its price is correct" in text
    for forbidden in ("within the ceiling", "price is fine", "correctly priced",
                      "no issue", "approved"):
        assert forbidden not in text, f"wording implies approval: {forbidden!r}"


def test_a_pack_count_can_never_become_the_ceiling_rows_unit_quantity():
    """THE 747 FENCE. `ceiling_row_unit_qty` is a property of the NPPA ROW.

    It is the "1" in "Rs 0.93 per 1 tablet" and the "500" in "Rs 66.50 per
    500 ml bag". A PACK COUNT is a different thing entirely, and passing one
    here searches for a ceiling priced per-ten-tablets, which does not exist:

        ceiling_row_unit_qty=1   -> FOUND 0.93
        ceiling_row_unit_qty=10  -> NO CEILING FOUND

    Found in the adversarial audit of 2026-09-19 as DEAD CODE that would
    activate the instant Class C read the PACK column, silently turning every
    packed tablet from green to gray -- the opposite of Class C's purpose.
    """
    from app.pipeline.audit import ceiling_row_unit_qty_for

    # A stated VOLUME is the ceiling row's unit quantity. Ringer Lactate's
    # row really is priced per 500 ml.
    volume = NormalizedItem(
        index=1, category=ItemCategory.DRUG, salt_components=["RINGER LACTATE"],
        unit_basis="ml", pack_count=Decimal("500"), pack_count_source="bill_text",
    )
    assert ceiling_row_unit_qty_for(volume) == Decimal("500")

    # A stated COUNT of discrete units is NOT. This is the Class C case: the
    # ceiling row is per 1 tablet however many came in the strip.
    count = NormalizedItem(
        index=1, category=ItemCategory.DRUG, salt_components=["PARACETAMOL"],
        unit_basis="tablet", pack_count=Decimal("15"), pack_count_source="bill_text",
    )
    assert ceiling_row_unit_qty_for(count) == Decimal("1"), (
        "a PACK COUNT reached ceiling_row_unit_qty; the ceiling lookup will "
        "find nothing and the item will silently go gray"
    )

    # Brand-index packs are never the row's unit quantity either.
    from_index = NormalizedItem(
        index=1, category=ItemCategory.DRUG, salt_components=["PARACETAMOL"],
        unit_basis="tablet", pack_count=Decimal("10"), pack_count_source="brand_index",
    )
    assert ceiling_row_unit_qty_for(from_index) == Decimal("1")


def test_d11_pack_evidence_may_narrow_a_claim_but_not_broaden_it():
    """D11, and the DIRECTION is the point.

    Suppression: a reading we hold evidence against cannot raise a flag. A
    compliant strip of 10 at Rs 1.00/tablet was flagged AMBER for Rs 0.00
    purely because the contradicted "one strip = one tablet" reading exceeded.

    Promotion is deliberately WITHHELD: dropping that reading could turn an
    amber into a red, which opens a new path to a false accusation. Narrowing
    is safe immediately; broadening waits for its own validation pass.
    """
    from app.models import ReadingStats, Reconciliation
    from app.pipeline.audit import audit

    def verdict(total, pack):
        it = VerifiedItem(index=1, name="Paracetamol 500mg Tablet",
                          quantity=Decimal("1"), line_total=Decimal(total),
                          confidence=ReadingConfidence.HIGH)
        nz = NormalizedItem(
            index=1, category=ItemCategory.DRUG, match_type=MatchType.EXACT,
            salt_components=["PARACETAMOL"], strength_mg=[Decimal("500")],
            strength_kind="mg", dosage_form="tablet", unit_basis="tablet",
            pack_count=Decimal(pack), pack_count_source="brand_index",
        )
        st = ReadingStats(total_items=1, auto_high=1, rescued_by_reread=0,
                          still_unverified=0,
                          reconciliation=Reconciliation.RECONCILED,
                          sum_of_line_totals=Decimal(total),
                          printed_grand_total=Decimal(total))
        return [f for f in audit([it], [nz], st) if f.rule_id == "R5"][0]

    # SUPPRESSION: 10 tablets at Rs 1.00 -- under the Rs 1.0416 allowance.
    compliant = verdict("10.00", "10")
    assert compliant.severity is Severity.GREEN, (
        "a compliant line was flagged because of a reading we have evidence "
        "against"
    )

    # NO PROMOTION, and the reason is structural rather than gated.
    # per_billed_unit divides by qty; per_pack_unit divides by qty*pack_count,
    # so with pack_count > 1 the DROPPED reading is always the HIGHER one.
    # Removing the largest element can only make `all(above_red)` stay the
    # same or become False -- never True. Suppression cannot manufacture a red.
    excessive = verdict("50.00", "10")
    assert excessive.severity is not Severity.RED, (
        "narrowing the interpretation set promoted a flag to red"
    )

    # And the 50x misread guard -- the one lever that COULD promote, because
    # it uses the highest per-unit reading -- still sees the full set.
    assert "ratio_" in " ".join(excessive.evidence.get("not_red_because", []))


def test_a_pdf_reaches_the_second_reader():
    """REGRESSION. PDFs silently got ONE reader until 2026-09-19.

    read_with_bedrock returned None before making any call, because the
    format map held images only. The two-reader cross-check -- the only thing
    that catches a CONFIDENT misread, and exactly what caught Textract
    reading a column header as line item 1 -- was absent on every PDF bill,
    while the product claimed it. Indian hospital bills arrive as PDFs
    constantly.

    Converse takes a PDF as a DOCUMENT block, not an image block. This test
    pins the routing without calling AWS.
    """
    from app.pipeline import readers_aws

    assert readers_aws.DOCUMENT_FORMATS.get("application/pdf") == "pdf"
    assert readers_aws.IMAGE_FORMATS.get("image/jpeg") == "jpeg"

    # The document name must be a CONSTANT, never the uploaded filename.
    # AWS documents this field as vulnerable to prompt injection, and the
    # filename is supplied by whoever uploads the bill.
    assert readers_aws.DOCUMENT_NAME == "bill"
    assert readers_aws.DOCUMENT_NAME.isalnum()


def test_a_single_reader_result_never_implies_a_cross_check():
    """The report must not claim agreement that never happened.

    "single_reader_high_confidence:97" alone reads like a strong result. It
    means the second opinion is missing and nothing was compared.
    """
    from app.pipeline.verify import verify_item

    only_a = ReaderItem(index=1, name="Paracetamol 500mg Tablet",
                        quantity=Decimal("10"), unit_price=Decimal("0.90"),
                        line_total=Decimal("9.00"), confidence=Decimal("99"))
    assert "only_one_reader_ran" in verify_item(only_a, None).reasons

    both = verify_item(only_a, only_a)
    assert "only_one_reader_ran" not in both.reasons
    assert any(r.startswith("both_readers_agree") for r in both.reasons)


def test_a_line_nobody_cross_checked_is_not_reported_as_misread():
    """A missing second reader is not a reading failure.

    Found 2026-09-20 on a real invoice that was read PERFECTLY -- all seven
    lines matched the paper -- and reported as "We could not read this line
    reliably" on six of them. The only thing wrong was Bedrock returning
    INVALID_PAYMENT_INSTRUMENT, so no second reader existed and a lone
    Textract reading below the 95 floor cannot promote itself.

    Blaming our own reading for a billing outage overstates our
    unreliability in the one place the product is asking to be trusted.
    The verdict is unchanged -- gray, unpriced -- only the sentence differs.
    """
    from app.models import GrayDetail
    from app.pipeline.audit import audit
    from app.pipeline.normalize import normalize_bill

    item = VerifiedItem(
        index=1, name="BENGAY GREASELESS 20Z", quantity=Decimal("2"),
        line_total=Decimal("28.60"), confidence=ReadingConfidence.UNVERIFIED,
        reasons=["only_one_reader_ran", "single_reader_low_confidence:88",
                 "arithmetic_not_checkable:missing_values"],
    )
    flags = audit([item], normalize_bill([item]), _stats())
    gray = [f for f in flags if f.gray_detail is not None]
    assert gray, "an unpriceable line must still report a gray detail"
    assert gray[0].gray_detail is GrayDetail.NOT_CROSS_CHECKED
    assert "not a sign" in gray[0].explanation.lower()


def test_a_genuinely_broken_reading_is_still_reported_as_misread():
    """The other direction: NOT_CROSS_CHECKED must not swallow real failures.

    Same missing second reader, but the arithmetic does not hold -- that IS
    evidence against our reading, and it must keep saying so.
    """
    from app.models import GrayDetail
    from app.pipeline.audit import audit
    from app.pipeline.normalize import normalize_bill

    item = VerifiedItem(
        index=1, name="Something", quantity=Decimal("2"),
        unit_price=Decimal("10.00"), line_total=Decimal("999.00"),
        confidence=ReadingConfidence.UNVERIFIED,
        reasons=["only_one_reader_ran", "arithmetic_does_not_hold"],
    )
    flags = audit([item], normalize_bill([item]), _stats())
    gray = [f for f in flags if f.gray_detail is not None]
    assert gray and gray[0].gray_detail is GrayDetail.COULD_NOT_READ


# --------------------------------------------------------------------------
# Textract response parsing. There were no tests over this shape at all, and
# a bug in it decided verdicts on real bills.
# --------------------------------------------------------------------------

def _expense_response(fields):
    """An AnalyzeExpense response with one line item carrying `fields`."""
    return {"ExpenseDocuments": [{
        "LineItemGroups": [{"LineItems": [{
            "LineItemExpenseFields": [
                {"Type": {"Text": k}, "ValueDetection": {"Text": t, "Confidence": c},
                 "PageNumber": 1}
                for k, t, c in fields
            ]}]}],
        "SummaryFields": [],
    }]}


def test_line_confidence_ignores_fields_we_never_read():
    """EXPENSE_ROW must not decide whether a price gets compared.

    AnalyzeExpense returns the whole row as one lower-confidence string
    alongside the cells. The line score is a MINIMUM, so that one field
    dragged every row under the 95 single-reader floor and the price was
    never compared -- a verdict decided by data we discard.

    Measured 2026-09-20: seven lines read correctly against the paper, six
    reported as unreadable.
    """
    from app.pipeline.readers_aws import _parse_expense

    resp = _expense_response([
        ("ITEM", "BENGAY GREASELESS 20Z", 99.4),
        ("QUANTITY", "2", 99.1),
        ("PRICE", "28.60", 99.7),
        ("EXPENSE_ROW", "BENGAY GREASELESS 20Z 2 28.60", 71.2),
    ])
    out = _parse_expense(resp)
    assert len(out.items) == 1
    assert out.items[0].confidence == Decimal("99.10"), (
        "the score must be the weakest field WE READ (QUANTITY 99.1), "
        "not the weakest field Textract happened to return"
    )


def test_line_confidence_still_falls_to_a_weak_field_we_do_read():
    """The narrowing half: a bad PRICE must still sink the line."""
    from app.pipeline.readers_aws import _parse_expense

    resp = _expense_response([
        ("ITEM", "Something", 99.4),
        ("PRICE", "28.60", 62.0),
        ("EXPENSE_ROW", "Something 28.60", 99.9),
    ])
    out = _parse_expense(resp)
    assert out.items[0].confidence == Decimal("62.00")


def test_r2_abstains_when_any_line_feeding_the_sum_is_untrusted():
    """A sum is only as sound as its weakest term -- EVERY term.

    Found 2026-09-20 by the user, on a real hospital bill that adds up
    perfectly: two group totals of 7,700.00 and 3,558.84 against a printed
    net of 11,258.84. Textract, reading a photographed page, dropped one
    2,400.00 line and shuffled others, so OUR sum came to 8,985.68 -- and the
    report asked the hospital to explain Rs 2,273.16 it had never charged.

    verify.py sums every line carrying a number, trusted or not, so R2 was
    reconciling a total built out of lines it had already refused to price.
    The rule existed for the narrow case of a line worth more than the whole
    bill; this is the same argument generalised.

    NARROWING ONLY: strictly fewer findings, so it cannot create a false red.
    """
    from app.models import ReadingStats
    from app.pipeline.audit import rule_r2_bill_total

    stats = ReadingStats(
        reconciliation=Reconciliation.MISMATCH,
        sum_of_line_totals=Decimal("8985.68"),
        printed_grand_total=Decimal("11258.84"),
    )
    # Trusted sum: the rule speaks.
    assert rule_r2_bill_total(stats, False) is not None
    # One line we could not read: it must not.
    assert rule_r2_bill_total(stats, True) is None


def test_r2_still_speaks_when_every_line_was_read_well():
    """The other direction, so the narrowing cannot silence R2 entirely."""
    from app.models import ReadingStats
    from app.pipeline.audit import audit
    from app.pipeline.normalize import normalize_bill

    items = [
        VerifiedItem(index=1, name="A", quantity=Decimal("1"),
                     unit_price=Decimal("100.00"), line_total=Decimal("100.00"),
                     confidence=ReadingConfidence.HIGH,
                     reasons=["both_readers_agree:name_similarity=100"]),
        VerifiedItem(index=2, name="B", quantity=Decimal("1"),
                     unit_price=Decimal("200.00"), line_total=Decimal("200.00"),
                     confidence=ReadingConfidence.HIGH,
                     reasons=["both_readers_agree:name_similarity=100"]),
    ]
    from app.models import ReadingStats
    stats = ReadingStats(
        total_items=2, auto_high=2,
        reconciliation=Reconciliation.MISMATCH,
        sum_of_line_totals=Decimal("300.00"),
        printed_grand_total=Decimal("900.00"),
    )
    flags = audit(items, normalize_bill(items), stats)
    r2 = [f for f in flags if f.rule_id == "R2"]
    assert r2, "a bill asking for more than well-read lines justify must fire R2"
    assert r2[0].amount_affected == Decimal("600.00")
