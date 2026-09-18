"""Phase 0b acceptance tests for the brand index."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

import build_brand_index as bbi
import prepare_reference as pr
from app.pipeline import salt_synonyms as ss

REPO_ROOT = Path(__file__).resolve().parent.parent
BRAND_INDEX = REPO_ROOT / "data" / "reference" / "brand_index.csv"

pytestmark = pytest.mark.skipif(
    not BRAND_INDEX.exists(),
    reason="brand_index.csv not built; run fetch_brand_data.py then build_brand_index.py",
)


@pytest.fixture(scope="module")
def index() -> dict[str, dict[str, str]]:
    with BRAND_INDEX.open(encoding="utf-8") as fh:
        return {r["brand_name_norm"]: r for r in csv.DictReader(fh)}


def lookup(index, brand_name: str) -> dict[str, str]:
    row = index.get(ss.normalise_spelling(brand_name))
    assert row is not None, f"{brand_name!r} not found in the brand index"
    return row


# --------------------------------------------------------------------------
# The headline acceptance case
# --------------------------------------------------------------------------

def test_augmentin_resolves_to_salts_strength_and_pack(index):
    row = lookup(index, "Augmentin 625 Duo Tablet")
    assert json.loads(row["salt_components"]) == ["AMOXYCILLIN", "CLAVULANIC ACID"]
    assert sorted(json.loads(row["strength_mg"])) == [125.0, 500.0]
    assert row["strength_kind"] == "mg"
    assert row["dosage_form"] == "tablet"
    assert row["pack_count"] == "10"
    assert row["pack_unit"] == "tablet"
    assert row["ambiguous"] == "false"


def test_augmentin_matches_the_ceiling_row_at_18_74(index, rows):
    """The full bridge: brand name -> salts -> ceiling.

    Goes through the SYNONYM tier: the brand file spells it AMOXYCILLIN and
    the tablet ceiling row spells it AMOXICILLIN. Tier 1 finds AMOXYCILLIN
    rows, but none of them is a 500+125 mg tablet, so tier 2 runs.
    """
    row = lookup(index, "Augmentin 625 Duo Tablet")
    chosen, tier = pr.select_ceiling_two_tier(
        rows,
        salt_components=json.loads(row["salt_components"]),
        dosage_form=row["dosage_form"],
        strength_mg=json.loads(row["strength_mg"]),
        strength_kind=row["strength_kind"],
        unit_basis="tablet",
        unit_qty=Decimal("1"),
        form_modifier=row["form_modifier"],
    )
    assert chosen is not None
    assert tier == "synonym"
    assert chosen.ref_id == "CEIL-0189"
    assert chosen.price_ex_gst == "18.74"
    assert chosen.so_number == "1575(E)"


def test_tier1_still_wins_when_an_exact_spelling_row_exists(rows):
    """The guardrail survives the full-match gate.

    PARACETAMOL TABLET 500 MG exists spelled exactly, so tier 1 must win and
    the synonym tier must never be consulted.
    """
    chosen, tier = pr.select_ceiling_two_tier(
        rows,
        salt_components=["PARACETAMOL"],
        dosage_form="tablet",
        strength_mg=[500.0],
        strength_kind="mg",
        unit_basis="tablet",
        unit_qty=Decimal("1"),
    )
    assert tier == "exact"
    assert chosen.price_ex_gst == "0.93"


def test_unknown_brand_returns_none_rather_than_guessing(rows):
    chosen, tier = pr.select_ceiling_two_tier(
        rows,
        salt_components=["NOT A REAL SALT"],
        dosage_form="tablet",
        strength_mg=[500.0],
        strength_kind="mg",
        unit_basis="tablet",
        unit_qty=Decimal("1"),
    )
    assert chosen is None
    assert tier == "none"


# --------------------------------------------------------------------------
# No brand-file field may ever reach a verdict
# --------------------------------------------------------------------------

def test_brand_index_has_no_price_column():
    """The hard rule. Brand-file prices are scraped, undated and stale."""
    with BRAND_INDEX.open(encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    lowered = [c.lower() for c in header]
    for column in lowered:
        assert "price" not in column, f"brand index must not carry {column!r}"
        assert "mrp" not in column, f"brand index must not carry {column!r}"
    assert set(header) == set(bbi.CSV_COLUMNS)


def test_forbidden_source_columns_are_dropped():
    for column in bbi.FORBIDDEN_SOURCE_COLUMNS:
        assert column not in bbi.CSV_COLUMNS


def test_reference_prices_never_originate_in_the_brand_file(rows):
    """Every price that can produce a verdict traces to an NPPA source."""
    for r in rows:
        assert r.source in ("ceiling", "special_feature", "retail_new_drug")
        assert r.retrieved_on == pr.RETRIEVED_ON


def test_a_verdict_price_can_only_come_from_a_ceiling_source(rows, index):
    """Selection returns NPPA rows only, whatever the brand index said."""
    row = lookup(index, "Augmentin 625 Duo Tablet")
    chosen, _ = pr.select_ceiling_two_tier(
        rows,
        salt_components=json.loads(row["salt_components"]),
        dosage_form=row["dosage_form"],
        strength_mg=json.loads(row["strength_mg"]),
        strength_kind=row["strength_kind"],
        unit_basis="tablet",
        unit_qty=Decimal("1"),
        form_modifier=row["form_modifier"],
    )
    assert chosen.source in ("ceiling", "special_feature")
    assert chosen.raw_row.startswith("[")  # provenance is the NPPA CSV row


# --------------------------------------------------------------------------
# Pack size label parsing
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "label, count, unit",
    [
        # strip forms
        ("strip of 10 tablets", "10", "tablet"),
        ("strip of 15 tablets", "15", "tablet"),
        ("strip of 1 Tablet", "1", "tablet"),
        ("strip of 10 capsules", "10", "capsule"),
        ("strip of 10 tablet sr", "10", "tablet"),
        ("strip of 10 tablet dt", "10", "tablet"),
        # bottle forms
        ("bottle of 100 ml Syrup", "100", "ml"),
        ("bottle of 30 ml Dry Syrup", "30", "ml"),
        ("bottle of 5 ml Eye Drop", "5", "ml"),
        ("bottle of 60 ml Oral Suspension", "60", "ml"),
        # vial forms -- an explicit unit token beats the container default
        ("vial of 1 Injection", "1", "vial"),
        ("vial of 2 ml Injection", "2", "ml"),
        ("vial of 1 Powder for Injection", "1", "vial"),
        # tube forms
        ("tube of 15 gm Cream", "15", "gm"),
        ("tube of 10 gm Ointment", "10", "gm"),
        # unparseable -> NULL, never a guess
        ("", "", ""),
        ("as directed", "", ""),
        ("packet", "", ""),
    ],
)
def test_pack_size_parsing(label, count, unit):
    assert bbi.parse_pack_size(label) == (count, unit)


def test_unparseable_pack_size_leaves_pack_count_null():
    """A null pack count forces gray downstream. That is correct."""
    count, unit = bbi.parse_pack_size("something we cannot read")
    assert count == ""
    assert unit == ""


def test_pack_count_is_null_or_a_positive_number(index):
    for row in index.values():
        if row["pack_count"]:
            assert Decimal(row["pack_count"]) > 0, row["brand_name_norm"]


# --------------------------------------------------------------------------
# Composition parsing
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, salt, strength",
    [
        ("Amoxycillin  (500mg) ", "AMOXYCILLIN", "500mg"),
        ("Clavulanic Acid (125mg)", "CLAVULANIC ACID", "125mg"),
        ("Ambroxol (30mg/5ml)", "AMBROXOL", "30mg/5ml"),
        ("Azithromycin (500mg)", "AZITHROMYCIN", "500mg"),
        ("", "", ""),
    ],
)
def test_composition_parsing(text, salt, strength):
    assert bbi.parse_composition(text) == (salt, strength)


def test_composition_without_a_strength_does_not_invent_one():
    salt, strength = bbi.parse_composition("Paracetamol")
    assert salt == "PARACETAMOL"
    assert strength == ""


# --------------------------------------------------------------------------
# Deduplication, discontinued and ambiguity
# --------------------------------------------------------------------------

def test_names_are_unique_after_deduplication(index):
    with BRAND_INDEX.open(encoding="utf-8") as fh:
        names = [r["brand_name_norm"] for r in csv.DictReader(fh)]
    assert len(names) == len(set(names))


def test_discontinued_brands_are_kept_and_flagged(index):
    discontinued = [r for r in index.values() if r["is_discontinued"] == "true"]
    assert len(discontinued) > 1000, "discontinued brands must not be dropped"
    for r in discontinued[:50]:
        assert json.loads(r["salt_components"]), "a kept row still needs its salts"


def test_ambiguous_names_are_flagged_not_resolved(index):
    ambiguous = [r for r in index.values() if r["ambiguous"] == "true"]
    assert ambiguous, "expected some names to map to several salt sets"
    for r in ambiguous:
        assert int(r["variant_count"]) > 1


def test_every_indexed_row_has_salts(index):
    for row in index.values():
        assert json.loads(row["salt_components"]), row["brand_name_norm"]
