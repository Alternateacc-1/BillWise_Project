"""The API. FastAPI locally, and the same app behind Mangum on Lambda.

Endpoints:
    GET  /health
    POST /bills                  upload a bill
    POST /bills/sample           run the bundled sample
    GET  /bills/{id}             the report
    PUT  /bills/{id}/items       correct the gray items
    POST /bills/{id}/confirm     re-run the audit after corrections
    POST /bills/{id}/letter      the clarification letter
"""

from __future__ import annotations

import secrets
from decimal import Decimal, InvalidOperation

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from . import blobs, config, store
from .models import (
    BillInput,
    BillReport,
    ReadingConfidence,
    Severity,
    VerifiedItem,
)
from .pipeline import reader
from .pipeline.audit import audit
from .pipeline.explain import explain_all
from .pipeline.letter import compose
from .pipeline.match import reference_retrieved_on
from .pipeline.normalize import normalize_bill
from .pipeline.verify import verify_bill

# Interactive docs are useful locally and are an invitation in production:
# this API is public and unauthenticated, and POST /bills spends Textract and
# Bedrock money per call. The endpoints are visible in the frontend anyway, so
# this is a speed bump rather than a control -- the actual control is request
# throttling on the API Gateway stage. Off in AWS, on everywhere else.
_DOCS_OFF = config.PROVIDER == "aws"
app = FastAPI(
    title="BillWise",
    version="0.3.0",
    docs_url=None if _DOCS_OFF else "/docs",
    redoc_url=None if _DOCS_OFF else "/redoc",
    openapi_url=None if _DOCS_OFF else "/openapi.json",
)

#: The local dev origins. In AWS the deployed Amplify origin is APPENDED
#: from FRONTEND_ORIGIN below -- never "*", because this API hands back a
#: user's uploaded bill.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# In AWS the Amplify origin is added from the environment. Still never "*":
# this API hands back a user's uploaded bill.
if config.FRONTEND_ORIGIN:
    ALLOWED_ORIGINS.append(config.FRONTEND_ORIGIN)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)


# --------------------------------------------------------------------------

def _new_bill_id() -> str:
    """Unguessable. Bill ids are the only thing protecting one user's bill
    from another's, since there is no login."""
    return secrets.token_urlsafe(16)


def _run_pipeline(bill: BillInput, corrections: dict | None = None) -> BillReport:
    items, stats = verify_bill(bill)

    if corrections:
        items = _apply_corrections(items, corrections)
        # A corrected line is the user's own reading, and the user is a better
        # reader than either model. Treat it as HIGH so it becomes eligible
        # for a price comparison.
        for item in items:
            if str(item.index) in corrections or item.index in corrections:
                item.confidence = ReadingConfidence.HIGH
                item.reasons = [*item.reasons, "corrected_by_user"]
        stats.auto_high = sum(1 for i in items if i.is_high)
        stats.still_unverified = sum(1 for i in items if not i.is_high)

    normalized = normalize_bill(items)
    flags = explain_all(audit(items, normalized, stats))

    return BillReport(
        bill_id=bill.bill_id,
        hospital_name=bill.hospital_name,
        bill_date=bill.bill_date,
        items=items,
        normalized=normalized,
        flags=flags,
        stats=stats,
        reference_retrieved_on=reference_retrieved_on(),
    )


def _apply_corrections(
    items: list[VerifiedItem], corrections: dict
) -> list[VerifiedItem]:
    by_index = {str(i.index): i for i in items}
    for raw_index, fields in corrections.items():
        item = by_index.get(str(raw_index))
        if item is None:
            continue
        for field in ("name", "quantity", "unit_price", "line_total"):
            if field not in fields or fields[field] in (None, ""):
                continue
            value = fields[field]
            if field == "name":
                item.name = str(value)[:200]
            else:
                try:
                    setattr(item, field, Decimal(str(value)))
                except (InvalidOperation, ValueError):
                    # A correction we cannot parse is ignored, not guessed at.
                    continue
    return items


def _store(report: BillReport, status: str, source: dict) -> None:
    store.put(report.bill_id, status, {
        "report": report.model_dump(mode="json"),
        "source": source,
    })


