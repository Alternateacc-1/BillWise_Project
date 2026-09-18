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
  brand_index.csv        NO, 36 MB. Too big for a bundle and slow to parse on
                         a cold start. Its absence is handled: resolution
                         falls back to generic names and unresolved items go
                         gray, which is correct behaviour rather than a crash.
                         Phase 4 loads it into DynamoDB if there is time.
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

    print("  brand_index.csv deliberately NOT staged (36 MB). The engine")
    print("  degrades to generic-name resolution without it.")
    # --use-container is NOT optional on Windows. A plain `sam build` installs
    # wheels for the machine it runs on, so it would bundle Windows wheels
    # into an arm64 Linux function -- which deploys successfully and then dies
    # at import time on the first request. See AWS_STEPS.md 3.4.
    print("\n  Now run:  sam build --use-container --template infra/template.yaml")
    print("  then:     sam deploy --guided --stack-name billsahi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
