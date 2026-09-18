"""Reduce the 254k-row brand dataset to data/reference/brand_index.csv.

Phase 0b. Bills say "Augmentin 625". The price lists say "AMOXICILLIN (A) +
CLAVULANIC ACID (B)". This index is the bridge.

Only the columns needed to cross that bridge are kept:

    brand_name_norm, salt_components, strength_mg, strength_kind,
    dosage_form, form_modifier, pack_count, pack_unit, manufacturer,
    is_discontinued, ambiguous, variant_count

THE PRICE COLUMN IS DROPPED AND NEVER WRITTEN. Those prices are scraped,
undated and stale -- Augmentin 625 Duo's listed price already exceeds the
March 2026 NPPA ceiling. A test asserts no field originating in the brand
file can reach a verdict.

Three deliberate behaviours:

  Discontinued brands are KEPT, flagged. An old bill can legitimately list a
  product that has since been withdrawn; refusing to resolve its name would
  turn a readable line gray for no reason.

  Unparseable pack labels leave pack_count NULL rather than guessing. A null
  pack count forces gray downstream, which is the correct outcome.

  Names that resolve to DIFFERENT salt sets are flagged `ambiguous` rather
  than having one arbitrarily chosen. An ambiguous name must never produce a
  red flag.

Run:  python scripts/build_brand_index.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path

from prepare_reference import detect_dosage_form, detect_form_modifiers, parse_strength
# Import, never reimplement: the pipeline owns canonicalisation.
from app.pipeline.salt_synonyms import normalise_spelling

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "data" / "raw" / "brands" / "indian_medicine_data.csv"
OUT_CSV = REPO_ROOT / "data" / "reference" / "brand_index.csv"
OUT_REPORT = REPO_ROOT / "data" / "reference" / "brand_index_report.json"

EXPECTED_SOURCE_ROWS = 253_973


@dataclass
class BrandRow:
    brand_name_norm: str
    brand_name_raw: str
    salt_components: list[str]
    strength_mg: list[float]
    strength_kind: str
    dosage_form: str
    form_modifier: str
    pack_count: str          # "" when unparseable -- forces gray downstream
    pack_unit: str
    manufacturer: str
    is_discontinued: str     # "true"/"false"
    ambiguous: str           # "true" when one name maps to several salt sets
    variant_count: str

    def as_csv_dict(self) -> dict[str, str]:
        d = asdict(self)
        d["salt_components"] = json.dumps(self.salt_components, ensure_ascii=False)
        d["strength_mg"] = json.dumps(self.strength_mg)
        return d


CSV_COLUMNS = list(BrandRow.__dataclass_fields__.keys())

#: Columns from the source we refuse to carry forward. Enforced by a test.
FORBIDDEN_SOURCE_COLUMNS = {"price(₹)", "price", "id"}


# --------------------------------------------------------------------------
# Composition parsing
#
# "Amoxycillin  (500mg) " -> ("AMOXYCILLIN", "500mg")
# "Ambroxol (30mg/5ml)"   -> ("AMBROXOL", "30mg/5ml")
# --------------------------------------------------------------------------

_COMPOSITION = re.compile(r"^\s*(?P<salt>.*?)\s*\((?P<strength>[^()]*)\)\s*$")


def parse_composition(text: str) -> tuple[str, str]:
    """Split "Name (strength)" into (UPPERCASE name, strength text).

    Returns ("", "") for an empty cell, and (name, "") when there is no
    parenthesised strength -- we never invent one.
    """
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return "", ""
    m = _COMPOSITION.match(cleaned)
    if not m:
        return cleaned.upper(), ""
    return m.group("salt").upper().strip(), m.group("strength").strip()


# --------------------------------------------------------------------------
# Pack size parsing
#
# "strip of 10 tablets"        -> 10 tablet
# "bottle of 100 ml Syrup"     -> 100 ml
# "vial of 1 Injection"        -> 1 vial      (no unit token; container wins)
# "vial of 2 ml Injection"     -> 2 ml
# "tube of 15 gm Cream"        -> 15 gm
# "strip of 10 tablet dt"      -> 10 tablet   (dt handled as a form modifier)
# anything else                -> (None, "")  -- pack_count stays NULL
# --------------------------------------------------------------------------

_CONTAINER_TO_UNIT = {
    "strip": "tablet",     # overridden by an explicit unit token when present
    "vial": "vial",
    "ampoule": "vial",
    "amp": "vial",
    "bottle": "ml",
    "tube": "gm",
    "jar": "gm",
    "sachet": "unit",
    "packet": "unit",
    "pack": "unit",
    "box": "unit",
    "tin": "unit",
    "carton": "unit",
    "prefilled syringe": "unit",
    "syringe": "unit",
    "cartridge": "unit",
    "kit": "unit",
    "tetrapack": "ml",
    "can": "ml",
    "disk": "unit",
    "rotacap": "capsule",
    "inhaler": "dose",
}

_UNIT_TOKEN_TO_UNIT = {
    "tablet": "tablet", "tablets": "tablet",
    "capsule": "capsule", "capsules": "capsule",
    "ml": "ml", "gm": "gm", "g": "gm", "gram": "gm", "grams": "gm",
    "vial": "vial", "vials": "vial",
    "suppository": "suppository", "suppositories": "suppository",
    "sachet": "unit", "sachets": "unit",
    "unit": "unit", "units": "unit",
    "dose": "dose", "doses": "dose",
}

_PACK_LABEL = re.compile(
    r"^(?P<container>[a-z ]+?)\s+of\s+(?P<count>[0-9]*\.?[0-9]+)\s*"
    r"(?P<unit>[a-z]+)?\b",
    re.IGNORECASE,
)


def parse_pack_size(label: str) -> tuple[str, str]:
    """Return (pack_count, pack_unit). pack_count is "" when unparseable.

    A null pack count is a legitimate outcome, not a failure. It forces the
    item gray downstream rather than producing a per-unit price from a
    quantity we had to invent.
    """
    text = " ".join((label or "").split())
    if not text:
        return "", ""

    m = _PACK_LABEL.match(text)
    if not m:
        return "", ""

    container = " ".join(m.group("container").lower().split())
    count = m.group("count")
    unit_token = (m.group("unit") or "").lower()

    # An explicit unit token always beats the container's default:
    # "vial of 2 ml Injection" is 2 ml, not 2 vials.
    if unit_token in _UNIT_TOKEN_TO_UNIT:
        return count, _UNIT_TOKEN_TO_UNIT[unit_token]

    if container in _CONTAINER_TO_UNIT:
        return count, _CONTAINER_TO_UNIT[container]

    return "", ""


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def _read_source() -> list[dict[str, str]]:
    if not SOURCE.exists():
        raise SystemExit(
            f"FATAL: {SOURCE.relative_to(REPO_ROOT)} is missing.\n"
            "Run: python scripts/fetch_brand_data.py"
        )
    with SOURCE.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def build() -> tuple[list[BrandRow], dict]:
    source = _read_source()
    if len(source) != EXPECTED_SOURCE_ROWS:
        print(
            f"  WARNING: source has {len(source):,} rows, expected "
            f"{EXPECTED_SOURCE_ROWS:,}. The upstream dataset may have changed.",
            file=sys.stderr,
        )

    stats = Counter()
    by_name: dict[str, list[BrandRow]] = {}

    for raw in source:
        name_raw = " ".join((raw.get("name") or "").split())
        name_norm = normalise_spelling(name_raw)
        if not name_norm:
            stats["skipped_no_name"] += 1
            continue

        salts: list[str] = []
        strength_texts: list[str] = []
        for column in ("short_composition1", "short_composition2"):
            salt, strength = parse_composition(raw.get(column, ""))
            if salt:
                salts.append(salt)
            if strength:
                strength_texts.append(strength)

        if not salts:
            stats["skipped_no_composition"] += 1
            continue

        strength_mg, strength_kind = parse_strength(" ".join(strength_texts))
        pack_label = raw.get("pack_size_label", "")
        pack_count, pack_unit = parse_pack_size(pack_label)
        if not pack_count:
            stats["pack_size_unparseable"] += 1

        row = BrandRow(
            brand_name_norm=name_norm,
            brand_name_raw=name_raw,
            salt_components=sorted(salts),
            strength_mg=strength_mg,
            strength_kind=strength_kind,
            # The pack label names the form ("...Syrup", "...Cream"); the
            # brand name carries it too ("Augmentin 625 Duo Tablet").
            dosage_form=detect_dosage_form(pack_label, name_raw),
            form_modifier=detect_form_modifiers(pack_label),
            pack_count=pack_count,
            pack_unit=pack_unit,
            manufacturer=" ".join((raw.get("manufacturer_name") or "").split()),
            is_discontinued=str(
                (raw.get("Is_discontinued") or "").strip().upper() == "TRUE"
            ).lower(),
            ambiguous="false",
            variant_count="1",
        )
        by_name.setdefault(name_norm, []).append(row)

    # ----------------------------------------------------------------------
    # Deduplicate on normalised name.
    #
    # Where variants disagree about the SALT SET, the name is ambiguous and
    # is flagged rather than resolved. Choosing one arbitrarily is exactly
    # the kind of quiet guess that produces a confident wrong verdict.
    # ----------------------------------------------------------------------
    deduped: list[BrandRow] = []
    for name_norm, variants in by_name.items():
        salt_sets = {tuple(v.salt_components) for v in variants}
        ambiguous = len(salt_sets) > 1

        # Prefer a live product over a discontinued one, then prefer a row
        # with a parseable pack size, then take the first for determinism.
        chosen = sorted(
            variants,
            key=lambda v: (
                v.is_discontinued == "true",
                v.pack_count == "",
                v.brand_name_raw,
            ),
        )[0]

        chosen.ambiguous = str(ambiguous).lower()
        chosen.variant_count = str(len(variants))
        if ambiguous:
            stats["ambiguous_names"] += 1
        if chosen.is_discontinued == "true":
            stats["discontinued_kept"] += 1
        deduped.append(chosen)

    deduped.sort(key=lambda r: r.brand_name_norm)

    report = {
        "source_rows": len(source),
        "indexed_names": len(deduped),
        "skipped_no_name": stats["skipped_no_name"],
        "skipped_no_composition": stats["skipped_no_composition"],
        "pack_size_unparseable": stats["pack_size_unparseable"],
        "ambiguous_names": stats["ambiguous_names"],
        "discontinued_kept": stats["discontinued_kept"],
    }
    return deduped, report


def write_outputs(rows: list[BrandRow], report: dict) -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_csv_dict())

    report["output_bytes"] = OUT_CSV.stat().st_size
    OUT_REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )


def main() -> int:
    rows, report = build()
    write_outputs(rows, report)

    mb = report["output_bytes"] / 1_000_000
    print("=" * 68)
    print("BillSahi brand index")
    print("=" * 68)
    print(f"  source rows            {report['source_rows']:>9,}")
    print(f"  indexed names          {report['indexed_names']:>9,}")
    print(f"  no composition         {report['skipped_no_composition']:>9,}  (skipped)")
    print(f"  pack size unparseable  {report['pack_size_unparseable']:>9,}  (pack_count NULL -> gray)")
    print(f"  ambiguous names        {report['ambiguous_names']:>9,}  (flagged, never red)")
    print(f"  discontinued kept      {report['discontinued_kept']:>9,}  (flagged)")
    print(f"\n  Wrote {OUT_CSV.relative_to(REPO_ROOT)}  ({mb:.1f} MB)")

    if mb > 10:
        print("\n  NOTE: too large to sit comfortably in a Lambda bundle.")
        print("        Phase 4 loads this into DynamoDB at deploy time.")
        print("        See docs/ARCHITECTURE.md.")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
