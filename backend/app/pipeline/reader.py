"""Reading a bill. Fixtures in local mode; Textract and Bedrock in Phase 4.

LOCAL MODE HAS NO OCR, and says so rather than pretending. An uploaded file is
stored and, if its name matches a known fixture, that fixture's reading is
used; otherwise the reader returns NO items and an explicit note. It never
invents a reading for a file it cannot read.

That honesty matters beyond tidiness: every reading-quality number in the eval
today comes from these fixtures, not from OCR, and must be re-measured on the
AWS path before it is quoted anywhere. See NOTES.md, "Which numbers are ours
to claim".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .. import config
from ..models import BillInput, ReaderOutput

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "eval" / "fixtures"

SAMPLE_BILL_ID = "bill_01"

_FIXTURE_NAME = re.compile(r"(bill_\d{2})")


class ReaderUnavailable(Exception):
    """Raised with a message safe to show the user."""


def available_fixtures() -> list[str]:
    return sorted(p.stem for p in FIXTURE_DIR.glob("bill_*.json"))


def load_fixture(name: str) -> BillInput:
    """Load a fixture by bare name. The name is validated, never a path."""
    if name not in available_fixtures():
        raise ReaderUnavailable(f"No such sample bill: {name}")
    return BillInput.model_validate_json(
        (FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8")
    )


def read_sample() -> BillInput:
    return load_fixture(SAMPLE_BILL_ID)


def read_upload(bill_id: str, original_filename: str, blob_key: str) -> BillInput:
    """Produce a reading for an uploaded file.

    In local mode this only works for files named after a known fixture --
    which is how the demo bills in eval/demo_bills/ are named. Anything else
    comes back with zero items and an explanation, because the alternative is
    inventing a reading, and this project does not do that.
    """
    if config.PROVIDER == "aws":
        return _read_upload_aws(bill_id, original_filename, blob_key)

    match = _FIXTURE_NAME.search(original_filename or "")
    if match and match.group(1) in available_fixtures():
        fixture = load_fixture(match.group(1))
        fixture.bill_id = bill_id
        return fixture

    return BillInput(
        bill_id=bill_id,
        hospital_name="",
        bill_date="",
        reader_a=ReaderOutput(source="local_no_ocr", items=[]),
    )


def _read_upload_aws(bill_id: str, original_filename: str, blob_key: str) -> BillInput:
    """Two independent readings of the same file.

    Textract is reader A. A Claude vision model is reader B, and is optional:
    if it is unavailable the bill still gets read, and verify.py simply
    applies the stricter single-reader bar of >= 95 confidence.
    """
    from .. import blobs
    from . import readers_aws

    content = blobs.get(blob_key)
    if content is None:
        raise ReaderUnavailable("The uploaded file could not be retrieved.")

    reader_a = readers_aws.read_with_textract(content)
    reader_b = readers_aws.read_with_bedrock(
        content, blobs.content_type_for(blob_key)
    )

    return BillInput(
        bill_id=bill_id,
        hospital_name="",
        bill_date="",
        reader_a=reader_a,
        reader_b=reader_b,
    )


def reader_note() -> str:
    """One sentence for the UI about what the reader can currently do."""
    if config.PROVIDER == "aws":
        return "Reading with Textract and a vision model, then verifying both."
    return (
        "Running offline: there is no OCR in local mode. Use “Try a sample "
        "bill”, or upload one of the files from eval/demo_bills/."
    )
