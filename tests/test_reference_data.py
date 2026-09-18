"""Phase 0 acceptance tests for the NPPA reference data.

Every number asserted here was read out of data/raw/ by hand before the
parser existed. If a test fails, the parser is wrong -- do not adjust the
expected value to make it pass.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

import prepare_reference as pr


def find_one(rows, **criteria):
    """Return the single row matching every criterion, or fail loudly."""
    matches = [
        r for r in rows
        if all(getattr(r, k) == v for k, v in criteria.items())
    ]
    assert len(matches) == 1, (
        f"expected exactly 1 row for {criteria}, got {len(matches)}: "
        f"{[m.ref_id for m in matches]}"
    )
    return matches[0]


# --------------------------------------------------------------------------
# Row counts and the zero-dropped rule
# --------------------------------------------------------------------------

def test_ceiling_row_count(ceiling):
    assert len(ceiling) == 915


def test_special_feature_row_count(special):
    assert len(special) == 22


def test_retail_row_count(retail):
    assert len(retail) == 3881


def test_zero_dropped_from_ceiling_file(ceiling):
    """Hard rule: every one of the 915 ceiling rows parses.

    parse_ceiling_csv() raises SystemExit on any parse failure, so reaching
    the expected count here proves nothing was silently skipped.
    """
    assert len(ceiling) == pr.EXPECTED_CEILING_ROWS
    assert all(r.price_ex_gst for r in ceiling)
    assert all(r.unit_basis_raw for r in ceiling)


def test_every_ceiling_row_has_a_price_and_unit(ceiling):
    for r in ceiling:
        assert r.price_ex_gst != "", f"{r.ref_id} has no price"
        assert Decimal(r.price_ex_gst) > 0, f"{r.ref_id} has a non-positive price"
        assert r.unit_basis in pr.UNIT_BASIS_ENUM, f"{r.ref_id} unit {r.unit_basis!r}"
        assert Decimal(r.unit_qty) > 0, f"{r.ref_id} has a non-positive unit_qty"


def test_no_usable_row_anywhere_has_a_null_price_or_unit(rows):
    """The zero-null rule, scoped to usable rows.

    Quarantined rows deliberately CAN have an empty price -- that is what
    quarantine means. The invariant is that nothing usable is missing either.
    """
    for r in rows:
        if r.status != pr.STATUS_USABLE:
            continue
        assert r.price_ex_gst != "", f"{r.ref_id} usable but has no price"
        assert r.unit_basis, f"{r.ref_id} usable but has no unit basis"
        assert Decimal(r.unit_qty) > 0, f"{r.ref_id} usable but unit_qty <= 0"


# --------------------------------------------------------------------------
# The specific reference values
# --------------------------------------------------------------------------

def test_drug_eluting_stents(ceiling):
    row = find_one(ceiling, ref_id="CEIL-0049")
    assert row.formulation_raw.startswith("Drug Eluting Stents")
    assert row.price_ex_gst == "39186.03"
    assert row.unit_basis == "unit"
    assert row.so_number == "1587(E)"


def test_bare_metal_stents(ceiling):
    row = find_one(ceiling, formulation_raw="Bare Metal Stents")
    assert row.price_ex_gst == "10762.15"
    assert row.unit_basis == "unit"
    assert row.so_number == "1587(E)"


def test_amoxicillin_clavulanic_acid_tablet(ceiling):
    row = find_one(
        ceiling,
        formulation_raw="AMOXICILLIN (A) + CLAVULANIC ACID (B)",
    )
    assert row.salt_components == ["AMOXICILLIN", "CLAVULANIC ACID"]
    assert row.dosage_form == "tablet"
    assert sorted(row.strength_mg) == [125.0, 500.0]
    assert row.price_ex_gst == "18.74"
    assert row.unit_basis == "tablet"
    assert row.unit_qty == "1"


@pytest.mark.parametrize(
    "strength_raw, expected_price",
    [("TABLET 500 MG", "0.93"), ("TABLET 650 MG", "2.05")],
)
def test_paracetamol_tablets(ceiling, strength_raw, expected_price):
    row = find_one(ceiling, formulation_raw="PARACETAMOL", strength_raw=strength_raw)
    assert row.price_ex_gst == expected_price
    assert row.unit_basis == "tablet"
    assert row.unit_qty == "1"


def test_ringer_lactate_ordinary_and_special_feature_both_exist(rows):
    """Special-feature rows are ADDITIONAL, not replacements."""
    ordinary = find_one(
        rows, source="ceiling", formulation_raw="Ringer Lactate",
        strength_raw="Injection 500 ml",
    )
    special = find_one(
        rows, source="special_feature", formulation_raw="Ringer Lactate",
        strength_raw="Injection 500 ml",
    )
    assert ordinary.price_ex_gst == "57.85"
    assert special.price_ex_gst == "66.52"
    # Both must resolve to the same basis or they cannot be compared at all.
    assert ordinary.unit_basis == special.unit_basis == "ml"
    assert ordinary.unit_qty == special.unit_qty == "500"


def test_ringer_lactate_selection_returns_the_higher_ceiling(rows):
    """A legitimate special-feature pack must never be flagged."""
    chosen = pr.select_highest_applicable_ceiling(
        rows,
        salt_components=["RINGER LACTATE"],
        dosage_form="injection",
        strength_mg=[],
        strength_kind="none",
        unit_basis="ml",
        unit_qty=Decimal("500"),
    )
    assert chosen is not None
    assert chosen.source == "special_feature"
    assert chosen.price_ex_gst == "66.52"
    assert chosen.so_number == "1584(E)"


def test_ringer_lactate_does_not_match_another_pack_size(rows):
    """Small Ringer packs are dearer per ml -- selection must not reach them.

    100 ml at 30.62 is 0.3062/ml; 500 ml at 66.52 is 0.1330/ml. If pack size
    were not part of the match, a 500 ml bag would be measured against the
    100 ml ceiling and a price 2.3x the real cap would pass as compliant.
    """
    for qty, expected in [
        (Decimal("100"), "30.62"),
        (Decimal("250"), "52.22"),
        (Decimal("500"), "66.52"),
        (Decimal("1000"), "116.95"),
    ]:
        chosen = pr.select_highest_applicable_ceiling(
            rows,
            salt_components=["RINGER LACTATE"],
            dosage_form="injection",
            strength_mg=[],
            strength_kind="none",
            unit_basis="ml",
            unit_qty=qty,
        )
        assert chosen is not None, f"no ceiling for {qty} ml"
        assert chosen.unit_qty == str(qty)
        assert chosen.price_ex_gst == expected


# --------------------------------------------------------------------------
# Named regression: the Meropenem strength inversion
# --------------------------------------------------------------------------

def test_meropenem_strength_inversion(rows):
    """The 500 mg vial costs MORE than the 1000 mg vial in the source data.

    Special-feature rows: 1000 MG = 851.43, 500 MG = 1121.96. If ceiling
    selection ever matched strength fuzzily, a 1000 mg item would inherit the
    500 mg row's higher ceiling and every verdict about it would be wrong.

    This asserts the inversion is real (so nobody "fixes" the data) and that
    selection is strength-exact (so the inversion cannot leak).
    """
    spec_1000 = find_one(
        rows, source="special_feature", formulation_raw="MEROPENEM",
        strength_raw="INJECTION 1000 MG",
    )
    spec_500 = find_one(
        rows, source="special_feature", formulation_raw="MEROPENEM",
        strength_raw="INJECTION 500 MG",
    )
    # The inversion is in the source. Documented, not corrected.
    assert Decimal(spec_500.price_ex_gst) > Decimal(spec_1000.price_ex_gst)

    # Selection for 1000 mg must return the 1000 mg ceiling, never 1121.96.
    chosen = pr.select_highest_applicable_ceiling(
        rows,
        salt_components=["MEROPENEM"],
        dosage_form="injection",
        strength_mg=[1000.0],
        strength_kind="mg",
        unit_basis="vial",
        unit_qty=Decimal("1"),
    )
    assert chosen is not None
    assert chosen.strength_raw == "INJECTION 1000 MG"
    assert chosen.price_ex_gst == "975.62"
    assert chosen.price_ex_gst != spec_500.price_ex_gst

    # ...and 500 mg must return the 500 mg ceiling, not the 1000 mg one.
    chosen_500 = pr.select_highest_applicable_ceiling(
        rows,
        salt_components=["MEROPENEM"],
        dosage_form="injection",
        strength_mg=[500.0],
        strength_kind="mg",
        unit_basis="vial",
        unit_qty=Decimal("1"),
    )
    assert chosen_500 is not None
    assert chosen_500.strength_raw == "INJECTION 500 MG"
    assert chosen_500.price_ex_gst == "740.37"


def test_selection_never_returns_a_retail_row(rows):
    """Retail prices bind one company. They can never act as a ceiling."""
    for r in rows:
        if r.source != "retail_new_drug" or r.status != pr.STATUS_USABLE:
            continue
        chosen = pr.select_highest_applicable_ceiling(
            rows,
            salt_components=r.salt_components,
            dosage_form=r.dosage_form,
            strength_mg=r.strength_mg,
            strength_kind=r.strength_kind,
            unit_basis=r.unit_basis,
            unit_qty=Decimal(r.unit_qty),
        )
        assert chosen is None or chosen.source != "retail_new_drug"


def test_selection_returns_none_for_an_unknown_salt(rows):
    assert pr.select_highest_applicable_ceiling(
        rows,
        salt_components=["NOT A REAL SALT"],
        dosage_form="tablet",
        strength_mg=[500.0],
        strength_kind="mg",
        unit_basis="tablet",
        unit_qty=Decimal("1"),
    ) is None


def test_retail_pack_size_is_never_read_from_composition_text(retail):
    """Regression: a drug strength is not a container size.

    RETL-0434's composition reads "Gemcitabine 1.4gm" and its unit cell says
    only "Each Pack". Reading the pack size out of that text priced the row
    per 1.4 gm of container, which is meaningless. Retail rows whose unit
    cell states no basis must stay `pack` and stay out of price checks.
    """
    row = find_one(retail, ref_id="RETL-0434")
    assert row.unit_basis == "pack"
    assert row.unit_qty == "1"
    assert row.price_checkable == "false"


def test_ceiling_pack_size_is_still_recovered_where_it_is_structured(ceiling):
    """The counterpart: the ceiling file's strength column IS safe to read."""
    row = find_one(ceiling, ref_id="CEIL-0116")
    assert row.unit_basis_raw == "Each Pack"
    assert row.strength_raw == "Injection 500 ml"
    assert (row.unit_basis, row.unit_qty) == ("ml", "500")
    assert row.price_checkable == "true"


