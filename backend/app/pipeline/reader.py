"""Reading a bill. Fixtures in local mode; Textract and Bedrock when
PROVIDER=aws, where both readers run on every bill.

LOCAL MODE HAS NO OCR, and says so rather than pretending. An uploaded file is
stored and, if its name matches a known fixture, that fixture's reading is
used; otherwise the reader returns NO items and an explicit note. It never
invents a reading for a file it cannot read.

That honesty matters beyond tidiness: every reading-quality number in the eval
today comes from these fixtures, not from OCR, and must be re-measured on the
AWS path before it is quoted anywhere. See docs/LIMITS.md for what may and
may not be claimed.
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import config
from ..models import BillInput, ReaderOutput

REPO_ROOT = Path(__file__).resolve().parents[3]


def _fixture_dir() -> Path:
    """Locate the sample bills in the repo OR in the Lambda bundle.

    Repo layout:   <root>/eval/fixtures/
    Lambda bundle: <task root>/fixtures/, staged by scripts/stage_lambda.py

    CodeUri is backend/, so eval/ is NOT deployed. Resolving only the repo
    path meant FIXTURE_DIR pointed at /var/eval/fixtures on Lambda, glob()
    returned nothing (a missing directory globs empty rather than raising),
    and every sample bill 404'd internally -- surfacing as a 500 on
    POST /bills/sample.
    """
    bundled = Path(__file__).resolve().parents[2] / "fixtures"
    if bundled.is_dir():
        return bundled
    return REPO_ROOT / "eval" / "fixtures"


FIXTURE_DIR = _fixture_dir()

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
    """One sentence for the UI about what the reader can currently do.

    IT DESCRIBES CONFIGURATION, NOT OUTCOME, AND THE DIFFERENCE IS THE POINT.

    This used to read "Reading with Textract and a vision model, then verifying
    both." -- asserted unconditionally, on an endpoint that never calls either
    reader. It can be false for a whole day without anyone noticing: if Bedrock
    returns
    INVALID_PAYMENT_INSTRUMENT (Anthropic models are Marketplace subscriptions
    and credits do not satisfy one), every line came back `only_one_reader_ran`,
    and /health -- the first thing anyone checks -- promised a cross-check that
    was not happening.

    Whether the second reader answers is knowable only per request, so this
    says what is CONFIGURED and points at the per-report field that records
    what actually ran. Never claim a cross-check that did not happen.
    """
    if config.PROVIDER == "aws":
        if config.BEDROCK_INFERENCE_PROFILE_ID:
            return (
                "Reading with Textract, with a vision model as a second "
                "reader. Each report says whether the cross-check actually "
                "ran on that bill."
            )
        return (
            "Reading with Textract only. No second reader is configured, so "
            "nothing cross-checks the reading."
        )
    return (
        "Running offline: there is no OCR in local mode. Use “Try a sample "
        "bill”, or upload one of the files from eval/demo_bills/."
    )
