"""Phase 3: the API surface, including the limits that keep it safe and cheap."""

from __future__ import annotations

import io
from decimal import Decimal
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
# One item, one headline verdict
# --------------------------------------------------------------------------

def test_an_item_never_has_more_than_one_headline(client, sample_bill):
    """An item can carry several flags but renders exactly one verdict.

    Items 9 and 13 were each showing two cards -- an amber finding AND a
    separate gray "not compared" block -- which reads as the system
    contradicting itself. Worst severity wins; everything else is a note.
    """
    report = client.get(f"/bills/{sample_bill}").json()
    for item in report["by_item"]:
        headlines = [item["headline"]] if item["headline"] else []
        assert len(headlines) == 1, f"item {item['index']} has no single headline"
        assert item["headline"]["severity"] == item["severity"]
        # Every other flag is subordinate, and none of them is a headline.
        assert all(n["rule_id"] != item["headline"]["rule_id"] or
                   n is not item["headline"] for n in item["notes"])
        assert len(item["notes"]) == len(item["flags"]) - 1


def test_a_multi_flag_item_keeps_its_gray_note_as_a_note(client, sample_bill):
    """Nothing is hidden -- the gray note is subordinate, not deleted."""
    report = client.get(f"/bills/{sample_bill}").json()
    multi = [i for i in report["by_item"] if len(i["flags"]) > 1]
    assert multi, "the sample bill should have an item with several flags"
    for item in multi:
        assert item["severity"] in ("red", "amber")
        assert any(n["rule_id"] == "R9" for n in item["notes"])


def test_gray_counts_match_what_the_cards_show(client, sample_bill):
    """The summary said 0 while a card said the opposite. Never again."""
    report = client.get(f"/bills/{sample_bill}").json()
    breakdown = report["gray_breakdown"]

    assert report["not_compared_total"] == sum(breakdown.values())
    assert report["not_compared_total"] == sum(
        1 for i in report["by_item"] if i["gray_reason"]
    )
    assert breakdown["could_not_read"] == sum(
        1 for i in report["by_item"] if i["gray_detail"] == "could_not_read"
    )
    assert breakdown["could_not_identify"] == sum(
        1 for i in report["by_item"] if i["gray_detail"] == "could_not_identify"
    )


def test_reading_and_identification_failures_are_worded_differently(client):
    from app.models import GrayDetail
    from app.pipeline.explain import explain
    from app.models import Flag, GrayReason, Severity

    unread = Flag(rule_id="R9", severity=Severity.GRAY, item_index=1,
                  gray_reason=GrayReason.COULD_NOT_VERIFY,
                  gray_detail=GrayDetail.COULD_NOT_READ)
    unknown = Flag(rule_id="R9", severity=Severity.GRAY, item_index=2,
                   gray_reason=GrayReason.COULD_NOT_VERIFY,
                   gray_detail=GrayDetail.COULD_NOT_IDENTIFY)

    assert explain(unread) != explain(unknown)
    assert "read this line reliably" in explain(unread)
    assert "could not identify which medicine" in explain(unknown)


def test_findings_count_matches_the_actionable_items(client, sample_bill):
    report = client.get(f"/bills/{sample_bill}").json()
    actionable = [
        i for i in report["by_item"] if i["severity"] in ("red", "amber")
    ]
    assert report["findings_count"] == len(actionable) + len(
        report["bill_level_flags"]
    )


def test_total_amount_affected_is_present_and_matches_the_letter(
    client, sample_bill
):
    """Bug: this rendered as "Rs " with no number."""
    report = client.get(f"/bills/{sample_bill}").json()
    total = report["total_amount_affected"]
    assert total
    assert Decimal(total) > 0

    letter = client.post(f"/bills/{sample_bill}/letter").json()["letter"]
    assert total in letter


# --------------------------------------------------------------------------
# Letter hygiene
# --------------------------------------------------------------------------

def test_letter_never_leaks_the_internal_bill_id(client, sample_bill):
    """The id is a random token. In a letter it reads as a system leak."""
    letter = client.post(f"/bills/{sample_bill}/letter").json()["letter"]
    assert sample_bill not in letter


def test_letter_attributes_nppa_exactly_once(client, sample_bill):
    letter = client.post(f"/bills/{sample_bill}/letter").json()["letter"]
    assert letter.count("NPPA data retrieved") == 1


def test_a_unit_quantity_of_one_is_not_printed(client, sample_bill):
    """"per tablet", not "per 1 tablet"."""
    from app.pipeline.audit import format_unit

    assert format_unit(Decimal("1"), "tablet") == "tablet"
    assert format_unit(Decimal("1"), "unit") == "unit"
    assert format_unit(Decimal("500"), "ml") == "500 ml"
    assert format_unit(Decimal("0.5"), "ml") == "0.5 ml"

    letter = client.post(f"/bills/{sample_bill}/letter").json()["letter"]
    assert "per 1 " not in letter

    report = client.get(f"/bills/{sample_bill}").json()
    for item in report["by_item"]:
        for flag in item["flags"]:
            unit = flag["evidence"].get("ceiling_unit")
            if unit:
                assert not unit.startswith("1 "), unit


# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------

def test_cors_is_not_a_wildcard():
    """The API returns a user's uploaded bill; "*" would be wrong."""
    from app.main import ALLOWED_ORIGINS

    assert "*" not in ALLOWED_ORIGINS
    assert all(o.startswith("http://localhost") or o.startswith("http://127.")
               for o in ALLOWED_ORIGINS)