# --------------------------------------------------------------------------
# Release / presentation modifiers
# --------------------------------------------------------------------------

def test_dispersible_tablet_is_not_a_plain_tablet(ceiling):
    """Regression: ASPIRIN "TABLET DT 75 MG" vs "Tablet 75 mg".

    Both are 75 mg aspirin tablets and both were collapsing into one group,
    which made synonym expansion look unsafe. They are genuinely different
    products with different ceilings under different S.O.s -- DT is a
    dispersible tablet. The fix is to treat the release modifier as part of
    product identity, not to weaken the synonym table.
    """
    plain = find_one(ceiling, ref_id="CEIL-0009")
    dispersible = find_one(ceiling, ref_id="CEIL-0214")

    assert plain.dosage_form == dispersible.dosage_form == "tablet"
    assert plain.form_modifier == ""
    assert dispersible.form_modifier == "dispersible"
    assert plain.price_ex_gst == "0.39"
    assert dispersible.price_ex_gst == "0.36"
    assert plain.so_number != dispersible.so_number


def test_selection_will_not_cross_a_form_modifier(rows):
    """A plain tablet must never be measured against a dispersible ceiling."""
    plain = pr.select_highest_applicable_ceiling(
        rows, salt_components=["ACETYLSALICYLIC ACID"], dosage_form="tablet",
        strength_mg=[75.0], strength_kind="mg", unit_basis="tablet",
        unit_qty=Decimal("1"), form_modifier="",
    )
    assert plain is not None
    assert plain.ref_id == "CEIL-0009"

    dispersible = pr.select_highest_applicable_ceiling(
        rows, salt_components=["ASPIRIN"], dosage_form="tablet",
        strength_mg=[75.0], strength_kind="mg", unit_basis="tablet",
        unit_qty=Decimal("1"), form_modifier="dispersible",
    )
    assert dispersible is not None
    assert dispersible.ref_id == "CEIL-0214"


