"""What is this bill line? Pure Python in local mode; Bedrock is optional.

Two jobs:

  CATEGORISE -- is this a drug, a consumable, or a service? This decides
  which gray reason applies, and the two mean opposite things to the user:

    no_public_ceiling   room rent, nursing, consultation, OT and lab charges,
                        gloves, syringes, cannulae. No published ceiling
                        exists for these and none ever did. We checked them
                        for arithmetic and duplication and say so plainly.
                        THIS IS A FEATURE, not a gap.

    could_not_verify    it looks like a medicine, but the reading was not
                        HIGH, or the name did not resolve, or the match was
                        ambiguous. A ceiling may well exist; we cannot
                        responsibly say which one applies.

  RESOLVE -- map a brand name to salts, strength, form and pack size, using
  brand_index.csv. Exact normalised match first, then fuzzy >= 92 with the
  strength corroborated from the raw text. Nothing else is eligible for red.
"""

from __future__ import annotations

import csv
import json
import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from ..models import ItemCategory, MatchType, NormalizedItem, VerifiedItem
from .salt_synonyms import normalise_spelling

REPO_ROOT = Path(__file__).resolve().parents[3]
BRAND_INDEX_CSV = REPO_ROOT / "data" / "reference" / "brand_index.csv"

FUZZY_BRAND_MIN = 92


# --------------------------------------------------------------------------
# Categorisation
#
# Keyword-driven and deliberately boring. A wrong category only ever changes
# WHICH gray message the user sees, never whether an item is flagged red, so
# a conservative keyword list is the right tool.
# --------------------------------------------------------------------------

_SERVICE_PATTERNS = [
    r"\broom\b", r"\bward\b", r"\bbed\s*charge", r"\bicu\b", r"\bhdu\b",
    r"\bnursing\b", r"\battendant\b", r"\bconsultation\b", r"\bconsultant\b",
    r"\bdoctor\s*(visit|fee)", r"\bvisit\s*charge", r"\bregistration\b",
    r"\badmission\b", r"\bdischarge\b", r"\bot\s*charge", r"\boperation\s*theatre",
    r"\btheatre\b", r"\bsurgeon\b", r"\banaesthet", r"\banesthe",
    r"\bprocedure\b", r"\bdressing\s*charge", r"\bphysiothe",
    r"\bdiet\b", r"\bfood\b", r"\bambulance\b", r"\bservice\s*charge",
    r"\bmonitoring\b", r"\boxygen\s*charge", r"\bbio[\s-]*medical",
    r"\bx[\s-]*ray\b", r"\bultrasound\b", r"\busg\b", r"\bct\s*scan", r"\bmri\b",
    r"\becg\b", r"\becho\b", r"\bblood\s*(test|sugar|group)", r"\bcbc\b",
    r"\bhaemogram\b", r"\bhemogram\b", r"\bcreatinine\b", r"\bculture\b",
    r"\bbiopsy\b", r"\bpathology\b", r"\blab\b", r"\blaboratory\b",
    r"\bprofile\b", r"\bpanel\b", r"\bscreening\b",
]

_CONSUMABLE_PATTERNS = [
    r"\bsyringe\b", r"\bneedle\b", r"\bglove", r"\bmask\b", r"\bgown\b",
    r"\bcannula\b", r"\bcatheter\b", r"\biv\s*set", r"\binfusion\s*set",
    r"\bdrip\s*set", r"\bcotton\b", r"\bgauze\b", r"\bbandage\b",
    r"\badhesive\b", r"\bmicropore\b", r"\bplaster\b", r"\bdressing\s*(pad|kit)",
    r"\bspirit\b", r"\bsavlon\b", r"\bbetadine\b", r"\bsanitiz",
    r"\burine\s*bag", r"\bdiaper\b", r"\bunderpad\b", r"\bapron\b",
    r"\bscalp\s*vein", r"\bthree\s*way", r"\bstopcock\b", r"\bsuction\b",
    r"\btubing\b", r"\bdisposable\b", r"\bkit\b", r"\bsticker\b",
]

_DRUG_HINT_PATTERNS = [
    r"\d+\s*mg\b", r"\d+\s*mcg\b", r"\d+\s*ml\b", r"\d+\s*gm?\b", r"\d+\s*iu\b",
    r"\btab\b", r"\btablet", r"\bcap\b", r"\bcapsule", r"\binj\b", r"\binjection",
    r"\bsyrup\b", r"\bsuspension\b", r"\bdrops?\b", r"\bointment\b", r"\bcream\b",
    r"\bvial\b", r"\bampoule\b", r"\binfusion\b", r"\bsachet\b", r"\bnebul",
]

