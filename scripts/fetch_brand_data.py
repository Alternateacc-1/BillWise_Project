"""Download the Indian Medicine Dataset into data/raw/brands/ (gitignored).

Source: https://github.com/junioralive/Indian-Medicine-Dataset  (MIT licence)
~254,000 Indian medicines with name, manufacturer, pack size and composition.

WHAT THIS DATA IS FOR: mapping a brand name on a bill to its salts, strengths
and pack size. That is all.

WHAT IT IS NOT FOR: prices. The `price(Rs)` column is scraped, undated and
stale -- Augmentin 625 Duo's listed price already sits above the March 2026
NPPA ceiling. It is dropped at index-build time and a test proves no field
originating in this file can reach a verdict.

Run:  python scripts/fetch_brand_data.py
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BRANDS_DIR = REPO_ROOT / "data" / "raw" / "brands"
TARGET = BRANDS_DIR / "indian_medicine_data.csv"

SOURCE_URL = (
    "https://raw.githubusercontent.com/junioralive/Indian-Medicine-Dataset"
    "/main/DATA/indian_medicine_data.csv"
)

#: Refuse anything implausible. The real file is ~40 MB; a 2 KB response is a
#: GitHub error page and a 500 MB one is not what we asked for.
MIN_BYTES = 5_000_000
MAX_BYTES = 200_000_000

#: Expected header, checked before we trust a single row.
EXPECTED_HEADER = (
    "id,name,price(₹),Is_discontinued,manufacturer_name,type,"
    "pack_size_label,short_composition1,short_composition2"
)


def download(url: str) -> bytes:
    # Only ever called with SOURCE_URL, but the signature is generic: refuse
    # anything that is not https so a later edit cannot turn this into a
    # file:// read or a custom-scheme handler.
    if not url.startswith("https://"):
        raise SystemExit(f"FATAL: refusing a non-https source: {url}")
    print(f"  Fetching {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "BillWise/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 200:
                raise SystemExit(f"FATAL: HTTP {response.status} from {url}")
            # Read with a hard cap so a redirect to something enormous cannot
            # fill the disk.
            payload = response.read(MAX_BYTES + 1)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"FATAL: could not reach the dataset ({exc}).\n"
            "This script is the only part of the project that needs the "
            "network. Everything else runs offline."
        ) from exc

    if len(payload) > MAX_BYTES:
        raise SystemExit(f"FATAL: response exceeded {MAX_BYTES} bytes; refusing.")
    if len(payload) < MIN_BYTES:
        raise SystemExit(
            f"FATAL: response was only {len(payload)} bytes -- expected at least "
            f"{MIN_BYTES}. This is almost certainly an error page, not the dataset."
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="re-download even if the file is already present",
    )
    args = parser.parse_args()

    BRANDS_DIR.mkdir(parents=True, exist_ok=True)

    if TARGET.exists() and not args.force:
        size = TARGET.stat().st_size
        digest = hashlib.sha256(TARGET.read_bytes()).hexdigest()
        print(f"  Already present: {TARGET.relative_to(REPO_ROOT)}")
        print(f"    {size:,} bytes   sha256 {digest}")
        print("  Use --force to re-download.")
        return 0

    payload = download(SOURCE_URL)

    header = payload.split(b"\n", 1)[0].decode("utf-8-sig").strip()
    if header != EXPECTED_HEADER:
        raise SystemExit(
            "FATAL: the dataset's columns have changed. Do not build an index\n"
            "from it until scripts/build_brand_index.py has been reviewed.\n"
            f"  expected: {EXPECTED_HEADER}\n"
            f"  got:      {header}"
        )

    TARGET.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    print(f"  Wrote {TARGET.relative_to(REPO_ROOT)}")
    print(f"    {len(payload):,} bytes")
    print(f"    sha256 {digest}")
    print()
    print("  Source: junioralive/Indian-Medicine-Dataset (MIT licence)")
    print("  Used for NAME and PACK-SIZE mapping only. Its prices are stale")
    print("  and are never used as a price reference.")
    print()
    print("  This directory is gitignored -- we do not redistribute the data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