def test_multi_modifier_rows_keep_every_modifier(ceiling):
    """"Effervescent/ Dispersible/ Enteric coated Tablet" is its own category."""
    row = find_one(ceiling, ref_id="CEIL-0012")
    assert row.dosage_form == "tablet"
    assert row.form_modifier == "dispersible|effervescent|enteric"


@pytest.mark.parametrize(
    "strength, expected",
    [
        ("Tablet 500 mg", ""),
        ("TABLET DT 75 MG", "dispersible"),
        ("Dispersible Tablet 100 mg", "dispersible"),
        ("Tablet Modified Release 50 mg", "modified_release"),
        ("Chewable Tablet 200 mg", "chewable"),
        ("Enteric coated Tablet 75 mg", "enteric"),
        ("Injection 500 mg", ""),
    ],
)
def test_form_modifier_detection(strength, expected):
    assert pr.detect_form_modifiers(strength) == expected


# --------------------------------------------------------------------------
# Synonym safety
# --------------------------------------------------------------------------

def test_synonym_expansion_creates_no_price_conflicts(rows):
    """The guardrail: synonym expansion must never merge differing prices.

    Zero conflicts today. If NPPA ever publishes a paracetamol ceiling and a
    differing acetaminophen ceiling, this fails loudly rather than letting
    the matcher pick one arbitrarily.
    """
    conflicts = pr.find_synonym_price_conflicts(rows)
    assert conflicts == [], (
        f"{len(conflicts)} synonym price conflict(s); the synonym tier is "
        f"unsafe until these are resolved: {conflicts}"
    )