_SERVICE_RE = [re.compile(p, re.I) for p in _SERVICE_PATTERNS]
_CONSUMABLE_RE = [re.compile(p, re.I) for p in _CONSUMABLE_PATTERNS]
_DRUG_HINT_RE = [re.compile(p, re.I) for p in _DRUG_HINT_PATTERNS]


def categorise(name: str) -> ItemCategory:
    """Classify a bill line. Services and consumables are checked first.

    Order matters: "IV Set" contains no drug hint, but "Inj. Ceftriaxone"
    does. A line matching a service or consumable pattern is never a drug,
    because those patterns are specific and the drug hints are generic.
    """
    text = " ".join((name or "").split())
    if not text:
        return ItemCategory.UNKNOWN

    if any(p.search(text) for p in _SERVICE_RE):
        return ItemCategory.SERVICE
    if any(p.search(text) for p in _CONSUMABLE_RE):
        return ItemCategory.CONSUMABLE
    if any(p.search(text) for p in _DRUG_HINT_RE):
        return ItemCategory.DRUG
    return ItemCategory.UNKNOWN


# --------------------------------------------------------------------------
# Brand index
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_brand_index(path: str | None = None) -> dict[str, dict]:
    """Load brand_index.csv, or return {} if it has not been built.

    Returning {} rather than raising is deliberate: the engine must work
    without the 36 MB index so that a fresh clone can run the tests and the
    CLI offline. Without it, resolution falls back to reading the salt name
    straight off the bill line, and unresolved items go gray -- which is the
    correct outcome, not a failure.
    """
    target = Path(path) if path else BRAND_INDEX_CSV
    if not target.exists():
        return {}
    index: dict[str, dict] = {}
    with target.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            row["salt_components"] = json.loads(row["salt_components"])
            row["strength_mg"] = json.loads(row["strength_mg"])
            index[row["brand_name_norm"]] = row
    return index


_STRENGTH_IN_TEXT = re.compile(r"([0-9]*\.?[0-9]+)\s*(mg|mcg|gm|g)\b", re.IGNORECASE)
_TO_MG = {"mcg": Decimal("0.001"), "mg": Decimal(1), "gm": Decimal(1000), "g": Decimal(1000)}


def strengths_in_text(text: str) -> set[float]:
    values = set()
    for number, suffix in _STRENGTH_IN_TEXT.findall(text or ""):
        try:
            values.add(float(Decimal(number) * _TO_MG[suffix.lower()]))
        except (InvalidOperation, KeyError):
            continue
    return values


# --------------------------------------------------------------------------
# Generic-name resolution
#
# Most hospital pharmacy lines are NOT brand names. "Paracetamol 500mg
# Tablet", "Ringer Lactate Injection 500 ml" and "Bare Metal Stent" are all
# named directly in the NPPA data. Without this fallback the brand index
# resolves none of them and the entire bill goes gray.
# --------------------------------------------------------------------------

_FORM_FROM_TEXT = [
    ("powder for injection", "powder for injection"),
    ("oral suspension", "oral suspension"),
    ("oral liquid", "oral liquid"),
    ("nasal spray", "nasal spray"),
    ("dry syrup", "dry syrup"),
    ("suppository", "suppository"),
    ("inhalation", "inhalation"),
    ("suspension", "suspension"),
    ("injection", "injection"),
    ("infusion", "infusion"),
    ("ointment", "ointment"),
    ("capsule", "capsule"),
    ("tablet", "tablet"),
    ("syrup", "syrup"),
    ("lotion", "lotion"),
    ("cream", "cream"),
    ("drops", "drops"),
    ("device", "device"),
    ("stent", "device"),
    ("gel", "gel"),
    ("inj", "injection"),
    ("tab", "tablet"),
    ("cap", "capsule"),
]

_MODIFIER_FROM_TEXT = [
    (re.compile(r"\bdispersible\b|\bdt\b", re.I), "dispersible"),
    (re.compile(r"\beffervescent\b", re.I), "effervescent"),
    (re.compile(r"\benteric\b", re.I), "enteric"),
    (re.compile(r"\bmodified\s+release\b|\bmr\b", re.I), "modified_release"),
    (re.compile(r"\bsustained\s+release\b|\bsr\b", re.I), "sustained_release"),
    (re.compile(r"\bextended\s+release\b|\ber\b|\bxr\b", re.I), "extended_release"),
    (re.compile(r"\bchewable\b", re.I), "chewable"),
]

