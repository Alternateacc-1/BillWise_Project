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

Run:  python scripts/stage_lambda.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "data" / "reference"
TARGET = REPO_ROOT / "backend" / "reference_data"

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
    print("  brand_index.csv deliberately NOT staged (36 MB). The engine")
    print("  degrades to generic-name resolution without it.")
    print("\n  Now run:  sam build && sam deploy --guided")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