def test_reference_rows_keep_their_original_spelling(ceiling):
    """Synonyms expand the QUERY. They never rewrite a reference row.

    Both spellings must still be present in the reference data exactly as
    NPPA published them.
    """
    spellings = {r.formulation_raw.upper() for r in ceiling}
    assert "ASPIRIN" in spellings
    assert "ACETYLSALICYLIC ACID" in spellings
    assert any("AMOXICILLIN" in s for s in spellings)
    assert any("AMOXYCILLIN" in s for s in spellings)


# --------------------------------------------------------------------------
# Quarantine behaviour
# --------------------------------------------------------------------------

def test_withdrawn_retail_prices_get_their_own_reason_code(retail):
    withdrawn = [r for r in retail if r.quarantine_reason == pr.REASON_PRICE_WITHDRAWN]
    assert len(withdrawn) == 2
    for r in withdrawn:
        assert r.status == pr.STATUS_QUARANTINED
        assert "WITHDRAWAL" in r.raw_row.upper()
        assert r.price_ex_gst == ""


def test_retail_unmappable_units_stay_usable_but_not_price_checkable(retail):
    """An unreadable unit costs a retail row its numbers, not its existence.

    "Injection" and "Gel" say nothing about what one unit is, but the price,
    salt set and manufacturer are all sound and still serve as R7 context.
    price_checkable=false already blocks any numeric comparison, so
    quarantining as well would discard good evidence for no safety gain.
    """
    # Two exclusions, both deliberate:
    #  - an EMPTY unit cell also normalises to `other`, but that is the
    #    separate unit_missing fault and stays quarantined;
    #  - a row can have BOTH an unmappable unit and a bad price (RETL-0225,
    #    unit "Gel", price unparseable). The price fault quarantines it, and
    #    rightly so.
    # What is being asserted is that an unmappable unit ALONE never does.
    unmappable = [
        r for r in retail
        if r.unit_basis == "other"
        and r.unit_basis_raw
        and r.quarantine_reason != pr.REASON_PRICE_UNPARSEABLE
        and r.quarantine_reason != pr.REASON_PRICE_WITHDRAWN
    ]
    assert len(unmappable) > 100, "expected the unmappable-unit tail to be large"
    for r in unmappable:
        assert r.status == pr.STATUS_USABLE, f"{r.ref_id} should not be quarantined"
        assert r.price_checkable == "false", f"{r.ref_id} must not be comparable"
        assert r.price_ex_gst != ""