def _load(bill_id: str) -> tuple[BillReport, dict]:
    record = store.get(bill_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such bill.")
    return BillReport.model_validate(record["report"]), record.get("source", {})


# --------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "provider": config.PROVIDER,
        "reference_retrieved_on": reference_retrieved_on(),
        "reader": reader.reader_note(),
    }


@app.post("/bills/sample")
def create_sample(fixture: str | None = None) -> dict:
    """Run a bundled sample bill.

    `fixture` picks which one. It is validated against the known fixture
    names, never used as a path, so it cannot be steered at the filesystem.
    """
    if fixture:
        try:
            bill = reader.load_fixture(fixture)
        except reader.ReaderUnavailable as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    else:
        # read_sample() raises the same ReaderUnavailable as load_fixture().
        # Leaving it unwrapped turned a missing fixture directory into a bare
        # 500 with no message -- exactly what the first deployed smoke test
        # hit. A sample bill that cannot be found is a 404 with a reason.
        try:
            bill = reader.read_sample()
        except reader.ReaderUnavailable as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    chosen = fixture or reader.SAMPLE_BILL_ID
    bill.bill_id = _new_bill_id()
    report = _run_pipeline(bill)
    _store(report, "ready", {"kind": "sample", "fixture": chosen})
    return {"bill_id": report.bill_id, "status": "ready"}


