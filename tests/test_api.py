"""Phase 3: the API surface, including the limits that keep it safe and cheap."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import blobs
from app.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_BILLS = REPO_ROOT / "eval" / "demo_bills"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture
def sample_bill(client) -> str:
    return client.post("/bills/sample").json()["bill_id"]


# --------------------------------------------------------------------------
# Basics
# --------------------------------------------------------------------------

def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["provider"] == "local"
    assert body["reference_retrieved_on"]


def test_sample_bill_produces_a_full_report(client, sample_bill):
    report = client.get(f"/bills/{sample_bill}").json()
    assert report["counts"]["red"] > 0
    assert report["counts"]["green"] > 0
    assert report["counts"]["gray"] > 0
    assert report["gray_breakdown"]["no_public_ceiling"] > 0
    assert report["reference_retrieved_on"]
    assert len(report["by_item"]) == 16


def test_unknown_bill_is_404(client):
    assert client.get("/bills/does-not-exist").status_code == 404


def test_bill_ids_are_unguessable(client):
    """No login, so the id is the only thing separating one bill from another."""
    ids = {client.post("/bills/sample").json()["bill_id"] for _ in range(5)}
    assert len(ids) == 5
    for bill_id in ids:
        assert len(bill_id) >= 20
        assert not bill_id.isdigit()


# --------------------------------------------------------------------------
# Upload limits -- enforced BEFORE anything billable runs
# --------------------------------------------------------------------------

def test_rejects_an_unsupported_content_type(client):
    response = client.post(
        "/bills",
        files={"file": ("bill.exe", b"MZ\x00\x00", "application/x-msdownload")},
    )
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_rejects_an_oversized_upload(client):
    payload = b"%PDF-1.4\n" + b"0" * (blobs.MAX_UPLOAD_BYTES + 1)
    response = client.post(
        "/bills", files={"file": ("big.pdf", payload, "application/pdf")}
    )
    assert response.status_code == 400
    assert "MB" in response.json()["detail"]


def test_rejects_an_empty_upload(client):
    response = client.post(
        "/bills", files={"file": ("empty.pdf", b"", "application/pdf")}
    )
    assert response.status_code == 400


def test_page_limit_is_checked_before_any_billable_call():
    """Textract is priced per page. An 11-page PDF must never reach it."""
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    buffer = io.BytesIO()
    pdf = reportlab.Canvas(buffer)
    for _ in range(blobs.MAX_PAGES + 2):
        pdf.drawString(100, 100, "page")
        pdf.showPage()
    pdf.save()

    with pytest.raises(blobs.UploadRejected) as exc:
        blobs.validate(buffer.getvalue(), "application/pdf")
    assert "pages" in str(exc.value)


def test_a_client_filename_cannot_steer_the_stored_path():
    """The stored name comes from the server-generated id, never the client."""
    key = blobs.put("safe-id-123", b"%PDF-1.4 test", ".pdf")
    assert key == "safe-id-123.pdf"
    assert blobs.path_for("../../../etc/passwd") is None
    assert blobs.path_for(key) is not None


def test_uploading_a_demo_bill_reads_it(client):
    """The demo PDFs are named after their fixtures, so local mode can read them."""
    pdf = DEMO_BILLS / "bill_01.pdf"
    if not pdf.exists():
        pytest.skip("demo bills not generated")
    response = client.post(
        "/bills",
        files={"file": ("bill_01.pdf", pdf.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["items_read"] == 16


def test_an_unreadable_upload_reports_zero_items_rather_than_inventing_any(client):
    """Local mode has no OCR and says so instead of guessing a reading."""
    response = client.post(
        "/bills",
        files={"file": ("some_random_scan.pdf", b"%PDF-1.4\nnot a known bill",
                        "application/pdf")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items_read"] == 0
    assert body["note"]


# --------------------------------------------------------------------------
# Review and confirm
# --------------------------------------------------------------------------

def test_corrections_promote_a_line_and_change_the_report(client, sample_bill):
    before = client.get(f"/bills/{sample_bill}").json()
    unverified = [
        i for i in before["by_item"] if i["gray_reason"] == "could_not_verify"
    ]
    assert unverified, "the sample bill should have something to review"

    target = unverified[0]["index"]
    assert client.put(
        f"/bills/{sample_bill}/items",
        json={"corrections": {str(target): {"name": "Blood Sugar Random"}}},
    ).status_code == 200

    after = client.post(f"/bills/{sample_bill}/confirm").json()
    assert after["stats"]["auto_high"] > before["stats"]["auto_high"]
    corrected = next(i for i in after["by_item"] if i["index"] == target)
    assert corrected["name"] == "Blood Sugar Random"


def test_an_unparseable_correction_is_ignored_not_guessed(client, sample_bill):
    client.put(
        f"/bills/{sample_bill}/items",
        json={"corrections": {"13": {"quantity": "not a number"}}},
    )
    after = client.post(f"/bills/{sample_bill}/confirm").json()
    item = next(i for i in after["by_item"] if i["index"] == 13)
    assert item["quantity"] == "10"


def test_confirm_is_idempotent(client, sample_bill):
    first = client.post(f"/bills/{sample_bill}/confirm").json()
    second = client.post(f"/bills/{sample_bill}/confirm").json()
    assert first["counts"] == second["counts"]


# --------------------------------------------------------------------------
# The letter
# --------------------------------------------------------------------------

def test_letter_cites_sources_and_accuses_nobody(client, sample_bill):
    from app.pipeline.explain import FORBIDDEN_WORDS

    letter = client.post(f"/bills/{sample_bill}/letter").json()["letter"]

    lowered = letter.lower()
    for word in FORBIDDEN_WORDS:
        assert word not in lowered, f"letter contains {word!r}"

    # No legal threats, no demands for money.
    for word in ("court", "legal action", "refund", "penalty", "consumer forum",
                 "compensation", "sue"):
        assert word not in lowered, f"letter contains {word!r}"

    assert "S.O." in letter
    assert "NPPA" in letter
    assert "may need clarification" in lowered or "clarification" in lowered


def test_letter_introduces_no_number_absent_from_the_report(client, sample_bill):
    import re

    report = client.get(f"/bills/{sample_bill}").json()
    letter = client.post(f"/bills/{sample_bill}/letter").json()["letter"]

    available = set(re.findall(r"\d+(?:\.\d+)?", str(report)))
    for number in re.findall(r"\d+(?:\.\d+)?", letter):
        assert number in available, f"letter cites {number!r}, absent from the report"


# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------

def test_cors_is_not_a_wildcard():
    """The API returns a user's uploaded bill; "*" would be wrong."""
    from app.main import ALLOWED_ORIGINS

    assert "*" not in ALLOWED_ORIGINS
    assert all(o.startswith("http://localhost") or o.startswith("http://127.")
               for o in ALLOWED_ORIGINS)
