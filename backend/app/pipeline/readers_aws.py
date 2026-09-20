"""The two AWS readers. Only imported when PROVIDER=aws.

Reader A  Textract AnalyzeExpense -- structured extraction, per-field
          confidence. Field names verified against the AnalyzeExpense API
          reference, not guessed.

Reader B  A Claude vision model through Bedrock Converse, returning strict
          JSON. Reached via a cross-region inference profile whose ID is
          copied from the console into .env.

Neither reader decides anything. They produce two independent readings, and
`verify.py` -- pure Python, no AWS -- decides which lines are trustworthy.
That separation is the whole point: the models read, the code judges.

DEGRADING BY DESIGN: if reader B fails for any reason (model access not yet
granted, a throttle, a malformed response) we return Textract alone rather
than failing the request. verify.py already handles a single reader, and it
demands >= 95 confidence from it. One reader and a higher bar beats an error
page.
"""

from __future__ import annotations

import logging

import json
import re
from decimal import Decimal, InvalidOperation

from .. import aws_clients, config
from ..models import ReaderItem, ReaderOutput

#: Textract's expense field types we care about. Everything else is ignored.
FIELD_ITEM = "ITEM"
FIELD_QUANTITY = "QUANTITY"
FIELD_UNIT_PRICE = "UNIT_PRICE"
FIELD_PRICE = "PRICE"

#: The fields whose confidence decides whether a line is trustworthy: exactly
#: the ones we read a value out of, and nothing else. See the note at the
#: confidence calculation for why this is not simply "every field".
#:
#: THIS WIDENS RATHER THAN NARROWS, which is rare here and worth flagging.
#: Excluding noisy fields RAISES line confidence, so lines that were held gray
#: can now reach HIGH and be priced -- a new path to a red verdict. It is
#: justified because the >= 95 floor is meant to bound the risk of trusting a
#: single reader's NAME AND NUMBERS, and those are precisely these four; a
#: floor that moves with data we throw away is noise, not caution.
CONFIDENCE_FIELDS = frozenset({
    FIELD_ITEM, FIELD_QUANTITY, FIELD_UNIT_PRICE, FIELD_PRICE,
})

#: Summary field types. SUBTOTAL and TAX are read but not yet used -- the
#: bill ledger that consumes them is the next piece of work.
SUMMARY_TOTAL = "TOTAL"
SUMMARY_SUBTOTAL = "SUBTOTAL"
SUMMARY_TAX = "TAX"

_MONEY = re.compile(r"-?[\d,]+(?:\.\d+)?")


def parse_money(text: str | None) -> Decimal | None:
    """Pull a number out of "₹1,440.00", "1440", "Rs. 1,440.00".

    Returns None rather than a guess. A reader that cannot read a number must
    say so -- verify.py treats None as "never agrees with anything".
    """
    if not text:
        return None
    match = _MONEY.search(text.replace("₹", " "))
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


# --------------------------------------------------------------------------
# Reader A -- Textract AnalyzeExpense
# --------------------------------------------------------------------------

def read_with_textract(content: bytes) -> ReaderOutput:
    """Synchronous AnalyzeExpense. Caps at 4 MB / 10 pages, enforced upstream.

    Response shape per the AnalyzeExpense API reference:
      ExpenseDocuments[]
        .LineItemGroups[].LineItems[].LineItemExpenseFields[]
            .Type.Text                 e.g. "ITEM", "QUANTITY", "PRICE"
            .ValueDetection.Text       the value as read
            .ValueDetection.Confidence 0-100
        .SummaryFields[]               same shape; TOTAL, SUBTOTAL, TAX
    """
    response = aws_clients.textract().analyze_expense(Document={"Bytes": content})
    return _parse_expense(response)


def _parse_expense(response: dict) -> ReaderOutput:
    """The pure half: an AnalyzeExpense response in, a reading out.

    Split out from the AWS call so the response SHAPE can be tested without a
    network, a mock client or an AWS bill. It had no tests at all until
    2026-09-20, and a bug in this function -- scoring a line on a field we
    never read -- was deciding on real bills whether a price got compared.
    """
    items: list[ReaderItem] = []
    printed_total: Decimal | None = None
    index = 0

    for document in response.get("ExpenseDocuments", []):
        for group in document.get("LineItemGroups", []):
            for line in group.get("LineItems", []):
                values: dict[str, str] = {}
                confidences: list[float] = []
                page = 1

                for field in line.get("LineItemExpenseFields", []):
                    kind = (field.get("Type") or {}).get("Text", "").upper()
                    detected = field.get("ValueDetection") or {}
                    text = detected.get("Text")
                    if kind and text is not None:
                        values[kind] = text
                    confidence = detected.get("Confidence")
                    # ONLY THE FIELDS WE ACTUALLY READ COUNT TOWARD CONFIDENCE.
                    #
                    # AnalyzeExpense returns more per row than we consume:
                    # EXPENSE_ROW (the entire row as one string), PRODUCT_CODE,
                    # and occasionally untyped fields. EXPENSE_ROW in
                    # particular scores lower than the individual cells,
                    # because it is a longer and messier piece of text.
                    #
                    # The line's score is a MINIMUM, so any one of those drags
                    # the whole row down -- and in single-reader mode a row
                    # under 95 is never trusted, so its price is never
                    # compared. That is a verdict decided by a field we
                    # discard.
                    #
                    # Measured 2026-09-20 on a real invoice: seven lines read
                    # correctly, names and amounts matching the paper, and six
                    # came back below the floor.
                    if confidence is not None and kind in CONFIDENCE_FIELDS:
                        confidences.append(float(confidence))
                    page = field.get("PageNumber") or page

                name = (values.get(FIELD_ITEM) or "").strip()
                if not name:
                    # A line with no product name is not a line item we can
                    # reason about. Skipping it is honest; inventing a name
                    # would not be.
                    continue

                index += 1
                items.append(ReaderItem(
                    index=index,
                    name=" ".join(name.split()),
                    quantity=parse_money(values.get(FIELD_QUANTITY)),
                    unit_price=parse_money(values.get(FIELD_UNIT_PRICE)),
                    line_total=parse_money(values.get(FIELD_PRICE)),
                    # The line's confidence is its WEAKEST field. A row whose
                    # name read at 99 and whose price read at 60 is a 60.
                    confidence=(
                        Decimal(str(round(min(confidences), 2)))
                        if confidences else None
                    ),
                    page=int(page),
                ))

        for field in document.get("SummaryFields", []):
            kind = (field.get("Type") or {}).get("Text", "").upper()
            if kind == SUMMARY_TOTAL and printed_total is None:
                printed_total = parse_money(
                    (field.get("ValueDetection") or {}).get("Text")
                )

    return ReaderOutput(
        source="textract_analyze_expense",
        items=items,
        printed_grand_total=printed_total,
    )


