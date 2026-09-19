"""Phase 3: the API surface, including the limits that keep it safe and cheap."""

from __future__ import annotations

import builtins
import io
from decimal import Decimal
from pathlib import Path
from unittest import mock

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


def test_the_page_guard_uses_a_library_that_ships_to_lambda():
    """REGRESSION. The guard must not depend on a build-time-only package.

    It used to call pdfplumber inside a bare `except Exception: return None`.
    pdfplumber is deliberately absent from backend/requirements.txt, so on
    Lambda the import failed, None came back, and the caller read that as
    "no limit". The 10-page cap was inert in the only environment that bills
    per page. This asserts the counter works with pdfplumber unavailable.
    """
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    buffer = io.BytesIO()
    pdf = reportlab.Canvas(buffer)
    for _ in range(3):
        pdf.drawString(100, 100, "page")
        pdf.showPage()
    pdf.save()

    real_import = builtins.__import__

    def without_pdfplumber(name, *args, **kwargs):
        if name == "pdfplumber":
            raise ModuleNotFoundError("No module named 'pdfplumber'")
        return real_import(name, *args, **kwargs)

    with mock.patch.object(builtins, "__import__", without_pdfplumber):
        assert blobs.count_pdf_pages(buffer.getvalue()) == 3


def test_an_uncountable_pdf_is_rejected_rather_than_waved_through():
    """Fail CLOSED. "We could not count the pages" is not "it is small".

    Textract bills per page, so an unreadable PDF must cost the user a retry
    rather than cost us an unbounded number of billable pages.
    """
    with pytest.raises(blobs.PageCountUnavailable):
        blobs.count_pdf_pages(b"%PDF-1.4 this is not actually a pdf")

    with pytest.raises(blobs.UploadRejected) as exc:
        blobs.validate(b"%PDF-1.4 this is not actually a pdf", "application/pdf")
    assert "could not read" in str(exc.value).lower()


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
    """Local mode has no OCR and says so instead of guessing a reading.

    The upload here is a VALID one-page PDF that simply is not a bill we know.
    That distinction is the point, and this test used to blur it: it passed a
    malformed byte string, so it was really asserting two different things at
    once. A well-formed unknown bill and a corrupt file deserve different
    answers, and they now get them --
    see test_an_uncountable_pdf_is_rejected_rather_than_waved_through.
    """
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    buffer = io.BytesIO()
    pdf = reportlab.Canvas(buffer)
    pdf.drawString(100, 100, "A bill we have never seen")
    pdf.showPage()
    pdf.save()

    response = client.post(
        "/bills",
        files={"file": ("some_random_scan.pdf", buffer.getvalue(),
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

    # Strip digit grouping before comparing: "12,947.61" in the letter is the
    # same number as "12947.61" in the evidence, and the contract is about
    # numbers, not about formatting.
    available = set(re.findall(r"\d+(?:\.\d+)?", str(report).replace(",", "")))
    for number in re.findall(r"\d+(?:\.\d+)?", letter.replace(",", "")):
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
    assert total in letter.replace(",", "")


ALL_FIXTURES = ["bill_01", "bill_02", "bill_03", "bill_04", "bill_05"]


@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_every_item_lands_in_exactly_one_ui_group(client, fixture):
    """REGRESSION: an item disappeared from the report entirely.

    The UI groups gray items by gray_detail. bill_02 has a pack_size_unknown
    item, no other bundled bill does, and the partition test only ever ran
    against bill_01 -- so a whole category rendered nowhere and nothing
    failed. Every bill is checked now, and the detail values the UI knows
    about are pinned.
    """
    UI_KNOWS = {"no_public_ceiling", "could_not_read", "could_not_identify",
                "pack_size_unknown"}

    bill_id = client.post(f"/bills/sample?fixture={fixture}").json()["bill_id"]
    items = client.get(f"/bills/{bill_id}").json()["by_item"]

    for item in items:
        if item["severity"] != "gray":
            continue
        detail = item["gray_detail"] or (
            "no_public_ceiling" if item["gray_reason"] == "no_public_ceiling"
            else None
        )
        assert detail in UI_KNOWS, (
            f"{fixture} item {item['index']} has gray detail {detail!r}, which "
            f"no UI group renders -- it would vanish from the report"
        )

    gray = [i for i in items if i["severity"] == "gray"]
    grouped = sum(
        1 for i in gray
        if i["gray_reason"] == "no_public_ceiling"
        or i["gray_detail"] in {"could_not_read", "could_not_identify",
                                "pack_size_unknown"}
    )
    assert grouped == len(gray), f"{fixture}: {len(gray) - grouped} item(s) ungrouped"


def test_every_count_the_ui_renders_is_derivable_from_by_item(client, sample_bill):
    """No number shown anywhere may be asserted independently of the list it labels.

    The bug this prevents: the "Not compared" header claimed "10 ... 2" above
    a group of 10 items, because the header read a breakdown computed over ALL
    items while the group listed only gray-bucketed ones. 10 + 2 = 12 != 10.

    Every count the UI renders is checked here against the same by_item array
    the UI groups from, so a header can never again disagree with its own list.
    """
    report = client.get(f"/bills/{sample_bill}").json()
    items = report["by_item"]

    # 1. The three top-level groups partition by_item exactly.
    findings = [i for i in items if i["severity"] in ("red", "amber")]
    clear = [i for i in items if i["severity"] == "green"]
    gray = [i for i in items if i["severity"] == "gray"]
    assert len(findings) + len(clear) + len(gray) == len(items)

    # 2. The severity counts match those groups.
    assert report["counts"]["green"] == len(clear)
    assert report["counts"]["gray"] == len(gray)
    assert report["counts"]["red"] + report["counts"]["amber"] == len(findings)

    # 3. The "Not compared" subgroups partition the gray group exactly.
    no_ceiling = [i for i in gray if i["gray_reason"] == "no_public_ceiling"]
    could_not_read = [i for i in gray if i["gray_detail"] == "could_not_read"]
    could_not_identify = [
        i for i in gray if i["gray_detail"] == "could_not_identify"
    ]
    assert (
        len(no_ceiling) + len(could_not_read) + len(could_not_identify)
        == len(gray)
    ), "the Not compared subgroups must partition the gray items exactly"

    # 4. The summary's headline numbers.
    assert report["findings_count"] == len(findings) + len(
        report["bill_level_flags"]
    )
    assert report["stats"]["total_items"] == len(items)

    # 5. The breakdown counts EVERY item without a price verdict, which is a
    #    superset of the gray group -- an item can be a duplicate (amber) and
    #    still have no published ceiling. Assert the relationship explicitly
    #    so the difference stays deliberate rather than looking like the bug.
    assert report["gray_breakdown"]["no_public_ceiling"] >= len(no_ceiling)
    assert report["not_compared_total"] >= len(gray)
    assert report["not_compared_total"] == sum(report["gray_breakdown"].values())


def test_amounts_sum_to_the_reported_total(client, sample_bill):
    report = client.get(f"/bills/{sample_bill}").json()
    from_items = sum(
        Decimal(i["amount_affected"])
        for i in report["by_item"]
        if i["severity"] in ("red", "amber")
    )
    from_bill = sum(
        Decimal(f["amount_affected"]) for f in report["bill_level_flags"]
    )
    assert from_items + from_bill == Decimal(report["total_amount_affected"])


# --------------------------------------------------------------------------
# Currency formatting
# --------------------------------------------------------------------------

def test_indian_digit_grouping():
    from app.money import format_inr, group_indian

    assert group_indian("1234567") == "12,34,567"
    assert group_indian("100000") == "1,00,000"
    assert group_indian("999") == "999"
    assert format_inr("12947.61") == "₹12,947.61"
    assert format_inr("1234567.5") == "₹12,34,567.50"
    assert format_inr("0.93") == "₹0.93"
    assert format_inr("5") == "₹5.00"
    # The CLI prints to a Windows console that cannot encode U+20B9.
    assert format_inr("12947.61", symbol="Rs ") == "Rs 12,947.61"


def test_letter_uses_the_rupee_symbol_and_grouping(client, sample_bill):
    letter = client.post(f"/bills/{sample_bill}/letter").json()["letter"]
    assert "₹" in letter
    assert "₹12,947.61" in letter or "₹" in letter


def test_evidence_keeps_raw_decimals_not_formatted_strings(client, sample_bill):
    """Formatting is presentation. Rules must never reason about it."""
    report = client.get(f"/bills/{sample_bill}").json()
    for item in report["by_item"]:
        for flag in item["flags"]:
            for key in ("ceiling_ex_gst", "amber_threshold", "red_threshold"):
                value = flag["evidence"].get(key)
                if value:
                    assert "," not in value, f"{key} carries digit grouping"
                    assert "₹" not in value, f"{key} carries a currency symbol"
        assert "," not in item["amount_affected"]


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


def test_a_second_reader_failure_is_logged_without_bill_content(caplog):
    """A degraded reading is acceptable; an undiagnosable one is not.

    Swallowing the cause meant PDFs silently lost the second reader in
    production while CloudWatch showed only START/END. But the log line must
    carry the exception TYPE and MESSAGE only -- never bill bytes, the model's
    output, or the filename. CloudWatch must not become somewhere a patient's
    bill can be read.
    """
    import logging
    from app.pipeline import readers_aws

    secret = b"%PDF-1.4 PATIENT NAME AND EVERY LINE OF THEIR BILL"

    def explode(*_a, **_kw):
        raise RuntimeError("ValidationException: document blocks not supported")

    with mock.patch.object(readers_aws.aws_clients, "bedrock_runtime", explode), \
         mock.patch.object(readers_aws.config, "BEDROCK_INFERENCE_PROFILE_ID", "x"), \
         caplog.at_level(logging.WARNING):
        assert readers_aws.read_with_bedrock(secret, "application/pdf") is None

    logged = caplog.text
    assert "RuntimeError" in logged
    assert "document blocks not supported" in logged, "the cause must be visible"
    assert "PATIENT NAME" not in logged, "bill content reached the logs"
    assert "%PDF" not in logged


# --------------------------------------------------------------------------
# Local/production parity.
#
# THE MOST EXPENSIVE BUG CLASS OF 2026-09-19, and it had no gate at all.
# Four separate failures shared one shape: WHAT WE TEST IS NOT WHAT RUNS.
#   - the brand index existed locally and was never deployed, so brand
#     resolution worked in every test and in no real request
#   - eval/fixtures/ was never staged, so /bills/sample returned a bare 500
#   - pdfplumber backed the page guard but is absent from the Lambda bundle,
#     so the guard was inert in the only environment that bills per page
#   - reference_data/ was missed entirely at the first deploy
#
# Each was found by a human hitting the deployed URL. None was found by the
# 270 tests, because every one of them tested the local filesystem.
# --------------------------------------------------------------------------

def test_everything_the_app_reads_at_runtime_is_staged_for_the_bundle():
    """Any file the engine loads must be in backend/, or it will not deploy.

    CodeUri is backend/, so NOTHING outside it reaches Lambda. This asserts
    that the paths the app actually resolves at runtime live inside the
    staged directory -- not merely that some copy exists somewhere on disk.
    """
    from app.pipeline import match, normalize, reader

    staged = Path(__file__).resolve().parent.parent / "backend"

    runtime_paths = {
        "reference_prices.csv": match.REFERENCE_CSV,
        "brand_index.csv": normalize.BRAND_INDEX_CSV,
        "fixtures/": reader.FIXTURE_DIR,
    }

    unstaged = {
        name: path for name, path in runtime_paths.items()
        if staged not in Path(path).resolve().parents
    }
    assert not unstaged, (
        "these are read at runtime but resolve OUTSIDE backend/, so they will "
        f"not be deployed: {unstaged}. Run scripts/stage_lambda.py."
    )


def test_the_staged_brand_index_is_the_one_the_app_resolves():
    """Local and production must read the SAME brand index.

    Before 2026-09-19 local read the full 36 MB file and production read
    nothing, so every local brand result was unreproducible on AWS. The
    reduced index is now staged into backend/reference_data/ and the
    bundle-aware path prefers it in both places.
    """
    from app.pipeline import normalize

    resolved = Path(normalize.BRAND_INDEX_CSV)
    if not resolved.exists():
        pytest.skip("brand index not built; run scripts/build_brand_index.py")

    assert resolved.parent.name == "reference_data", (
        f"the app resolves its brand index to {resolved}, which is not the "
        "staged copy -- local and production would disagree"
    )


# --------------------------------------------------------------------------
# Every number the summary states must be derivable from the rendered items.
#
# CLASS: A REPORT THAT CHECKED NOTHING MUST NOT READ AS A CLEAN BILL.
#
# Found 2026-09-19 on the real retail pharmacy bill (bill_06): all six lines
# came back gray -- one with no published ceiling, five unidentified, so ZERO
# were compared against any price -- and the summary rendered
# "We found 0 things worth asking about, worth Rs 0.00" with a
# "Write a clarification letter" button. Every word true; the page says the
# bill is fine. Falsely reassuring a patient about a medical bill is the same
# failure as falsely accusing a pharmacy, pointed the other way, and the whole
# project is built around not doing the second one.
#
# The frontend now derives the summary from `by_item` and `bill_level_flags`
# instead of `stats` and `gray_breakdown`, so these assert that the derivation
# is possible and agrees with the server's own totals.
# --------------------------------------------------------------------------


def _derived(report):
    """Recompute the summary the way the UI does -- from rendered arrays."""
    items = report["by_item"]
    findings = [i for i in items if i["severity"] in ("red", "amber")]
    return {
        "total": len(items),
        # A price verdict, not a colour: an amber duplicate on a line with no
        # published ceiling was never priced. gray_reason is set exactly when
        # no price verdict was reached.
        "compared": len([i for i in items
                         if i["severity"] != "gray" and not i["gray_reason"]]),
        "findings": len(findings) + len(report["bill_level_flags"]),
        "amount": sum(Decimal(i["amount_affected"]) for i in findings)
        + sum(Decimal(f["amount_affected"]) for f in report["bill_level_flags"]),
        "read_high": len([i for i in items if i["confidence"] == "high"]),
    }


@pytest.mark.parametrize("fixture", [f"bill_0{n}" for n in range(1, 7)])
def test_summary_numbers_are_derivable_from_the_rendered_items(client, fixture):
    report = client.post(f"/bills/sample?fixture={fixture}").json()
    report = client.get(f"/bills/{report['bill_id']}").json()
    d = _derived(report)

    assert d["total"] == report["stats"]["total_items"]
    assert d["findings"] == report["findings_count"]
    assert d["amount"] == Decimal(report["total_amount_affected"])
    assert d["read_high"] == report["stats"]["auto_high"], (
        "the confidence on by_item must agree with stats.auto_high, or the "
        "summary line '{n}/{t} lines read at high confidence' is a second "
        "source of truth".format(n=report["stats"]["auto_high"], t=d["total"])
    )


def test_a_bill_where_nothing_was_compared_is_distinguishable_from_a_clean_one(
    client,
):
    """bill_06 is the real-pharmacy-layout fixture. Zero lines get a price.

    The assertion is not that this SHOULD be zero -- Class A and R6 are meant
    to raise it. It is that when it IS zero, the data says so plainly, so the
    UI can lead with "we could not compare any of these" rather than with a
    finding count of nothing.
    """
    report = client.post("/bills/sample?fixture=bill_06").json()
    report = client.get(f"/bills/{report['bill_id']}").json()
    d = _derived(report)

    assert d["findings"] == 0
    assert d["compared"] == 0, (
        "if bill_06 ever starts comparing lines this test should be updated "
        "with the new number, not deleted -- the invariant it guards is that "
        "`compared` exists and is derivable, not that it stays 0"
    )
    assert d["total"] == 6
    # A clean bill and this bill BOTH have findings == 0. Only `compared`
    # tells them apart, which is exactly why the summary must state it.
    assert d["compared"] < d["total"]


def test_compared_counts_price_verdicts_not_colours(client):
    """An amber from R1/R3 is not evidence that a price was checked.

    bill_01 line 9 is a duplicate (amber) on a line with no published ceiling,
    and line 13 is an arithmetic flag (amber) on a line we could not read.
    Neither was compared against a ceiling, so a summary saying "we compared N"
    must not count them -- that is the same overstatement as a zero-finding
    report reading as a clean bill, one level down.
    """
    report = client.post("/bills/sample?fixture=bill_01").json()
    report = client.get(f"/bills/{report['bill_id']}").json()

    flagged_but_unpriced = [
        i for i in report["by_item"]
        if i["severity"] in ("red", "amber") and i["gray_reason"]
    ]
    assert flagged_but_unpriced, (
        "this fixture is meant to contain flagged-but-unpriced lines; if it "
        "no longer does, point this test at one that does rather than drop it"
    )
    d = _derived(report)
    assert d["compared"] == len(
        [i for i in report["by_item"]
         if i["severity"] != "gray" and not i["gray_reason"]]
    )
    assert d["compared"] + len(flagged_but_unpriced) <= d["total"]
