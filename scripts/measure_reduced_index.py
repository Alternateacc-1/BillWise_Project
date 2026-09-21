"""Would a REDUCED brand index fit in the Lambda bundle, and buy anything?

The full brand index is 36 MB and is deliberately not deployed, so brand
resolution works locally and not in production. That gap is worse than missing
coverage: it means what we test is not what runs.

Option 1 is to ship only the brands that could ever produce a verdict. This
measures whether that option exists before anyone builds it.

THE FILTER IS SALT-SET BASED, NOT SALT-MEMBER BASED, and the distinction is
the whole measurement. A brand resolving to pantoprazole + domperidone may
survive only if THAT COMBINATION has a ceiling row. Filtering on "any
constituent salt appears somewhere in the 915" would drag in most of the
Indian combination market and shrink nothing.

Reports: the size, and what the filter does to the six brands on the real
retail bill we have been testing against.

Run:  python scripts/measure_reduced_index.py
"""

from __future__ import annotations

import csv
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.pipeline.match import load_reference  # noqa: E402
from app.pipeline.salt_synonyms import (  # noqa: E402
    canonicalise_salt_set,
    normalise_salt_set,
)

BRAND_INDEX = REPO_ROOT / "data" / "reference" / "brand_index.csv"
CEILING_SOURCES = ("ceiling", "special_feature")

#: The six brands from the real retail pharmacy bill. Product names only --
#: no patient, doctor, invoice or registration detail from that bill exists
#: anywhere in this repo.
REAL_BILL_BRANDS = [
    "pantocid dsr capsule", "ofivay oz tab", "sinalate tablet",
    "eferim sp tab", "becosule cap", "medinoze 0 05 nasal spray",
]


def main() -> int:
    if not BRAND_INDEX.exists():
        print(f"  brand_index.csv not found at {BRAND_INDEX}")
        print("  Run: python scripts/build_brand_index.py")
        return 1

    # Every salt SET that has a ceiling row, in both spelling tiers.
    ceiling_sets: set[tuple[str, ...]] = set()
    for row in load_reference():
        if row.source not in CEILING_SOURCES or not row.price_checkable:
            continue
        salts = list(getattr(row, "salt_components", None) or [])
        if not salts:
            continue
        ceiling_sets.add(tuple(normalise_salt_set(salts)))
        ceiling_sets.add(tuple(canonicalise_salt_set(salts)))

    print("=" * 74)
    print("REDUCED BRAND INDEX -- would option 1 fit, and would it help?")
    print("=" * 74)
    print(f"\n  distinct salt SETS with a ceiling row : {len(ceiling_sets)}")

    total = kept = 0
    kept_bytes = 0
    header_len = 0
    survivors: dict[str, bool] = {}

    with BRAND_INDEX.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        header_len = len(",".join(reader.fieldnames or [])) + 1
        for row in reader:
            total += 1
            try:
                salts = json.loads(row["salt_components"])
            except (ValueError, KeyError):
                salts = []
            if not salts:
                continue
            exact = tuple(normalise_salt_set(salts))
            canon = tuple(canonicalise_salt_set(salts))
            survives = exact in ceiling_sets or canon in ceiling_sets
            name = row.get("brand_name_norm", "")
            if name in REAL_BILL_BRANDS:
                survivors[name] = survives
            if survives:
                kept += 1
                kept_bytes += sum(len(str(v or "")) + 1 for v in row.values())

    mb = (kept_bytes + header_len) / 1_000_000
    print(f"  brands in the full index              : {total:,}")
    print(f"  brands whose SALT SET has a ceiling   : {kept:,}  "
          f"({kept / total * 100:.1f}%)")
    print(f"  estimated reduced size                : {mb:.2f} MB")
    print("  reference data already in the bundle  : 3.26 MB")
    print(f"  bundle total if shipped               : {mb + 3.26:.2f} MB")

    print("\n  WHAT THE FILTER DOES TO THE REAL BILL'S SIX BRANDS:")
    for name in REAL_BILL_BRANDS:
        if name not in survivors:
            print(f"     {name:<30} NOT IN THE INDEX AT ALL")
        else:
            verdict = "KEPT" if survivors[name] else "DROPPED (no ceiling for its salt set)"
            print(f"     {name:<30} {verdict}")

    print("\n" + "=" * 74)
    if not any(survivors.values()):
        print("  NONE of the real bill's brands survives the filter.")
        print("  A reduced index would not relabel a single line of the bill")
        print("  being demoed. Option 1 buys nothing HERE -- which is the")
        print("  argument for option 3: keep the full index locally, ship")
        print("  nothing, and say so in the claim audit.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