def test_retail_quarantine_reasons_are_only_the_three_data_faults(retail):
    """unit_unmappable must never quarantine a retail row."""
    reasons = {r.quarantine_reason for r in retail if r.status == pr.STATUS_QUARANTINED}
    assert reasons <= {
        pr.REASON_PRICE_UNPARSEABLE,
        pr.REASON_PRICE_WITHDRAWN,
        pr.REASON_UNIT_MISSING,
    }
    assert pr.REASON_UNIT_UNMAPPABLE not in reasons


def test_quarantined_rows_carry_a_known_reason(rows):
    known = {
        pr.REASON_PRICE_WITHDRAWN,
        pr.REASON_PRICE_UNPARSEABLE,
        pr.REASON_UNIT_MISSING,
        pr.REASON_UNIT_UNMAPPABLE,
    }
    for r in rows:
        if r.status == pr.STATUS_QUARANTINED:
            assert r.quarantine_reason in known, f"{r.ref_id}: {r.quarantine_reason!r}"
        else:
            assert r.quarantine_reason == ""


def test_ceiling_quarantines_are_only_the_ambiguous_unit_rows(ceiling):
    """The 4 ceiling quarantines are deliberate, not parser misses.

    Each is a unit string that genuinely does not say what one unit is.
    Locked down so that a parser regression cannot quietly add a fifth.
    """
    q = sorted(r.ref_id for r in ceiling if r.status == pr.STATUS_QUARANTINED)
    assert q == ["CEIL-0138", "CEIL-0593", "CEIL-0721", "CEIL-0833"]
    for r in ceiling:
        if r.status == pr.STATUS_QUARANTINED:
            assert r.quarantine_reason == pr.REASON_UNIT_UNMAPPABLE


def test_no_special_feature_row_is_quarantined(special):
    assert [r.ref_id for r in special if r.status == pr.STATUS_QUARANTINED] == []


# --------------------------------------------------------------------------
# Unit basis invariants
# --------------------------------------------------------------------------

def test_every_unit_lands_in_the_enum(rows):
    for r in rows:
        assert r.unit_basis in pr.UNIT_BASIS_ENUM, f"{r.ref_id}: {r.unit_basis!r}"


def test_other_and_pack_are_never_price_checkable(rows):
    for r in rows:
        if r.unit_basis in pr.UNIT_BASIS_NOT_PRICE_CHECKABLE:
            assert r.price_checkable == "false", (
                f"{r.ref_id} has basis {r.unit_basis!r} but is marked checkable"
            )


def test_selection_never_returns_a_non_checkable_row(rows):
    """`other` and `pack` rows must be unreachable through selection."""
    for r in rows:
        if r.price_checkable == "true":
            continue
        chosen = pr.select_highest_applicable_ceiling(
            rows,
            salt_components=r.salt_components,
            dosage_form=r.dosage_form,
            strength_mg=r.strength_mg,
            strength_kind=r.strength_kind,
            unit_basis=r.unit_basis,
            unit_qty=Decimal(r.unit_qty),
        )
        assert chosen is None or chosen.price_checkable == "true"