_VOLUME_IN_TEXT = re.compile(r"([0-9]*\.?[0-9]+)\s*(ml|gm)\b(?!\s*/)", re.IGNORECASE)

#: dosage form -> the base unit a ceiling would be quoted in.
_FORM_TO_UNIT_BASIS = {
    "tablet": "tablet",
    "capsule": "capsule",
    "injection": "vial",
    "powder for injection": "vial",
    "infusion": "ml",
    "oral liquid": "ml",
    "oral suspension": "ml",
    "suspension": "ml",
    "syrup": "ml",
    "dry syrup": "ml",
    "drops": "ml",
    "lotion": "ml",
    "cream": "gm",
    "ointment": "gm",
    "gel": "gm",
    "suppository": "suppository",
    "inhalation": "dose",
    "nasal spray": "dose",
    "device": "unit",
}


def detect_form_from_text(text: str) -> str:
    low = " ".join((text or "").split()).lower()
    for needle, form in _FORM_FROM_TEXT:
        if re.search(rf"\b{re.escape(needle)}\b", low):
            return form
    return ""


def detect_modifier_from_text(text: str) -> str | None:
    """Return the stated modifier, or None meaning UNKNOWN.

    None is the common case and is NOT the same as "" (explicitly plain).
    None makes select_ceiling widen across modifier variants and take the
    highest, resolving the ambiguity in the hospital's favour.
    """
    for pattern, name in _MODIFIER_FROM_TEXT:
        if pattern.search(text or ""):
            return name
    return None


@lru_cache(maxsize=1)
def _salt_name_index() -> dict[str, list[str]]:
    """{normalised salt-set name: salt components} from the NPPA reference.

    Built from the reference rows themselves, so it can only ever contain
    names that a ceiling actually exists for.
    """
    from .match import load_reference

    index: dict[str, list[str]] = {}
    for row in load_reference():
        if row.source not in ("ceiling", "special_feature"):
            continue
        key = normalise_spelling(row.formulation_raw)
        if key:
            index.setdefault(key, row.salt_components)
        for salt in row.salt_components:
            salt_key = normalise_spelling(salt)
            if salt_key:
                index.setdefault(salt_key, [salt])
    return index


def resolve_generic(index_num: int, name: str) -> NormalizedItem | None:
    """Resolve a generic/INN item name straight against the NPPA reference."""
    text = " ".join((name or "").split())
    name_norm = normalise_spelling(text)
    if not name_norm:
        return None

    salt_index = _salt_name_index()

    # Longest containment match wins: "ringer lactate" beats "lactate".
    best_key = None
    for key in salt_index:
        if len(key) < 4:
            continue
        if re.search(rf"\b{re.escape(key)}\b", name_norm):
            if best_key is None or len(key) > len(best_key):
                best_key = key

    # Fall back to fuzzy on the whole line, for plurals and small typos
    # ("Bare Metal Stent" vs "Bare Metal Stents").
    note = "generic_name_exact_match"
    if best_key is None:
        candidate = process.extractOne(
            name_norm, salt_index.keys(), scorer=fuzz.token_sort_ratio,
            score_cutoff=FUZZY_BRAND_MIN,
        )
        if candidate is None:
            return None
        best_key = candidate[0]
        note = f"generic_name_fuzzy_match:score={candidate[1]:.0f}"

    salts = salt_index[best_key]
    form = detect_form_from_text(text)
    strengths = sorted(strengths_in_text(text))
    volume = _VOLUME_IN_TEXT.findall(text)

    unit_basis = _FORM_TO_UNIT_BASIS.get(form, "")
    pack_count: Decimal | None = None
    pack_unit = ""
    pack_source = ""

    # A volume stated on the bill is CERTAIN: "Injection 500 ml" is a 500 ml
    # bag, not an ambiguous strip-or-unit quantity.
    if len(volume) == 1:
        pack_count = Decimal(volume[0][0])
        pack_unit = "ml" if volume[0][1].lower() == "ml" else "gm"
        unit_basis = pack_unit
        pack_source = "bill_text"
        # The volume is the pack size, not a drug strength.
        strengths = [s for s in strengths if s != float(pack_count)]
    elif form == "device":
        pack_count = Decimal("1")
        pack_unit = "unit"
        unit_basis = "unit"
        pack_source = "bill_text"

    return NormalizedItem(
        index=index_num,
        category=ItemCategory.DRUG,
        match_type=MatchType.EXACT,
        salt_components=salts,
        strength_mg=strengths,
        strength_kind="mg" if strengths else "none",
        dosage_form=form,
        form_modifier=detect_modifier_from_text(text),
        pack_count=pack_count,
        pack_unit=pack_unit,
        unit_basis=unit_basis or "tablet",
        pack_count_source=pack_source,
        matched_brand="",
        notes=[note],
    )


