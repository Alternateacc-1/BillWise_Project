"""Stage the reference data into the Lambda bundle. Run before `sam build`.

The SAM template's CodeUri is `backend/`, so anything outside that directory
is simply not deployed. The reference prices live in `data/reference/`, so
without this step the Lambda starts and then fails on its first bill with a
FileNotFoundError -- at runtime, in production, which is the worst place to
discover it.

What gets staged and what does NOT:

  reference_prices.csv   YES, 3.2 MB. The engine cannot produce a verdict
                         without it.
  salt_synonyms.json     YES, tiny, and load-bearing for matching.
  brand_index.csv        REDUCED and staged, ~12.9 MB of 36 MB. See
                         reduce_brand_index() below for the filter and why it
                         is MEMBER-based rather than SET-based. The full 36 MB
                         file is never deployed: too large for the bundle and
                         slow to parse on a cold start.
  eval/fixtures/*.json   YES, a few KB. These are the "Try a sample bill"
                         demo bills. Missed on the first deploy, which made
                         POST /bills/sample return a bare 500 -- the exact
                         button a judge presses first.

Run:  python scripts/stage_lambda.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "data" / "reference"
TARGET = REPO_ROOT / "backend" / "reference_data"

FIXTURE_SOURCE = REPO_ROOT / "eval" / "fixtures"
FIXTURE_TARGET = REPO_ROOT / "backend" / "fixtures"

REQUIRED = ["reference_prices.csv", "salt_synonyms.json"]

BRAND_INDEX_SOURCE = SOURCE / "brand_index.csv"
BRAND_INDEX_TARGET = TARGET / "brand_index.csv"


def reduce_brand_index() -> int:
    """Stage the brands that can produce an HONEST ANSWER, not just a price.

    THE FILTER IS MEMBER-BASED, AND THE EARLIER SET-BASED ONE WAS WRONG.

    A set-based filter keeps a brand only if its whole salt COMBINATION has a
    ceiling row. That answers "can we PRICE this?", which is a two-state
    question -- and the engine has three states, because R9 has a third
    branch:

        priced            we resolved it and a ceiling exists
        no_public_ceiling we resolved it and NO ceiling exists  <-- needs the
                          brand, and the set rule threw it away
        could_not_identify we did not resolve it at all

    Measured consequence: the set rule dropped PANTOCID DSR, a real medicine on
    a real bill that resolves cleanly to DOMPERIDONE + PANTOPRAZOLE. Both salts
    are in the 915; the COMBINATION is not. That is precisely the finding worth
    reporting, and the set rule deleted the data needed to report it, turning
    an honest "not price-controlled" back into "we could not identify it".

    The member rule keeps a brand when EVERY salt appears somewhere in the 915,
    in any form or strength. Cost, measured: 96,489 brands and 12.9 MB versus
    73,717 and 9.4 MB -- 1.38x for 22,772 more brands.

    It is still a REDUCTION, not the whole index. A brand with a salt that
    appears nowhere in the 915 can never yield either verdict, so shipping it
    would cost cold-start time to no effect. SINALATE (diphenhydramine) and
    MEDINOZE (oxymetazoline) drop for exactly that reason and stay
    could_not_identify -- which is honest, because we genuinely hold nothing
    about those molecules.
    """
    import csv
    import json
    import sys as _sys

    _sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.pipeline.match import load_reference
    from app.pipeline.salt_synonyms import canonicalise_salt_set, normalise_salt_set

    members: set[str] = set()
    for row in load_reference():
        if row.source not in ("ceiling", "special_feature") or not row.price_checkable:
            continue
        salts = list(getattr(row, "salt_components", None) or [])
        if not salts:
            continue
        members.update(normalise_salt_set(salts))
        members.update(canonicalise_salt_set(salts))

    kept = 0
    with BRAND_INDEX_SOURCE.open(encoding="utf-8", newline="") as src,          BRAND_INDEX_TARGET.open("w", encoding="utf-8", newline="") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            try:
                salts = json.loads(row["salt_components"])
            except (ValueError, KeyError):
                continue
            if not salts:
                continue
            if (all(s in members for s in normalise_salt_set(salts))
                    or all(s in members for s in canonicalise_salt_set(salts))):
                writer.writerow(row)
                kept += 1
    return kept


def main() -> int:
    missing = [n for n in REQUIRED if not (SOURCE / n).exists()]
    if missing:
        raise SystemExit(
            "FATAL: missing reference data: " + ", ".join(missing) + "\n"
            "Run: python scripts/prepare_reference.py"
        )

    TARGET.mkdir(parents=True, exist_ok=True)
    total = 0
    for name in REQUIRED:
        shutil.copy2(SOURCE / name, TARGET / name)
        size = (TARGET / name).stat().st_size
        total += size
        print(f"  staged {name:<26} {size / 1_000_000:>6.2f} MB")

    print(f"\n  Total staged: {total / 1_000_000:.2f} MB -> "
          f"{TARGET.relative_to(REPO_ROOT)}")
    # The sample bills. Small, and the demo depends on them.
    fixtures = sorted(FIXTURE_SOURCE.glob("bill_*.json"))
    if not fixtures:
        raise SystemExit(
            "FATAL: no fixtures in " + str(FIXTURE_SOURCE) + "\n"
            "Run: python scripts/make_demo_bills.py"
        )
    FIXTURE_TARGET.mkdir(parents=True, exist_ok=True)
    for stale in FIXTURE_TARGET.glob("bill_*.json"):
        stale.unlink()
    fixture_bytes = 0
    for f in fixtures:
        shutil.copy2(f, FIXTURE_TARGET / f.name)
        fixture_bytes += f.stat().st_size
    print(f"  staged {len(fixtures)} sample bills        "
          f"{fixture_bytes / 1_000:>6.1f} KB -> "
          f"{FIXTURE_TARGET.relative_to(REPO_ROOT)}")

    if BRAND_INDEX_SOURCE.exists():
        kept = reduce_brand_index()
        size = BRAND_INDEX_TARGET.stat().st_size
        print(f"  staged brand_index.csv (reduced) {size / 1_000_000:>6.2f} MB "
              f"-- {kept:,} brands")
    else:
        print("  brand_index.csv NOT FOUND -- brands will not resolve.")
        print("  Run: python scripts/fetch_brand_data.py && "
              "python scripts/build_brand_index.py")
    # --use-container is NOT optional on Windows. A plain `sam build` installs
    # wheels for the machine it runs on, so it would bundle Windows wheels
    # into an arm64 Linux function -- which deploys successfully and then dies
    # at import time on the first request. See AWS_STEPS.md 3.4.
    print("\n  Now run:  sam build --use-container --template infra/template.yaml")
    print("  then:     sam deploy --guided --stack-name billsahi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