@pytest.mark.parametrize(
    "raw, expected_basis, expected_qty",
    [
        ("1 Tablet", "tablet", "1"),
        ("1 Tablet)( Pack", "tablet", "1"),
        ("Each Vial", "vial", "1"),
        ("Each Vial)( Pack", "vial", "1"),
        ("Each Pack (5 ml)", "ml", "5"),
        ("Each Pack (0.5ml)", "ml", "0.5"),
        ("Per Metered Dose", "dose", "1"),
        ("250ml Non-Glass", "ml", "250"),
        ("2 ML Pack", "ml", "2"),
        ("Cubic Meter", "cubic_meter", "1"),
        ("Combi Pack", "pack", "1"),
        ("1 Condom", "unit", "1"),
        ("28's Tablet", "tablet", "28"),
        ("1 gm or 1 ml", "other", "1"),
        ("Per mg of Phospholipids in the pack", "other", "1"),
        ("", "other", "1"),
    ],
)
def test_unit_basis_normalisation(raw, expected_basis, expected_qty):
    basis, qty = pr.normalise_unit_basis(raw)
    assert basis == expected_basis
    assert str(qty) == expected_qty


# --------------------------------------------------------------------------
# Salt and strength parsing
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "formulation, expected",
    [
        ("Abacavir (A)+Lamivudine (B)", ["ABACAVIR", "LAMIVUDINE"]),
        ("AMOXYCILLIN + CLAVULANIC ACID", ["AMOXYCILLIN", "CLAVULANIC ACID"]),
        ("AMOXICILLIN (A) + CLAVULANIC ACID (B)", ["AMOXICILLIN", "CLAVULANIC ACID"]),
        ("Paracetamol", ["PARACETAMOL"]),
        # Multi-letter parentheticals are NOT combination markers.
        (
            "Drug Eluting Stents (DES) including metallic DES",
            ["DRUG ELUTING STENTS (DES) INCLUDING METALLIC DES"],
        ),
    ],
)
def test_salt_splitting(formulation, expected):
    assert pr.split_salt_components(formulation) == expected


@pytest.mark.parametrize(
    "strength, expected_mg, expected_kind",
    [
        ("Tablet 300 mg", [300.0], "mg"),
        ("TABLET 500 MG (A) +125 MG(B)", [500.0, 125.0], "mg"),
        ("Injection 300 mcg", [0.3], "mg"),
        ("ORAL LIQUID 250 MG/ 5 ML", [250.0], "concentration"),
        ("Cream 2.50%", [], "percent"),
        ("DEVICE --", [], "none"),
        ("", [], "none"),
    ],
)
def test_strength_parsing(strength, expected_mg, expected_kind):
    values, kind = pr.parse_strength(strength)
    assert values == expected_mg
    assert kind == expected_kind


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

def test_every_row_carries_provenance(rows):
    """Every flag must be traceable back to a source row."""
    for r in rows:
        assert r.retrieved_on == pr.RETRIEVED_ON
        assert r.raw_row, f"{r.ref_id} has no raw_row"
        assert r.ref_id and r.source


def test_ceiling_rows_all_have_an_so_number_and_date(ceiling):
    """Red flags cite the SO number and date, so they must always be present."""
    for r in ceiling:
        assert r.so_number, f"{r.ref_id} has no SO number"
        assert r.so_date, f"{r.ref_id} has no SO date"


def test_output_is_deterministic(rows, tmp_path, monkeypatch):
    """Identical input must produce a byte-identical file."""
    first = tmp_path / "a"
    second = tmp_path / "b"
    for target in (first, second):
        target.mkdir()
        monkeypatch.setattr(pr, "REF_DIR", target)
        monkeypatch.setattr(pr, "OUT_CSV", target / "reference_prices.csv")
        monkeypatch.setattr(pr, "OUT_QUARANTINE", target / "quarantine_log.csv")
        monkeypatch.setattr(pr, "OUT_COVERAGE", target / "unit_coverage.json")
        pr.write_outputs(rows)
    assert (first / "reference_prices.csv").read_bytes() == (
        second / "reference_prices.csv"
    ).read_bytes()
