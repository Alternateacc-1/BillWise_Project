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


def test_missing_values_never_count_as_agreement():
    a = reader_item(unit_price=None, line_total=None)
    assert verify_item(a, a).confidence is ReadingConfidence.UNVERIFIED


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


def test_r1_tolerates_rounding_within_one_rupee():
    item = VerifiedItem(
        index=1, name="X", quantity=Decimal("3"), unit_price=Decimal("3.33"),
        line_total=Decimal("10.00"), confidence=ReadingConfidence.HIGH,
    )
    assert rule_r1_line_arithmetic(item) is None


def _drug(index=1, **kwargs) -> NormalizedItem:
    base = dict(
        index=index, category=ItemCategory.DRUG, match_type=MatchType.EXACT,
        salt_components=["PARACETAMOL"], strength_mg=[500.0], strength_kind="mg",
        dosage_form="tablet", unit_basis="tablet", form_modifier=None,
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
    excess = flag.evidence["interpretations"][0]["excess_over_ceiling_pct"]
    assert Decimal(excess) > 0


def test_r5_shows_the_full_arithmetic_and_excess_percentage():
    flag = rule_r5_above_ceiling(
        _item(line_total=Decimal("40.00")), _drug(), _ceiling()
    )
    evidence = flag.evidence
    for key in ("ceiling_ex_gst", "gst_percent", "gst_multiplier",
                "amber_threshold", "red_threshold", "arithmetic"):
        assert key in evidence, key
    assert "excess_over_ceiling_pct" in evidence["interpretations"][0]
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
        for number in re.findall(r"\d+(?:\.\d+)?", flag.explanation):
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
    assert "BillSahi report" in out
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
