"""Phase 0b: salt-name canonicalisation and two-tier matching."""

from __future__ import annotations

import pytest

import salt_synonyms as ss


# --------------------------------------------------------------------------
# Every synonym pair, both directions
# --------------------------------------------------------------------------

#: The pairs the brief names as mandatory. Asserted explicitly so that
#: deleting one from the JSON fails the build rather than silently losing
#: coverage.
REQUIRED_PAIRS = [
    ("amoxycillin", "amoxicillin"),
    ("cetrizine", "cetirizine"),
    ("acetylsalicylic acid", "aspirin"),
    ("paracetamol", "acetaminophen"),
    ("salbutamol", "albuterol"),
    ("adrenaline", "epinephrine"),
    ("noradrenaline", "norepinephrine"),
    ("frusemide", "furosemide"),
    ("lignocaine", "lidocaine"),
    ("thiopentone", "thiopental"),
]


@pytest.mark.parametrize("left, right", REQUIRED_PAIRS)
def test_required_synonym_pairs_canonicalise_together(left, right):
    assert ss.canonicalise_salt(left) == ss.canonicalise_salt(right)


@pytest.mark.parametrize("left, right", REQUIRED_PAIRS)
def test_required_synonym_pairs_are_case_and_space_insensitive(left, right):
    assert ss.canonicalise_salt(left.upper()) == ss.canonicalise_salt(right.title())
    assert ss.canonicalise_salt(f"  {left}  ") == ss.canonicalise_salt(right)


def test_every_pair_in_the_table_is_symmetric():
    """Whatever is in the JSON, both spellings must land on one canonical."""
    for variant, canonical in ss.all_synonym_pairs():
        assert ss.canonicalise_salt(variant) == ss.canonicalise_salt(canonical), (
            f"{variant!r} and {canonical!r} do not canonicalise together"
        )


def test_the_table_is_unambiguous():
    """A variant claimed by two canonicals raises rather than picking one."""
    ss._variant_to_canonical.cache_clear()
    ss._variant_to_canonical()  # must not raise


def test_unrelated_drugs_never_canonicalise_together():
    """The rules must not over-merge. These are all genuinely different."""
    distinct = [
        "paracetamol", "ibuprofen", "amoxicillin", "azithromycin",
        "metformin", "atorvastatin", "omeprazole", "phenytoin",
        "morphine", "amlodipine", "ceftriaxone", "meropenem",
    ]
    canonical = [ss.canonicalise_salt(d) for d in distinct]
    assert len(set(canonical)) == len(distinct)


# --------------------------------------------------------------------------
# Orthographic rules -- safe because applied to BOTH sides
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "left, right",
    [
        ("sulphamethoxazole", "sulfamethoxazole"),
        ("magnesium sulphate", "magnesium sulfate"),
        ("sulphadoxine", "sulfadoxine"),
        ("oestradiol", "estradiol"),
    ],
)
def test_orthographic_rules_normalise_both_spellings(left, right):
    assert ss.normalise_spelling(left) == ss.normalise_spelling(right)


def test_oe_rule_is_word_initial_only():
    """A blanket oe->e would turn Coenzyme Q10 into 'cenzyme q10'.

    Coenzyme Q10 is a real product in the brand dataset, so this is not
    hypothetical.
    """
    assert "coenzyme" in ss.normalise_spelling("Coenzyme Q10")
    assert ss.normalise_spelling("oestradiol") == "estradiol"


def test_ph_is_never_rewritten_to_f():
    """A blanket ph->f would wreck phenytoin, morphine and phosphate."""
    for name in ["phenytoin", "morphine", "sodium phosphate", "phenobarbital"]:
        assert "ph" in ss.normalise_spelling(name), name


def test_punctuation_and_spacing_are_normalised():
    assert ss.normalise_spelling("Amoxicillin,") == "amoxicillin"
    assert ss.normalise_spelling("CLAVULANIC   ACID") == "clavulanic acid"
    assert ss.normalise_spelling("Acetyl-Salicylic  Acid") == "acetyl salicylic acid"


# --------------------------------------------------------------------------
# Salt sets
# --------------------------------------------------------------------------

def test_salt_sets_are_order_independent():
    a = ss.canonicalise_salt_set(["AMOXYCILLIN", "CLAVULANIC ACID"])
    b = ss.canonicalise_salt_set(["CLAVULANIC ACID", "AMOXICILLIN"])
    assert a == b


def test_tier1_does_not_apply_synonyms():
    """Tier 1 is exact spelling. Amoxy and Amoxi must NOT match there."""
    assert ss.normalise_salt_set(["AMOXYCILLIN"]) != ss.normalise_salt_set(["AMOXICILLIN"])
    # ...but tier 2 must.
    assert ss.canonicalise_salt_set(["AMOXYCILLIN"]) == ss.canonicalise_salt_set(["AMOXICILLIN"])


# --------------------------------------------------------------------------
# Two-tier matching
# --------------------------------------------------------------------------

class _Row:
    def __init__(self, ref_id, salts, price):
        self.ref_id, self.salts, self.price = ref_id, salts, price


def _salts_of(row):
    return row.salts


def test_tier1_wins_and_tier2_is_never_consulted():
    """An exact-spelling match must shut out the synonym tier entirely.

    This is the guardrail that stops a synonym raising a ceiling that an
    exact match already established.
    """
    candidates = [
        _Row("EXACT", ["AMOXICILLIN"], 10),
        _Row("SYNONYM", ["AMOXYCILLIN"], 999),
    ]
    matches, tier = ss.match_two_tier(["Amoxicillin"], candidates, _salts_of)
    assert tier == "exact"
    assert [m.ref_id for m in matches] == ["EXACT"]
    assert all(m.ref_id != "SYNONYM" for m in matches)


def test_tier2_runs_only_when_tier1_is_empty():
    candidates = [_Row("SYNONYM", ["AMOXYCILLIN"], 999)]
    matches, tier = ss.match_two_tier(["Amoxicillin"], candidates, _salts_of)
    assert tier == "synonym"
    assert [m.ref_id for m in matches] == ["SYNONYM"]


def test_no_match_reports_none_rather_than_guessing():
    candidates = [_Row("OTHER", ["IBUPROFEN"], 5)]
    matches, tier = ss.match_two_tier(["Amoxicillin"], candidates, _salts_of)
    assert tier == "none"
    assert matches == []


def test_tiers_are_never_mixed():
    """Both tiers can match; only the winning tier's rows come back."""
    candidates = [
        _Row("EXACT-A", ["AMOXICILLIN"], 10),
        _Row("EXACT-B", ["AMOXICILLIN"], 20),
        _Row("SYNONYM", ["AMOXYCILLIN"], 999),
    ]
    matches, tier = ss.match_two_tier(["AMOXICILLIN"], candidates, _salts_of)
    assert tier == "exact"
    assert sorted(m.ref_id for m in matches) == ["EXACT-A", "EXACT-B"]