# --------------------------------------------------------------------------
# Reader B -- Claude vision through Bedrock Converse
# --------------------------------------------------------------------------

#: Converse accepts these image formats. A PDF cannot go down this path.
logger = logging.getLogger(__name__)

IMAGE_FORMATS = {
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}

#: Converse takes a PDF as a DOCUMENT block rather than an image block.
#: Without this, PDFs never reached the second reader at all -- read_with_bedrock
#: returned None before making any call, and the bill silently got ONE reader.
#: That is worse than a degraded reading: the two-reader cross-check is the
#: only thing that catches a confident misread, and it is exactly what caught
#: Textract reading a column HEADER as line item 1 on bill_02.jpg. On a PDF we
#: were claiming a guarantee we were not providing. Indian hospital bills
#: arrive as PDFs constantly.
DOCUMENT_FORMATS = {"application/pdf": "pdf"}

#: A CONSTANT, and deliberately not the uploaded filename. AWS documents this
#: field as "vulnerable to prompt injections, because the model might
#: inadvertently interpret it as instructions", and the filename is supplied
#: by whoever uploads the bill. A fixed neutral string cannot carry an
#: instruction.
DOCUMENT_NAME = "bill"

PROMPT = """You are reading an Indian hospital or pharmacy bill.

Return STRICT JSON only. No prose, no markdown fence.

{"items":[{"index":1,"name":"...","quantity":"10","unit_price":"40.00",
"line_total":"360.00","confidence":95}],"printed_grand_total":"2469.60"}

Rules you must follow:
- Copy values EXACTLY as printed. Do not compute anything.
- If a value is unreadable, use null. NEVER guess a number.
- confidence is 0-100, your own confidence in that line.
- Include every line item you can see, in order, top to bottom.
- printed_grand_total is the total printed on the bill, or null."""


def read_with_bedrock(content: bytes, content_type: str) -> ReaderOutput | None:
    """Second opinion from a vision model. None when unavailable.

    Returns None rather than raising: a missing second reader costs us
    confidence, not the whole request.
    """
    mime = (content_type or "").split(";")[0].strip().lower()
    image_format = IMAGE_FORMATS.get(mime)
    document_format = DOCUMENT_FORMATS.get(mime)
    if image_format is None and document_format is None:
        return None
    if not config.BEDROCK_INFERENCE_PROFILE_ID:
        return None

    if image_format is not None:
        source_block = {"image": {"format": image_format,
                                  "source": {"bytes": content}}}
    else:
        source_block = {"document": {"format": document_format,
                                     "name": DOCUMENT_NAME,
                                     "source": {"bytes": content}}}

    try:
        response = aws_clients.bedrock_runtime().converse(
            modelId=config.BEDROCK_INFERENCE_PROFILE_ID,
            messages=[{
                "role": "user",
                "content": [source_block, {"text": PROMPT}],
            }],
            inferenceConfig={"maxTokens": 4096, "temperature": 0},
        )
        text = response["output"]["message"]["content"][0]["text"]
        payload = json.loads(_strip_fence(text))
    except Exception as exc:
        # Deliberately broad. Model access not granted, a throttle, a
        # malformed response -- every one of them means "no second reader",
        # and none of them should turn into a 500 for the user.
        #
        # BUT IT MUST NOT BE SILENT. Swallowing the cause meant PDFs lost the
        # second reader in production and the logs showed only START/END --
        # a guarantee quietly absent with no way to find out why. A degraded
        # reading is acceptable; an undiagnosable one is not.
        #
        # The exception TYPE and MESSAGE only. Never the bill bytes, never the
        # model's output, never the filename: CloudWatch must not become a
        # place where a patient's bill can be read.
        logger.warning(
            "second reader unavailable (%s): %s | format=%s",
            type(exc).__name__, exc,
            image_format or document_format,
        )
        return None

    items: list[ReaderItem] = []
    for n, raw in enumerate(payload.get("items") or [], start=1):
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        items.append(ReaderItem(
            index=int(raw.get("index") or n),
            name=" ".join(name.split()),
            quantity=parse_money(raw.get("quantity")),
            unit_price=parse_money(raw.get("unit_price")),
            line_total=parse_money(raw.get("line_total")),
            confidence=parse_money(str(raw.get("confidence"))
                                   if raw.get("confidence") is not None else None),
            page=1,
        ))

    return ReaderOutput(
        source="bedrock_vision",
        items=items,
        printed_grand_total=parse_money(payload.get("printed_grand_total")),
    )


def _strip_fence(text: str) -> str:
    """Models sometimes wrap JSON in a markdown fence despite being told not to."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()
