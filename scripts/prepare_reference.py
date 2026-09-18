"""Build data/reference/reference_prices.csv from the NPPA source files.

Phase 0. This script is the ONLY place government price data enters the
project. Everything downstream reads reference_prices.csv and nothing else.

Three sources, one schema:

  ceiling         All_Drugs_Ceiling_Prices.csv (915 rows)
                  DPCO scheduled formulations. Ceiling price per unit,
                  EXCLUDING taxes. These are the only rows allowed to
                  produce a red flag.

  special_feature Special_Feature_..._for_Specific_Companies.pdf (22 rows)
                  Higher ceilings for special-feature packs. ADDITIONAL to
                  the ceiling rows, never replacements -- Ringer Lactate
                  500 ml exists in both (57.85 ordinary, 66.52 special).

  retail_new_drug Retail_Price_Information.csv (3881 rows)
                  Non-scheduled new drugs. These are per-company approved
                  retail prices, NOT ceilings that bind other companies.
                  Amber/context only, never red.

Two hard rules enforced here:

  1. ZERO DROPPED from the ceiling file. All 915 rows must parse. If any
     row fails, the script exits non-zero. The regex is wrong, not the data.

  2. NOTHING IS EVER INVENTED. A row we cannot parse is marked
     status=quarantined with a machine-readable reason and is invisible to
     the matcher. We never fill in a missing price, unit, SO number or date.

Run:  python scripts/prepare_reference.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

# pdfplumber is only needed for the 22-row special-feature PDF.
import pdfplumber

# --------------------------------------------------------------------------
# Paths. Everything resolves from the repo root so the script behaves the
# same whether it is run from the root or from scripts/.
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
REF_DIR = REPO_ROOT / "data" / "reference"

CEILING_CSV = RAW_DIR / "All_Drugs_Ceiling_Prices.csv"
RETAIL_CSV = RAW_DIR / "Retail_Price_Information.csv"
SPECIAL_PDF = (
    RAW_DIR
    / "Special_Feature_Schedule_Drugs_Ceiling_Prices_fixed_for_Specific_Companies.pdf"
)

OUT_CSV = REF_DIR / "reference_prices.csv"
OUT_QUARANTINE = REF_DIR / "quarantine_log.csv"
OUT_COVERAGE = REF_DIR / "unit_coverage.json"

# Date the NPPA files in data/raw/ were retrieved. Both source CSVs carry
# this date in their header line; it is shown to the user next to every
# verdict. Not a guess -- see the DATE row at the top of each CSV.
RETRIEVED_ON = "2026-09-18"

# Expected row counts. These are assertions about the data we were given,
# not targets to parse towards. A mismatch means the source file changed and
# a human must look before anything downstream is trusted.
EXPECTED_CEILING_ROWS = 915
EXPECTED_SPECIAL_ROWS = 22
EXPECTED_RETAIL_ROWS = 3881


# --------------------------------------------------------------------------
# Output schema
# --------------------------------------------------------------------------

#: Statuses a reference row can carry.
STATUS_USABLE = "usable"
STATUS_QUARANTINED = "quarantined"

#: Machine-readable quarantine reasons. Anything quarantined is invisible to
#: the matcher, so these codes are the audit trail for coverage gaps.
REASON_PRICE_WITHDRAWN = "price_withdrawn"
REASON_PRICE_UNPARSEABLE = "price_unparseable"
REASON_UNIT_MISSING = "unit_missing"
REASON_UNIT_UNMAPPABLE = "unit_unmappable"


@dataclass
class ReferenceRow:
    """One reference price. Field order here is the CSV column order."""

    ref_id: str
    source: str                     # ceiling | special_feature | retail_new_drug
    formulation_raw: str            # verbatim from the source, for display
    salt_components: list[str]      # UPPERCASE, sorted, (A)/(B) markers stripped
    dosage_form: str                # normalised base form; "" if undeterminable
    form_modifier: str              # dispersible|enteric|modified_release|...
    strength_raw: str               # verbatim, whitespace-normalised
    strength_mg: list[float]        # numeric mg values, [] when not mg-based
    strength_kind: str              # mg | percent | concentration | none
    unit_basis: str                 # the enum below
    unit_qty: str                   # how many base units price_ex_gst covers
    price_checkable: str            # "true"/"false" -- see note below
    price_ex_gst: str               # Decimal as string; never a float
    so_number: str
    so_date: str
    manufacturer: str               # retail rows only; "" for ceiling rows
    marketing_company: str          # retail rows only
    retrieved_on: str
    status: str                     # usable | quarantined
    quarantine_reason: str          # "" when usable
    unit_basis_raw: str             # the original unit string, for evidence
    raw_row: str                    # JSON of the source row, for evidence

    def as_csv_dict(self) -> dict[str, str]:
        d = asdict(self)
        d["salt_components"] = json.dumps(self.salt_components, ensure_ascii=False)
        d["strength_mg"] = json.dumps(self.strength_mg)
        return d


CSV_COLUMNS = list(ReferenceRow.__dataclass_fields__.keys())


# --------------------------------------------------------------------------
# Unit basis normalisation
#
# The ceiling file contains 60 distinct unit strings and the retail file 176.
# Every one of them must land in an explicit bucket -- including `other`,
# which is deliberately EXCLUDED from price checks because we cannot say what
# "per unit" means for it.
#
# unit_qty is how many base units the price covers. "Each Pack (5 ml)" means
# the price is for a 5 ml pack, so unit_qty=5 and unit_basis=ml, and the
# per-ml price downstream is price_ex_gst / 5.
# --------------------------------------------------------------------------

UNIT_BASIS_ENUM = {
    "tablet",
    "capsule",
    "ml",
    "gm",
    "vial",
    "pack",
    "dose",
    "suppository",
    "unit",
    "device",
    "cubic_meter",
    "other",
}

#: Unit bases we refuse to run price comparisons against.
#:
#: `pack` is here because "Each Pack" of an unknown count cannot be converted
#: to a per-unit price without inventing the count. Where the pack size IS
#: stated elsewhere on the row -- "Each Pack" + strength "Injection 500 ml" --
#: refine_pack_basis() recovers it and the row becomes ml-based and checkable.
#:
#: NOTE the difference between this and quarantine. status=quarantined means
#: the row's DATA is unusable (no price, withdrawn price, unreadable unit).
#: price_checkable=false means the data is fine but the unit basis does not
#: support a per-unit comparison. A pack row is still shown as evidence and
#: still counts for R9 messaging; it just never produces a price verdict.
#: Conflating the two would silently drop good evidence.
UNIT_BASIS_NOT_PRICE_CHECKABLE = {"other", "pack"}

#: Singular word -> enum. Longest-first matching is applied by the caller.
_UNIT_WORD_TO_BASIS = {
    "tablet": "tablet",
    "tablets": "tablet",
    "tab": "tablet",
    "capsule": "capsule",
    "capsules": "capsule",
    "cap": "capsule",
    "ml": "ml",
    "millilitre": "ml",
    "gm": "gm",
    "gram": "gm",
    "grams": "gm",
    "g": "gm",
    "vial": "vial",
    "vials": "vial",
    "bag": "pack",
    "sachet": "unit",
    "kit": "unit",
    "suppository": "suppository",
    "suppositories": "suppository",
    "pessary": "unit",
    "lozenges": "unit",
    "lozenge": "unit",
    "pastille": "unit",
    "gum": "unit",
    "condom": "unit",
    "iud": "unit",
    "unit": "unit",
    "dose": "dose",
    "metered dose": "dose",
    "pack": "pack",
    "combi pack": "pack",
    "cubic meter": "cubic_meter",
}

#: Unit strings that are genuinely ambiguous about what one unit is. These go
#: to `other` on purpose. Listed explicitly so that the coverage report shows
#: a deliberate decision rather than a parser miss.
_DELIBERATELY_OTHER = {
    "1 gm or 1 ml",                          # gm or ml -- cannot pick one
    "1 gm or 1 ml)( pack",
    "per mg of phospholipids in the pack",   # per-mg-of-ingredient basis
    "20 ml pack)(1 ml pack",                 # two conflicting bases in one cell
}

# "Each Pack (5 ml)", "Each Pack (1000 ml))( Pack", "Each Pack (0.5ml)"
_PACK_WITH_VOLUME = re.compile(
    r"^each\s+pack\s*\(\s*([0-9]*\.?[0-9]+)\s*(ml|gm|g)\s*\)", re.IGNORECASE
)
# "1000ml Glass", "250ml Non-Glass", "2 ML Pack", "10 ml Pack", "0.1 ml",
# "1 Gram", "1 Sachet", "1 kit"
_QTY_THEN_UNIT = re.compile(
    r"^(?:each\s+|per\s+)?([0-9]*\.?[0-9]+)\s*"
    r"(ml|gm|grams|gram|g|tablets|tablet|capsules|capsule|vials|vial|dose|"
    r"suppositories|suppository|condom|iud|gum|lozenges|pastille|pessary|"
    r"sachet|kit|bag|pack|unit)\b",
    re.IGNORECASE,
)
# "Each Vial", "Per Dose", "Per Metered Dose", "Each Pack", "Combi Pack"
_BARE_UNIT = re.compile(
    r"^(?:each\s+|per\s+)?(metered\s+dose|combi\s+pack|cubic\s+meter|tablets|"
    r"tablet|capsules|capsule|vials|vial|dose|pack|bag|sachet|kit|"
    r"suppositories|suppository|condom|iud|gum|lozenges|pastille|pessary|"
    r"unit|ml|gm|grams|gram)\b",
    re.IGNORECASE,
)
# "28's Tablet", "10's Tablets", "28’s Tablets" -- a pack of N tablets. The
# price applies to the whole pack, so unit_qty is N.
#
# If this reading were wrong, the per-unit price would come out N times too
# LOW, which suppresses a flag rather than raising a false one -- and retail
# rows can never produce a red flag in any case. Erring toward silence.
_NS_PACK = re.compile(
    r"^([0-9]+)\s*['’]?\s*s\s+(tablets|tablet|capsules|capsule)\b", re.IGNORECASE
)


def normalise_unit_basis(raw: str) -> tuple[str, Decimal]:
    """Map a source unit string to (unit_basis, unit_qty).

    Returns ("other", Decimal(1)) for anything we cannot confidently read.
    Never raises -- an unreadable unit is a data outcome, not a crash.
    """
    text = " ".join((raw or "").split())
    if not text:
        return "other", Decimal(1)

    # The source sometimes concatenates a second parenthetical, producing
    # trailing artefacts like "1 Tablet)( Pack" or "Each Vial)( Pack". The
    # leading term is the real basis; the trailing ")( Pack" is noise.
    cleaned = re.sub(r"\)\(\s*pack\s*\)?$", "", text, flags=re.IGNORECASE).strip()
    cleaned = cleaned.rstrip(")").strip()

    if cleaned.lower() in _DELIBERATELY_OTHER or text.lower() in _DELIBERATELY_OTHER:
        return "other", Decimal(1)

    # "Each Pack (5 ml)" -- price covers a pack of a stated volume.
    m = _PACK_WITH_VOLUME.match(text)
    if m:
        qty = Decimal(m.group(1))
        basis = _UNIT_WORD_TO_BASIS[m.group(2).lower()]
        return basis, qty

    # "250ml Non-Glass", "2 ML Pack", "1 Tablet", "0.1 ml"
    m = _QTY_THEN_UNIT.match(cleaned)
    if m:
        qty = Decimal(m.group(1))
        basis = _UNIT_WORD_TO_BASIS[m.group(2).lower()]
        return basis, qty

    # "28's Tablet" -- a pack of N tablets.
    m = _NS_PACK.match(cleaned)
    if m:
        return _UNIT_WORD_TO_BASIS[m.group(2).lower()], Decimal(m.group(1))

    # "Each Vial", "Per Metered Dose", "Combi Pack", "Cubic Meter"
    m = _BARE_UNIT.match(cleaned)
    if m:
        word = " ".join(m.group(1).lower().split())
        return _UNIT_WORD_TO_BASIS[word], Decimal(1)

    # "Per Dual chamber bag with special feature" -- the basis word is not at
    # the start, so anchored matching misses it. A bag is one pack; `pack` is
    # excluded from price checks anyway, so this only improves the coverage
    # report's honesty, it does not widen what we are willing to flag.
    if re.search(r"\bbag\b", cleaned, re.IGNORECASE):
        return "pack", Decimal(1)

    return "other", Decimal(1)


#: "Injection 500 ml", "Injection 1000 ml" -- a pack whose size is stated in
#: the strength cell rather than the unit cell.
_STRENGTH_VOLUME = re.compile(
    r"\b([0-9]*\.?[0-9]+)\s*(ml|gm)\b(?!\s*/)", re.IGNORECASE
)


def refine_pack_basis(
    basis: str, qty: Decimal, strength_raw: str
) -> tuple[str, Decimal]:
    """Recover a pack's size from the strength cell when the unit cell omits it.

    The ceiling file prices Ringer Lactate at "Rs 57.85(Each Pack)" with
    strength "Injection 500 ml". The special-feature file prices the same
    product at "Rs 66.52(Each 500 ml pack having special features)", which
    already states its volume. Without this step the two rows would have
    different bases and could not be compared -- and the whole point of the
    special-feature file is that they must be.

    Only applies to `pack`. A volume must be unambiguous: exactly one
    candidate in the strength cell, and not a concentration like
    "250 MG/ 5 ML" (excluded by the negative lookahead in the pattern).

    ONLY safe on a terse, structured strength column. Do not call this on the
    retail file's free-text Formulations column, where a number followed by
    "gm" is the drug's strength rather than the container's size. See the note
    in parse_retail_csv().
    """
    if basis != "pack":
        return basis, qty

    text = " ".join((strength_raw or "").split())
    matches = _STRENGTH_VOLUME.findall(text)
    if len(matches) != 1:
        return basis, qty

    value, unit_word = matches[0]
    return _UNIT_WORD_TO_BASIS[unit_word.lower()], Decimal(value)


# --------------------------------------------------------------------------
# Formulation / salt / strength parsing
# --------------------------------------------------------------------------

#: Strips the combination markers "(A)" / "(B)" / "(C)". Single letter only,
#: so real parentheticals like "(DES)" and "(BVS)" in the stent row survive.
_COMBO_MARKER = re.compile(r"\s*\(\s*[A-Za-z]\s*\)")

#: Dosage forms seen in the source data, longest first so that
#: "powder for injection" wins over "injection".
#:
#: Release/presentation modifiers (dispersible, enteric, modified release...)
#: are NOT in this list -- they are captured separately by
#: detect_form_modifiers(), because they qualify a base form rather than
#: replacing it. A dispersible tablet is still a tablet.
_DOSAGE_FORMS = [
    "powder for injection",
    "oral suspension",
    "oral liquid",
    "nasal spray",
    "dry syrup",
    "suppository",
    "inhalation",
    "suspension",
    "injection",
    "infusion",
    "solution",
    "lozenges",
    "ointment",
    "pastille",
    "pessary",
    "capsule",
    "tablet",
    "syrup",
    "lotion",
    "cream",
    "drops",
    "device",
    "condom",
    "patch",
    "gel",
    "iud",
    "gum",
]


def split_salt_components(formulation: str) -> list[str]:
    """Split a formulation name into sorted, uppercase salt components.

    "Abacavir (A)+Lamivudine (B)"  -> ["ABACAVIR", "LAMIVUDINE"]
    "AMOXYCILLIN + CLAVULANIC ACID" -> ["AMOXYCILLIN", "CLAVULANIC ACID"]
    """
    text = " ".join((formulation or "").split())
    text = _COMBO_MARKER.sub("", text)
    parts = [p.strip(" -\t") for p in text.split("+")]
    salts = [" ".join(p.split()).upper() for p in parts if p.strip()]
    return sorted(salts)


def detect_dosage_form(strength_raw: str, formulation_raw: str) -> str:
    """Read the dosage form off the strength cell, falling back to the name."""
    for haystack in (strength_raw, formulation_raw):
        low = " ".join((haystack or "").split()).lower()
        for form in _DOSAGE_FORMS:
            if form in low:
                return form
    return ""


#: Release / presentation modifiers, as (regex, canonical name).
#:
#: These are part of product identity and therefore part of the price. NPPA
#: demonstrably prices them apart: plain Acetylsalicylic acid Tablet 100 mg is
#: 0.21, while the Effervescent/Dispersible/Enteric coated Tablet 100 mg is
#: 0.22. Treating a modified-release tablet as a plain tablet would measure a
#: bill line against the wrong ceiling.
#:
#: Found via the aspirin case: "TABLET DT 75 MG" (dispersible, SO 1575(E),
#: 0.36) and "Tablet 75 mg" (plain, SO 1581(E), 0.39) were collapsing into
#: one group. See test_dispersible_tablet_is_not_a_plain_tablet.
_FORM_MODIFIERS = [
    (re.compile(r"\bdispersible\b", re.I), "dispersible"),
    (re.compile(r"\bdt\b", re.I), "dispersible"),
    (re.compile(r"\beffervescent\b", re.I), "effervescent"),
    (re.compile(r"\benteric\b", re.I), "enteric"),
    (re.compile(r"\bmodified\s+release\b", re.I), "modified_release"),
    (re.compile(r"\bsustained\s+release\b|\bsr\b", re.I), "sustained_release"),
    (re.compile(r"\bextended\s+release\b|\ber\b|\bxr\b", re.I), "extended_release"),
    (re.compile(r"\bchewable\b", re.I), "chewable"),
]


def detect_form_modifiers(strength_raw: str) -> str:
    """Sorted, pipe-joined release modifiers, or "" when there are none.

    A row carrying several ("Effervescent/ Dispersible/ Enteric coated
    Tablet") keeps all of them, because NPPA priced that combination as one
    category and it is not the same product as any single modifier alone.
    """
    text = " ".join((strength_raw or "").split())
    found = {name for pattern, name in _FORM_MODIFIERS if pattern.search(text)}
    return "|".join(sorted(found))


_MG_VALUE = re.compile(r"([0-9]*\.?[0-9]+)\s*(mcg|mg|gm|g)\b", re.IGNORECASE)
_PERCENT_VALUE = re.compile(r"[0-9]*\.?[0-9]+\s*%")
_CONCENTRATION = re.compile(
    r"[0-9]*\.?[0-9]+\s*(?:mcg|mg|gm|g)\s*/\s*[0-9]*\.?[0-9]*\s*(?:ml|gm|g)\b",
    re.IGNORECASE,
)

_TO_MG = {"mcg": Decimal("0.001"), "mg": Decimal(1), "gm": Decimal(1000), "g": Decimal(1000)}


def parse_strength(strength_raw: str) -> tuple[list[float], str]:
    """Parse a strength cell into (mg values, kind).

    kind is one of:
      mg            -- plain mg/mcg/g strengths, e.g. "Tablet 500 mg"
      concentration -- e.g. "ORAL LIQUID 250 MG/ 5 ML"
      percent       -- e.g. "Cream 2.50%"
      none          -- e.g. "DEVICE --", "CONDOM"

    The mg list is the numerator values in source order. Matching downstream
    must still require strength_raw agreement -- these numbers are an index,
    not a licence to match loosely.
    """
    text = " ".join((strength_raw or "").split())
    if not text:
        return [], "none"

    values: list[float] = []
    for num, suffix in _MG_VALUE.findall(text):
        try:
            values.append(float(Decimal(num) * _TO_MG[suffix.lower()]))
        except (InvalidOperation, KeyError):
            continue

    if _CONCENTRATION.search(text):
        return values, "concentration"
    if values:
        return values, "mg"
    if _PERCENT_VALUE.search(text):
        return [], "percent"
    return [], "none"


# --------------------------------------------------------------------------
# Source 1: the ceiling CSV (primary, zero-dropped)
# --------------------------------------------------------------------------

#: "₹ 39186.03(1 Unit)" -> price, unit string.
#: Verified against all 915 rows: 915/915 match.
_CEILING_PRICE = re.compile(r"^\s*₹\s*([0-9,]+(?:\.[0-9]+)?)\s*\((.*)\)\s*$", re.DOTALL)


def _read_data_rows(path: Path) -> list[list[str]]:
    """Return the real data rows of an NPPA CSV.

    Both CSVs carry 4 junk header lines and an empty first column. A data row
    is one whose SECOND column is an integer serial number. Read with
    utf-8-sig -- the files carry a BOM.
    """
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.reader(fh) if len(r) > 1 and r[1].strip().isdigit()]


def parse_ceiling_csv() -> list[ReferenceRow]:
    rows: list[ReferenceRow] = []
    failures: list[str] = []

    for raw in _read_data_rows(CEILING_CSV):
        # Columns: ["", SL No, NLEM Version, Formulation, Dosage & Strength,
        #           SO Number, SO Date, Ceiling Price]
        serial = raw[1].strip()
        formulation_raw = " ".join(raw[3].split())
        strength_raw = " ".join(raw[4].split())   # some cells contain newlines
        so_number = raw[5].strip()
        so_date = raw[6].strip()
        price_cell = raw[7]

        m = _CEILING_PRICE.match(price_cell)
        if not m:
            failures.append(f"row {serial}: unparseable price cell {price_cell!r}")
            continue

        price = Decimal(m.group(1).replace(",", ""))
        unit_raw = " ".join(m.group(2).split())
        basis, qty = normalise_unit_basis(unit_raw)
        basis, qty = refine_pack_basis(basis, qty, strength_raw)
        strength_mg, strength_kind = parse_strength(strength_raw)

        # A `other` unit basis is quarantined, not dropped: the row stays
        # visible for evidence and coverage reporting but can never be
        # selected for a price comparison.
        if basis == "other":
            status, reason = STATUS_QUARANTINED, REASON_UNIT_UNMAPPABLE
        else:
            status, reason = STATUS_USABLE, ""

        rows.append(
            ReferenceRow(
                ref_id=f"CEIL-{int(serial):04d}",
                source="ceiling",
                formulation_raw=formulation_raw,
                salt_components=split_salt_components(formulation_raw),
                dosage_form=detect_dosage_form(strength_raw, formulation_raw),
                form_modifier=detect_form_modifiers(strength_raw),
                strength_raw=strength_raw,
                strength_mg=strength_mg,
                strength_kind=strength_kind,
                unit_basis=basis,
                unit_qty=str(qty),
                price_checkable=str(basis not in UNIT_BASIS_NOT_PRICE_CHECKABLE).lower(),
                price_ex_gst=str(price),
                so_number=so_number,
                so_date=so_date,
                manufacturer="",
                marketing_company="",
                retrieved_on=RETRIEVED_ON,
                status=status,
                quarantine_reason=reason,
                unit_basis_raw=unit_raw,
                raw_row=json.dumps(raw, ensure_ascii=False),
            )
        )

    # Hard rule: zero dropped from the ceiling file.
    if failures:
        raise SystemExit(
            "FATAL: ceiling file had unparseable rows. The regex is wrong, not\n"
            "the data. Fix the parser; do not fill values in.\n  "
            + "\n  ".join(failures[:20])
        )
    return rows


# --------------------------------------------------------------------------
# Source 2: the special-feature PDF (22 rows)
# --------------------------------------------------------------------------

#: The PDF embeds a font with no usable ToUnicode map, so pdfplumber emits a
#: "(cid:0)" between every glyph of the price column, plus a stray superscript
#: one where the rupee sign should be. extract_tables() still recovers the
#: cell text correctly once these are stripped -- extract_text() does not, so
#: do not switch to it.
_PDF_NOISE = re.compile(r"\(cid:\d+\)")

_SPECIAL_PRICE = re.compile(r"^\s*([0-9,]+(?:\.[0-9]+)?)\s*\((.*)\)\s*$", re.DOTALL)


def _clean_pdf_cell(cell: str | None) -> str:
    text = _PDF_NOISE.sub("", cell or "").replace("¹", "")
    return " ".join(text.split())


def parse_special_feature_pdf() -> list[ReferenceRow]:
    rows: list[ReferenceRow] = []
    failures: list[str] = []

    with pdfplumber.open(SPECIAL_PDF) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for raw in table:
                    cells = [_clean_pdf_cell(c) for c in raw]
                    # Data rows have 6 columns and an integer serial number.
                    if len(cells) < 6 or not cells[0].isdigit():
                        continue

                    serial, formulation_raw, strength_raw, so_number, so_date, price_cell = (
                        cells[0], cells[1], cells[2], cells[3], cells[4], cells[5]
                    )

                    m = _SPECIAL_PRICE.match(price_cell)
                    if not m:
                        failures.append(f"row {serial}: unparseable price {price_cell!r}")
                        continue

                    price = Decimal(m.group(1).replace(",", ""))
                    unit_raw = " ".join(m.group(2).split())
                    basis, qty = normalise_unit_basis(unit_raw)
                    strength_mg, strength_kind = parse_strength(strength_raw)

                    # "Each 500 ml pack having special features" is a pack
                    # whose volume is stated in the unit text -- recover the
                    # volume so the row is comparable per-ml.
                    vol = re.match(
                        r"^each\s+([0-9]*\.?[0-9]+)\s*(ml|gm)\s+pack", unit_raw, re.IGNORECASE
                    )
                    if vol:
                        qty = Decimal(vol.group(1))
                        basis = _UNIT_WORD_TO_BASIS[vol.group(2).lower()]
                    else:
                        basis, qty = refine_pack_basis(basis, qty, strength_raw)

                    if basis == "other":
                        status, reason = STATUS_QUARANTINED, REASON_UNIT_UNMAPPABLE
                    else:
                        status, reason = STATUS_USABLE, ""

                    rows.append(
                        ReferenceRow(
                            ref_id=f"SPEC-{int(serial):02d}",
                            source="special_feature",
                            formulation_raw=formulation_raw,
                            salt_components=split_salt_components(formulation_raw),
                            dosage_form=detect_dosage_form(strength_raw, formulation_raw),
                            form_modifier=detect_form_modifiers(strength_raw),
                            strength_raw=strength_raw,
                            strength_mg=strength_mg,
                            strength_kind=strength_kind,
                            unit_basis=basis,
                            unit_qty=str(qty),
                            price_checkable=str(
                                basis not in UNIT_BASIS_NOT_PRICE_CHECKABLE
                            ).lower(),
                            price_ex_gst=str(price),
                            so_number=so_number,
                            so_date=so_date,
                            manufacturer="",
                            marketing_company="",
                            retrieved_on=RETRIEVED_ON,
                            status=status,
                            quarantine_reason=reason,
                            unit_basis_raw=unit_raw,
                            raw_row=json.dumps(cells, ensure_ascii=False),
                        )
                    )

    if failures:
        raise SystemExit(
            "FATAL: special-feature PDF had unparseable rows:\n  " + "\n  ".join(failures)
        )
    return rows


# --------------------------------------------------------------------------
# Source 3: the retail CSV (non-scheduled, amber/context only)
# --------------------------------------------------------------------------

_PLAIN_PRICE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*$")


def parse_retail_csv() -> list[ReferenceRow]:
    rows: list[ReferenceRow] = []

    for raw in _read_data_rows(RETAIL_CSV):
        # Columns: ["", S.No, Medicines, Formulations, Manufacturer Name,
        #           Marketing Company, Units, Retail Price, SO NO, SO Date]
        serial = raw[1].strip()
        medicines = " ".join(raw[2].split())
        formulations = " ".join(raw[3].split())
        manufacturer = " ".join(raw[4].split())
        marketing = " ".join(raw[5].split())
        unit_raw = " ".join(raw[6].split())
        price_cell = " ".join(raw[7].split())
        so_number = " ".join(raw[8].split()) if len(raw) > 8 else ""
        so_date = " ".join(raw[9].split()) if len(raw) > 9 else ""

        status, reason = STATUS_USABLE, ""
        price: Decimal | None = None

        # Order matters: a withdrawn price gets its own reason code even
        # though it would also fail the numeric parse.
        if "withdraw" in price_cell.lower():
            status, reason = STATUS_QUARANTINED, REASON_PRICE_WITHDRAWN
        else:
            m = _PLAIN_PRICE.match(price_cell)
            if m:
                price = Decimal(m.group(1))
            else:
                status, reason = STATUS_QUARANTINED, REASON_PRICE_UNPARSEABLE

        basis, qty = normalise_unit_basis(unit_raw)
        # NOTE: refine_pack_basis() is deliberately NOT applied here.
        #
        # It reads a pack size out of the strength cell, which is safe for the
        # ceiling file (terse and structured: "Injection 500 ml") but wrong for
        # this file, whose Formulations column is free-text composition. There,
        # "Gemcitabine 1.4gm" is how much DRUG is in the vial, not how big the
        # container is -- RETL-0434 was being priced per 1.4 gm of container.
        # A retail row whose unit cell does not state a basis stays `pack` and
        # is simply not price-checkable. Silence beats a fabricated quantity.
        if status == STATUS_USABLE and not unit_raw:
            status, reason = STATUS_QUARANTINED, REASON_UNIT_MISSING

        # NOTE: an unmappable unit does NOT quarantine a retail row.
        #
        # A row whose unit cell reads "Injection" or "Gel" has a perfectly
        # good price, salt set and manufacturer -- it just does not say what
        # one unit is. price_checkable=false already makes a numeric
        # comparison impossible, so quarantining as well would throw away
        # usable R7 context for no safety gain.
        #
        # This is deliberately NOT symmetric with the ceiling file, where the
        # 4 unmappable rows stay quarantined. Ceiling rows exist only to BE a
        # ceiling; a ceiling you cannot compare against has no other use.
        # Retail rows exist to provide context, which survives the loss of a
        # unit basis. Only price_unparseable, price_withdrawn and unit_missing
        # quarantine a retail row.

        strength_mg, strength_kind = parse_strength(formulations)

        rows.append(
            ReferenceRow(
                ref_id=f"RETL-{int(serial):04d}",
                source="retail_new_drug",
                formulation_raw=medicines,
                salt_components=split_salt_components(medicines),
                dosage_form=detect_dosage_form(unit_raw, formulations),
                form_modifier=detect_form_modifiers(formulations),
                strength_raw=formulations,
                strength_mg=strength_mg,
                strength_kind=strength_kind,
                unit_basis=basis,
                unit_qty=str(qty),
                price_checkable=str(
                    price is not None and basis not in UNIT_BASIS_NOT_PRICE_CHECKABLE
                ).lower(),
                price_ex_gst=str(price) if price is not None else "",
                so_number=so_number,
                so_date=so_date,
                manufacturer=manufacturer,
                marketing_company=marketing,
                retrieved_on=RETRIEVED_ON,
                status=status,
                quarantine_reason=reason,
                unit_basis_raw=unit_raw,
                raw_row=json.dumps(raw, ensure_ascii=False),
            )
        )
    return rows


# --------------------------------------------------------------------------
# Ceiling selection
#
# Lives here in Phase 0 because the Phase 0 acceptance criteria require it
# (Ringer Lactate: "the matcher returns the higher one"). Phase 1's matcher
# imports this rather than reimplementing it.
# --------------------------------------------------------------------------

def per_base_unit_price(row: ReferenceRow) -> Decimal:
    """Price for ONE base unit. Decimal throughout -- never float for money."""
    return Decimal(row.price_ex_gst) / Decimal(row.unit_qty)


def select_highest_applicable_ceiling(
    rows: list[ReferenceRow],
    salt_components: list[str],
    dosage_form: str,
    strength_mg: list[float],
    strength_kind: str,
    unit_basis: str,
    unit_qty: Decimal,
    form_modifier: str = "",
) -> ReferenceRow | None:
    """Return the highest applicable ceiling row, or None.

    "Highest applicable" is deliberately narrow. A candidate must match on
    ALL of: exact salt set, dosage form, strength, unit basis AND pack size.
    Only then do we take the highest per-base-unit price among the survivors,
    so that a legitimate special-feature pack is never flagged against the
    ordinary ceiling.

    PACK SIZE IS PART OF PRODUCT IDENTITY, not a detail. NPPA prices Ringer
    Lactate in four pack sizes, and the small packs are dearer per ml:
    30.62 for 100 ml is 0.3062/ml, while 66.52 for 500 ml is 0.1330/ml.
    Without matching unit_qty, a query for a 500 ml bag would select the
    100 ml row as the "highest" ceiling and permit a price more than twice
    the real cap. Caught by test_ringer_lactate_does_not_match_another_pack_size.

    EXACT strength matching is not optional. The special-feature file prices
    MEROPENEM 500 MG at 1121.96 and MEROPENEM 1000 MG at 851.43 -- the
    smaller vial costs more. Any fuzzy strength match would hand a 1000 mg
    item the 500 mg row's higher ceiling and quietly corrupt every verdict
    about it. See tests/test_reference_data.py::test_meropenem_strength_inversion.

    Retail rows are never candidates: they are per-company approved prices,
    not ceilings that bind anyone else.
    """
    from salt_synonyms import normalise_salt_set

    return _select_with_salt_key(
        rows, salt_components, dosage_form, strength_mg, strength_kind,
        unit_basis, unit_qty, form_modifier, normalise_salt_set,
    )


def _select_with_salt_key(
    rows, salt_components, dosage_form, strength_mg, strength_kind,
    unit_basis, unit_qty, form_modifier, salt_key,
) -> ReferenceRow | None:
    """Shared filter. `salt_key` decides which tier this is."""
    wanted_salts = salt_key(salt_components)
    wanted_mg = sorted(strength_mg)

    candidates = [
        r
        for r in rows
        if r.source in ("ceiling", "special_feature")
        and r.status == STATUS_USABLE
        and r.price_checkable == "true"
        and salt_key(r.salt_components) == wanted_salts
        and r.dosage_form == dosage_form
        and r.form_modifier == form_modifier
        and r.unit_basis == unit_basis
        and Decimal(r.unit_qty) == unit_qty
        and r.strength_kind == strength_kind
        and sorted(r.strength_mg) == wanted_mg
    ]
    if not candidates:
        return None
    return max(candidates, key=per_base_unit_price)


def select_ceiling_two_tier(
    rows: list[ReferenceRow],
    salt_components: list[str],
    dosage_form: str,
    strength_mg: list[float],
    strength_kind: str,
    unit_basis: str,
    unit_qty: Decimal,
    form_modifier: str = "",
) -> tuple[ReferenceRow | None, str]:
    """Two-tier ceiling selection. Returns (row, tier).

    tier is "exact" | "synonym" | "none".

    THE TIER GATE IS APPLIED TO THE WHOLE PRODUCT MATCH, not to the salt set
    alone. This matters, and getting it wrong silently loses real matches.

    Worked example -- Augmentin 625 Duo Tablet:
      Its composition reads AMOXYCILLIN + CLAVULANIC ACID. Gating on the salt
      set alone, tier 1 "succeeds" with four AMOXYCILLIN rows -- a dry syrup,
      an oral suspension and two injections. None is a tablet. Tier 2 never
      runs, and the tablet ceiling (CEIL-0189, spelled AMOXICILLIN, Rs 18.74)
      is never found. The item goes gray for no good reason.

      Gating on the full match, tier 1 finds no AMOXYCILLIN tablet at
      500+125 mg, so tier 2 runs, canonicalises both spellings, and finds it.

    The guardrail is preserved exactly: if ANY exact-spelling row satisfies
    the full criteria, tier 2 never runs, so a synonym can never outrank an
    exact match. "Highest applicable" is still resolved strictly within the
    winning tier.
    """
    from salt_synonyms import canonicalise_salt_set, normalise_salt_set

    exact = _select_with_salt_key(
        rows, salt_components, dosage_form, strength_mg, strength_kind,
        unit_basis, unit_qty, form_modifier, normalise_salt_set,
    )
    if exact is not None:
        return exact, "exact"

    synonym = _select_with_salt_key(
        rows, salt_components, dosage_form, strength_mg, strength_kind,
        unit_basis, unit_qty, form_modifier, canonicalise_salt_set,
    )
    if synonym is not None:
        return synonym, "synonym"

    return None, "none"


# --------------------------------------------------------------------------
# Synonym safety check
# --------------------------------------------------------------------------

def find_synonym_price_conflicts(rows: list[ReferenceRow]) -> list[dict]:
    """Groups where synonym expansion would merge DIFFERENT prices.

    Synonym expansion is only safe while no two rows that canonicalise to the
    same product carry different prices. Today that holds: zero conflicts
    across all 915 ceiling rows. If NPPA ever publishes, say, a paracetamol
    ceiling and a differing acetaminophen ceiling, this must fail loudly
    rather than let the matcher pick one arbitrarily.

    A conflict counts ONLY when synonym expansion introduced it -- the group
    must contain more than one distinct original spelling AND more than one
    distinct per-unit price. Two rows with the same spelling and different
    prices are a pre-existing fact about the source data (NPPA prices some
    formulations differently by pack condition) and are reported separately.
    """
    from salt_synonyms import canonicalise_salt_set, normalise_salt_set

    groups: dict[tuple, list[ReferenceRow]] = {}
    for r in rows:
        if r.source != "ceiling" or r.status != STATUS_USABLE:
            continue
        key = (
            tuple(canonicalise_salt_set(r.salt_components)),
            r.dosage_form,
            r.form_modifier,
            tuple(sorted(r.strength_mg)),
            r.strength_kind,
            r.unit_basis,
            r.unit_qty,
        )
        groups.setdefault(key, []).append(r)

    conflicts = []
    for key, members in groups.items():
        prices = {per_base_unit_price(m) for m in members}
        spellings = {tuple(normalise_salt_set(m.salt_components)) for m in members}
        if len(prices) > 1 and len(spellings) > 1:
            conflicts.append({
                "canonical_salts": list(key[0]),
                "dosage_form": key[1] + (f" ({key[2]})" if key[2] else ""),
                "strength": list(key[3]),
                "unit": f"{key[6]} {key[5]}",
                "spellings": sorted("+".join(s) for s in spellings),
                "prices": sorted(str(p) for p in prices),
                "ref_ids": sorted(m.ref_id for m in members),
            })
    return conflicts


# --------------------------------------------------------------------------
# Build + report
# --------------------------------------------------------------------------

def build() -> list[ReferenceRow]:
    """Parse all three sources. Raises SystemExit on any hard-rule breach."""
    ceiling = parse_ceiling_csv()
    special = parse_special_feature_pdf()
    retail = parse_retail_csv()

    problems = []
    if len(ceiling) != EXPECTED_CEILING_ROWS:
        problems.append(f"ceiling: expected {EXPECTED_CEILING_ROWS}, got {len(ceiling)}")
    if len(special) != EXPECTED_SPECIAL_ROWS:
        problems.append(f"special: expected {EXPECTED_SPECIAL_ROWS}, got {len(special)}")
    if len(retail) != EXPECTED_RETAIL_ROWS:
        problems.append(f"retail: expected {EXPECTED_RETAIL_ROWS}, got {len(retail)}")
    if problems:
        raise SystemExit("FATAL: source row counts changed:\n  " + "\n  ".join(problems))

    return ceiling + special + retail


def _formula_injection_check(rows: list[ReferenceRow]) -> list[str]:
    """Flag any field that a spreadsheet would execute as a formula.

    reference_prices.csv is a machine artefact, but raw_row carries arbitrary
    source text and someone will eventually open it in Excel. A leading
    = + - @ CR or TAB is what turns a cell into code. We report rather than
    mangle, so the data stays byte-faithful to the source.
    """
    hits = []
    for row in rows:
        for key, value in row.as_csv_dict().items():
            if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
                hits.append(f"{row.ref_id}.{key}")
    return hits


def write_outputs(rows: list[ReferenceRow]) -> None:
    REF_DIR.mkdir(parents=True, exist_ok=True)

    # Sorted for reproducible diffs: identical input must give an identical
    # file, byte for byte.
    ordered = sorted(rows, key=lambda r: r.ref_id)

    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in ordered:
            writer.writerow(row.as_csv_dict())

    quarantined = [r for r in ordered if r.status == STATUS_QUARANTINED]
    with OUT_QUARANTINE.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ref_id", "source", "reason", "formulation_raw", "unit_basis_raw", "price_cell_raw"])
        for r in quarantined:
            writer.writerow([r.ref_id, r.source, r.quarantine_reason,
                             r.formulation_raw, r.unit_basis_raw, r.price_ex_gst])

    # Every distinct source unit string and where it landed. This is the
    # artefact that proves no unit was silently ignored.
    coverage: dict[str, dict[str, dict[str, int]]] = {}
    for r in ordered:
        bucket = coverage.setdefault(r.source, {})
        entry = bucket.setdefault(r.unit_basis_raw or "<empty>", {})
        entry[r.unit_basis] = entry.get(r.unit_basis, 0) + 1
    OUT_COVERAGE.write_text(
        json.dumps(coverage, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def report(rows: list[ReferenceRow]) -> None:
    by_source = Counter(r.source for r in rows)
    usable = Counter(r.source for r in rows if r.status == STATUS_USABLE)
    reasons = Counter(r.quarantine_reason for r in rows if r.status == STATUS_QUARANTINED)

    print("=" * 68)
    print("BillSahi reference data  --  NPPA lists retrieved", RETRIEVED_ON)
    print("=" * 68)
    for source in ("ceiling", "special_feature", "retail_new_drug"):
        total = by_source[source]
        ok = usable[source]
        print(f"  {source:<16} {total:>5} rows   {ok:>5} usable   {total - ok:>4} quarantined")
    print(f"  {'TOTAL':<16} {len(rows):>5} rows   "
          f"{sum(usable.values()):>5} usable   "
          f"{len(rows) - sum(usable.values()):>4} quarantined")

    if reasons:
        print("\n  Quarantine reasons:")
        for reason, count in reasons.most_common():
            print(f"    {reason:<22} {count:>5}")

    ceiling_rows = [r for r in rows if r.source == "ceiling"]
    print(f"\n  Ceiling file: {len(ceiling_rows)}/{EXPECTED_CEILING_ROWS} parsed, 0 dropped.")

    conflicts = find_synonym_price_conflicts(rows)
    if conflicts:
        print(f"\n  *** {len(conflicts)} SYNONYM PRICE CONFLICT(S) ***")
        print("      Synonym expansion would merge rows with DIFFERENT prices.")
        print("      Matching must not use the synonym tier until this is resolved.")
        for c in conflicts[:10]:
            print(f"        {'+'.join(c['canonical_salts'])} {c['dosage_form']} "
                  f"{c['strength']} per {c['unit']}")
            print(f"          spellings: {c['spellings']}")
            print(f"          prices:    {c['prices']}  ({', '.join(c['ref_ids'])})")
    else:
        print("  Synonym price-conflict scan: clean (0 conflicting groups).")

    injection = _formula_injection_check(rows)
    if injection:
        print(f"\n  NOTE: {len(injection)} field(s) start with a spreadsheet formula")
        print("        character. Left byte-faithful on purpose; sanitise at")
        print("        any user-facing export instead. First few:")
        for h in injection[:5]:
            print(f"          {h}")
    else:
        print("  Spreadsheet formula-injection scan: clean (0 fields).")

    print(f"\n  Wrote {OUT_CSV.relative_to(REPO_ROOT)}")
    print(f"  Wrote {OUT_QUARANTINE.relative_to(REPO_ROOT)}")
    print(f"  Wrote {OUT_COVERAGE.relative_to(REPO_ROOT)}")
    print("=" * 68)


def main() -> int:
    for path in (CEILING_CSV, RETAIL_CSV, SPECIAL_PDF):
        if not path.exists():
            print(f"FATAL: missing source file {path}", file=sys.stderr)
            return 2
    rows = build()
    write_outputs(rows)
    report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