def _from_brand_row(index_num: int, row: dict, match_type: MatchType, note: str) -> NormalizedItem:
    pack_count = None
    if row.get("pack_count"):
        try:
            pack_count = Decimal(row["pack_count"])
        except InvalidOperation:
            pack_count = None

    ambiguous = row.get("ambiguous") == "true"
    notes = [note]
    if ambiguous:
        notes.append("brand_name_maps_to_multiple_salt_sets")
    if pack_count is None:
        notes.append("pack_size_unknown")

    return NormalizedItem(
        index=index_num,
        category=ItemCategory.DRUG,
        # An ambiguous name can never be EXACT, so it can never produce red.
        match_type=MatchType.AMBIGUOUS if ambiguous else match_type,
        salt_components=row["salt_components"],
        strength_mg=row["strength_mg"],
        strength_kind=row.get("strength_kind", "none"),
        dosage_form=row.get("dosage_form", ""),
        # The brand index records a modifier only when the pack label stated
        # one. A blank there means UNKNOWN, not "plain" -- so it maps to
        # None, which makes select_ceiling widen and pick the highest.
        form_modifier=row.get("form_modifier") or None,
        pack_count=pack_count,
        pack_unit=row.get("pack_unit", ""),
        unit_basis=row.get("pack_unit", "") or "tablet",
        # Inferred from a pack label, so "Qty 1" is genuinely ambiguous
        # between one tablet and one strip. This is what makes R5 compute
        # both interpretations.
        pack_count_source="brand_index" if pack_count is not None else "",
        matched_brand=row.get("brand_name_raw", ""),
        notes=notes,
    )


def normalize_item(item: VerifiedItem, brand_index: dict[str, dict] | None = None) -> NormalizedItem:
    """Resolve one verified line into salts, strength, form and pack size."""
    index = load_brand_index() if brand_index is None else brand_index
    category = categorise(item.name)

    if category in (ItemCategory.SERVICE, ItemCategory.CONSUMABLE):
        return NormalizedItem(
            index=item.index,
            category=category,
            match_type=MatchType.NONE,
            notes=["no_public_ceiling_exists_for_this_category"],
        )

    name_norm = normalise_spelling(item.name)
    if not name_norm:
        return NormalizedItem(index=item.index, category=category, notes=["empty_name"])

    # Tier 1: exact normalised brand name.
    row = index.get(name_norm)
    if row is not None:
        return _from_brand_row(item.index, row, MatchType.EXACT, "brand_exact_match")

    # Tier 2: fuzzy >= 92, but ONLY if a strength in the raw bill text
    # corroborates the candidate. A name that merely looks similar is not
    # enough to price someone's medicine against.
    if index:
        best = process.extractOne(
            name_norm, index.keys(), scorer=fuzz.token_sort_ratio,
            score_cutoff=FUZZY_BRAND_MIN,
        )
        if best is not None:
            candidate = index[best[0]]
            bill_strengths = strengths_in_text(item.name)
            candidate_strengths = set(candidate["strength_mg"])
            if bill_strengths and bill_strengths & candidate_strengths:
                return _from_brand_row(
                    item.index, candidate, MatchType.EXACT,
                    f"brand_fuzzy_match:score={best[1]:.0f}:strength_corroborated",
                )
            return _from_brand_row(
                item.index, candidate, MatchType.PROBABLE,
                f"brand_fuzzy_match:score={best[1]:.0f}:strength_not_corroborated",
            )

    # Tier 3: a generic / INN name straight out of the NPPA reference.
    # Most hospital pharmacy lines are generic, not branded.
    generic = resolve_generic(item.index, item.name)
    if generic is not None:
        return generic

    return NormalizedItem(
        index=item.index,
        category=category,
        match_type=MatchType.NONE,
        notes=["name_did_not_resolve"],
    )


def normalize_bill(items: list[VerifiedItem], brand_index: dict[str, dict] | None = None) -> list[NormalizedItem]:
    return [normalize_item(i, brand_index) for i in items]