@app.post("/bills")
async def create_bill(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    try:
        suffix = blobs.validate(content, file.content_type or "")
    except blobs.UploadRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    bill_id = _new_bill_id()
    key = blobs.put(bill_id, content, suffix)

    try:
        bill = reader.read_upload(bill_id, file.filename or "", key)
    except reader.ReaderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    report = _run_pipeline(bill)
    _store(report, "ready", {"kind": "upload", "blob_key": key,
                             "filename": file.filename})

    return {
        "bill_id": bill_id,
        "status": "ready",
        "items_read": len(report.items),
        "note": reader.reader_note() if not report.items else "",
    }


@app.get("/bills/{bill_id}")
def get_bill(bill_id: str) -> dict:
    report, _ = _load(bill_id)
    return _serialise(report)


class ItemCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    line_total: str | None = None


class CorrectionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    corrections: dict[str, ItemCorrection] = Field(default_factory=dict)


@app.put("/bills/{bill_id}/items")
def update_items(bill_id: str, body: CorrectionsIn) -> dict:
    _report, source = _load(bill_id)
    record = store.get(bill_id) or {}
    corrections = {
        k: v.model_dump(exclude_none=True) for k, v in body.corrections.items()
    }
    record_source = dict(source)
    record_source["corrections"] = corrections
    store.put(bill_id, "reviewing", {
        "report": record["report"], "source": record_source,
    })
    return {"bill_id": bill_id, "status": "reviewing",
            "corrections": len(corrections)}


@app.post("/bills/{bill_id}/confirm")
def confirm(bill_id: str) -> dict:
    _report, source = _load(bill_id)

    if source.get("kind") == "sample":
        bill = reader.load_fixture(source.get("fixture", reader.SAMPLE_BILL_ID))
    else:
        bill = reader.read_upload(
            bill_id, source.get("filename", ""), source.get("blob_key", "")
        )
    bill.bill_id = bill_id

    report = _run_pipeline(bill, corrections=source.get("corrections"))
    _store(report, "done", source)
    return _serialise(report)


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    email: str | None = Field(default=None, max_length=254)


@app.post("/feedback")
def feedback(body: FeedbackIn) -> dict:
    """Store a note from the user. Reuses the bill store; it is one JSON table.

    NOTHING HERE IS LOGGED. The message is free text a user typed and the
    email identifies them, so both are PII: they go to the store and nowhere
    else. CloudWatch must not become a place where either can be read, which
    is the same rule the readers follow for bill content.

    No email is sent, and the UI does not claim one is -- it says the note was
    received, which is all that happens.
    """
    fid = "fb_" + _new_bill_id()
    store.put(fid, "feedback", {
        "message": body.message.strip(),
        "email": (body.email or "").strip() or None,
    })
    return {"ok": True}


@app.post("/bills/{bill_id}/letter")
def letter(bill_id: str) -> dict:
    report, _ = _load(bill_id)
    return {"bill_id": bill_id, "letter": compose(report)}


# --------------------------------------------------------------------------

def _serialise(report: BillReport) -> dict:
    """The report, shaped for the UI.

    Gray items are listed separately because they are the only ones the
    review screen offers to correct -- and because the two gray reasons mean
    opposite things and are counted apart.
    """
    payload = report.model_dump(mode="json")

    by_item = []
    for item in report.items:
        flags = report.flags_for(item.index)
        severity = report.severity_of(item.index)

        # ONE item, ONE headline verdict. An item that is both a duplicate
        # (amber) and unpriceable (gray) is an amber item with a note -- not
        # two cards contradicting each other. The gray note still travels, in
        # `notes`, so nothing is hidden; it just stops competing for the
        # headline. Enforced by test_an_item_never_has_more_than_one_headline.
        headline = next((f for f in flags if f.severity is severity), None)
        notes = [f for f in flags if f is not headline]

        gray_flag = next((f for f in flags if f.gray_reason), None)
        by_item.append({
            "index": item.index,
            "name": item.name,
            "quantity": str(item.quantity) if item.quantity is not None else None,
            "unit_price": str(item.unit_price) if item.unit_price is not None else None,
            "line_total": str(item.line_total) if item.line_total is not None else None,
            "page": item.page,
            "confidence": item.confidence.value,
            "severity": severity.value,
            "gray_reason": gray_flag.gray_reason.value if gray_flag else None,
            "gray_detail": (
                gray_flag.gray_detail.value
                if gray_flag and gray_flag.gray_detail else None
            ),
            "amount_affected": str(headline.amount_affected) if headline else "0",
            "headline": headline.model_dump(mode="json") if headline else None,
            "notes": [f.model_dump(mode="json") for f in notes],
            "flags": [f.model_dump(mode="json") for f in flags],
        })

    counts = {s.value: 0 for s in Severity}
    for entry in by_item:
        counts[entry["severity"]] += 1

    payload["by_item"] = by_item
    payload["counts"] = counts
    payload["bill_level_flags"] = [
        f.model_dump(mode="json") for f in report.flags_for(-1)
    ]
    # The letter quotes a total across every point it raises. Computing it
    # there and nowhere else would mean the letter cited a number the user
    # could not find in the report -- so it lives here, and the letter reads
    # it rather than inventing it. Enforced by
    # test_letter_introduces_no_number_absent_from_the_report.
    payload["total_amount_affected"] = str(
        sum(
            (f.amount_affected for f in report.flags
             if f.severity in (Severity.RED, Severity.AMBER)),
            Decimal("0"),
        )
    )
    # The breakdown counts every item WITHOUT a price verdict, regardless of
    # which bucket its headline landed in. An item can have no published
    # ceiling AND be a duplicate: it belongs in "what we found" because the
    # duplicate is actionable, and it still counts toward "10 of 16 charges
    # have no published ceiling", because that is simply true.
    #
    # Counting only gray-BUCKETED items is what made the summary say
    # "0 could not be confidently identified" while a card said exactly that.
    not_compared = [e for e in by_item if e["gray_reason"]]
    payload["not_compared_total"] = len(not_compared)
    payload["gray_breakdown"] = {
        "no_public_ceiling": sum(
            1 for e in not_compared if e["gray_reason"] == "no_public_ceiling"
        ),
        "could_not_read": sum(
            1 for e in not_compared if e["gray_detail"] == "could_not_read"
        ),
        "could_not_identify": sum(
            1 for e in not_compared if e["gray_detail"] == "could_not_identify"
        ),
    }

    findings = [e for e in by_item if e["severity"] in ("red", "amber")]
    payload["findings_count"] = len(findings) + len(report.flags_for(-1))
    return payload


# --------------------------------------------------------------------------
# Lambda entry point. Mangum is imported lazily so a local run never needs it
# loaded, and so an import error here cannot break the dev server.
# --------------------------------------------------------------------------

def _make_handler():
    from mangum import Mangum

    return Mangum(app, lifespan="off")


handler = _make_handler()
