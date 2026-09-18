"""Salt-name canonicalisation for two-tier matching.

Phase 0b. The ceiling file itself contains BOTH `AMOXICILLIN` and
`AMOXYCILLIN` as separate rows, and the brand dataset spells it
`Amoxycillin`. Without this module those never meet.

THE CONTRACT, which the rest of the project depends on:

  1. Reference rows keep their ORIGINAL spelling. Nothing here rewrites or
     merges a row in data/reference/. This module only ever expands a query.

  2. Matching is TWO-TIER. Tier 1 matches on exact spelling. Tier 2 -- the
     synonym-expanded form -- runs only if tier 1 found nothing.

  3. "Highest applicable ceiling" is resolved WITHIN THE WINNING TIER ONLY.
     An exact-spelling match is never mixed with a synonym-expanded one, so
     a synonym can never raise the ceiling that an exact match already found.

Two kinds of transformation, and the difference matters:

  ORTHOGRAPHIC RULES are spelling conventions applied to BOTH sides of a
  comparison. `sulph` -> `sulf` is safe because it is a canonicalisation, not
  a claim that two different drugs are the same: phenytoin still equals
  phenytoin afterwards.

  SYNONYMS are genuine claims of identity -- aspirin IS acetylsalicylic acid.
  Each one is hand-curated in salt_synonyms.json and unit-tested.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SYNONYMS_JSON = REPO_ROOT / "data" / "reference" / "salt_synonyms.json"


# --------------------------------------------------------------------------
# Orthographic rules
#
# Safe ONLY because they are applied to both the query and the reference.
# Each one is deliberately narrow; broad rules cause false merges.
# --------------------------------------------------------------------------

def _apply_orthographic_rules(text: str) -> str:
    """Normalise spelling conventions. Applied to both sides of a match."""
    out = text

    # British/IP "sulph" -> international "sulf". Unambiguous: there is no
    # word where "sulph" means anything else.
    out = out.replace("sulph", "sulf")

    # Word-initial "oe" -> "e" (oestradiol -> estradiol).
    #
    # MUST be word-initial. A blanket oe->e turns "coenzyme" into "cenzyme",
    # and Coenzyme Q10 is a real product in the brand dataset.
    out = re.sub(r"\boe", "e", out)

    # NOT applied, and deliberately so:
    #   ph -> f       would wreck phenytoin, morphine, phosphate
    #   y  -> i       would merge unrelated names; amoxycillin is handled
    #                 by an explicit synonym instead
    #   ae -> e       little value for drug names, real false-merge risk
    return out


_PUNCTUATION = re.compile(r"[^a-z0-9\s]+")
_WHITESPACE = re.compile(r"\s+")


def normalise_spelling(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, apply ortho rules.

    This is TIER 1's key. It does not consult the synonym table, so two
    genuinely different names never collide here.
    """
    out = (name or "").lower().strip()
    out = _PUNCTUATION.sub(" ", out)
    out = _WHITESPACE.sub(" ", out).strip()
    return _apply_orthographic_rules(out)


# --------------------------------------------------------------------------
# The synonym table
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _variant_to_canonical() -> dict[str, str]:
    """Flatten salt_synonyms.json into {normalised variant: canonical}.

    Raises on a variant claimed by two canonicals -- an ambiguous table is a
    bug, not something to resolve arbitrarily at runtime.
    """
    raw = json.loads(SYNONYMS_JSON.read_text(encoding="utf-8"))
    table = raw["synonyms"]

    mapping: dict[str, str] = {}
    for canonical, variants in table.items():
        canon_norm = normalise_spelling(canonical)
        for name in [canonical, *variants]:
            key = normalise_spelling(name)
            if key in mapping and mapping[key] != canon_norm:
                raise ValueError(
                    f"synonym table is ambiguous: {name!r} maps to both "
                    f"{mapping[key]!r} and {canon_norm!r}"
                )
            mapping[key] = canon_norm
    return mapping


def canonicalise_salt(name: str) -> str:
    """TIER 2's key: spelling-normalised, then mapped through the synonyms.

    A name with no synonym entry simply comes back spelling-normalised, so
    tier 2 is always a superset of tier 1.
    """
    key = normalise_spelling(name)
    return _variant_to_canonical().get(key, key)


def canonicalise_salt_set(salts: list[str]) -> list[str]:
    """Canonicalise every component and sort, for comparing combinations."""
    return sorted(canonicalise_salt(s) for s in salts)


def normalise_salt_set(salts: list[str]) -> list[str]:
    """Tier 1 key for a salt set: spelling-normalised only, no synonyms."""
    return sorted(normalise_spelling(s) for s in salts)


def all_synonym_pairs() -> list[tuple[str, str]]:
    """Every (variant, canonical) pair. Used to unit-test the whole table."""
    raw = json.loads(SYNONYMS_JSON.read_text(encoding="utf-8"))
    pairs = []
    for canonical, variants in raw["synonyms"].items():
        for variant in variants:
            pairs.append((variant, canonical))
    return pairs


# --------------------------------------------------------------------------
# Two-tier matching
# --------------------------------------------------------------------------

def match_two_tier(
    query_salts: list[str],
    candidates: list,
    salts_of,
) -> tuple[list, str]:
    """Return (matching candidates, tier) for a salt set.

    tier is "exact" when tier 1 produced matches, "synonym" when tier 2 did,
    and "none" when neither did.

    The tiers are never mixed. Callers resolve "highest applicable ceiling"
    inside the returned list, which is why a synonym can never outrank an
    exact-spelling match -- if tier 1 matched at all, tier 2 was never run.
    """
    wanted_exact = normalise_salt_set(query_salts)
    tier1 = [c for c in candidates if normalise_salt_set(salts_of(c)) == wanted_exact]
    if tier1:
        return tier1, "exact"

    wanted_canon = canonicalise_salt_set(query_salts)
    tier2 = [c for c in candidates if canonicalise_salt_set(salts_of(c)) == wanted_canon]
    if tier2:
        return tier2, "synonym"

    return [], "none"
