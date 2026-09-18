"""Verifying our own reading of the bill. Pure Python, no AWS variant.

This is the part judges will ask about. A line is trusted only when the
system can show its own work, and anything that is not trusted is excluded
from every price rule rather than guessed at.

A line is HIGH confidence only if ALL of these hold:

  1. Both readers agree -- name similarity >= 90 and quantity, unit price and
     line total each within Rs 1. Or only one reader ran and its own
     confidence is >= 95.
  2. quantity x unit_price - discount + tax equals line_total within Rs 1.
  3. Sanity bounds: quantity 0.01-500, unit price Rs 0.10-5,00,000.

Anything else is `unverified_reading`, shown gray with reason
could_not_verify, and excluded from R5/R6/R7.
"""

from __future__ import annotations

from decimal import Decimal

from rapidfuzz import fuzz

from .salt_synonyms import normalise_spelling
from ..models import (
    BillInput,
    ReaderItem,
    ReaderOutput,
    ReadingConfidence,
    ReadingStats,
    Reconciliation,
    VerifiedItem,
)

NAME_SIMILARITY_MIN = 90
SINGLE_READER_CONFIDENCE_MIN = Decimal("95")
MONEY_TOLERANCE = Decimal("1")

QUANTITY_MIN = Decimal("0.01")
QUANTITY_MAX = Decimal("500")
UNIT_PRICE_MIN = Decimal("0.10")
UNIT_PRICE_MAX = Decimal("500000")


def _close(a: Decimal | None, b: Decimal | None, tol: Decimal = MONEY_TOLERANCE) -> bool:
    """None never agrees with anything. A missing value is not a match."""
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def name_similarity(a: str, b: str) -> float:
    """Compare names AFTER normalising punctuation and spacing.

    Comparing raw strings penalises formatting rather than content:
    "X-Ray Chest PA View" vs "X Ray Chest PA View" scored 79 on the hyphen
    alone and lost a perfectly good reading. A hyphen is not a disagreement
    between readers. Genuine differences -- "Dr." vs "Doctor" -- still score
    below the threshold, and still cost the line its HIGH confidence.
    """
    return fuzz.token_sort_ratio(normalise_spelling(a), normalise_spelling(b))


def arithmetic_holds(item: ReaderItem | VerifiedItem) -> bool | None:
    """Does qty x price - discount + tax == line_total? None if unknowable."""
    if item.quantity is None or item.unit_price is None or item.line_total is None:
        return None
    computed = item.quantity * item.unit_price - item.discount + item.tax
    return abs(computed - item.line_total) <= MONEY_TOLERANCE


def within_sanity_bounds(item: ReaderItem | VerifiedItem) -> bool:
    if item.quantity is None or item.unit_price is None:
        return False
    if not (QUANTITY_MIN <= item.quantity <= QUANTITY_MAX):
        return False
    return UNIT_PRICE_MIN <= item.unit_price <= UNIT_PRICE_MAX


def _index_by(reader: ReaderOutput | None) -> dict[int, ReaderItem]:
    return {i.index: i for i in reader.items} if reader else {}


def verify_item(a: ReaderItem | None, b: ReaderItem | None) -> VerifiedItem:
    """Combine one line's two readings into a verdict.

    Reader A is preferred as the value source when both agree, because
    Textract's numeric extraction is structured rather than generated.
    """
    primary = a or b
    if primary is None:
        raise ValueError("verify_item needs at least one reading")

    item = VerifiedItem(
        index=primary.index,
        name=primary.name,
        quantity=primary.quantity,
        unit_price=primary.unit_price,
        discount=primary.discount,
        tax=primary.tax,
        line_total=primary.line_total,
        page=primary.page,
    )

    reasons: list[str] = []
    agrees = False

    if a is not None and b is not None:
        similarity = name_similarity(a.name, b.name)
        name_ok = similarity >= NAME_SIMILARITY_MIN
        qty_ok = _close(a.quantity, b.quantity)
        price_ok = _close(a.unit_price, b.unit_price)
        total_ok = _close(a.line_total, b.line_total)

        agrees = name_ok and qty_ok and price_ok and total_ok
        if agrees:
            reasons.append(f"both_readers_agree:name_similarity={similarity:.0f}")
        else:
            if not name_ok:
                reasons.append(f"readers_disagree_on_name:similarity={similarity:.0f}")
            if not qty_ok:
                reasons.append("readers_disagree_on_quantity")
            if not price_ok:
                reasons.append("readers_disagree_on_unit_price")
            if not total_ok:
                reasons.append("readers_disagree_on_line_total")
    else:
        confidence = primary.confidence
        if confidence is not None and confidence >= SINGLE_READER_CONFIDENCE_MIN:
            agrees = True
            reasons.append(f"single_reader_high_confidence:{confidence}")
        else:
            reasons.append(
                f"single_reader_low_confidence:{confidence if confidence is not None else 'unknown'}"
            )

    arithmetic = arithmetic_holds(item)
    if arithmetic is None:
        reasons.append("arithmetic_not_checkable:missing_values")
    elif arithmetic:
        reasons.append("arithmetic_holds")
    else:
        reasons.append("arithmetic_does_not_hold")

    bounds_ok = within_sanity_bounds(item)
    if not bounds_ok:
        reasons.append("outside_sanity_bounds")

    if agrees and arithmetic is True and bounds_ok:
        item.confidence = ReadingConfidence.HIGH
    else:
        item.confidence = ReadingConfidence.UNVERIFIED

    item.reasons = reasons
    return item


def verify_bill(bill: BillInput) -> tuple[list[VerifiedItem], ReadingStats]:
    """Verify every line, then reconcile the bill against its printed total."""
    a_items = _index_by(bill.reader_a)
    b_items = _index_by(bill.reader_b)

    verified = [
        verify_item(a_items.get(index), b_items.get(index))
        for index in sorted(set(a_items) | set(b_items))
    ]

    totals = [i.line_total for i in verified if i.line_total is not None]
    line_sum = sum(totals, Decimal("0")) if totals else None

    printed = bill.reader_a.printed_grand_total
    if printed is None and bill.reader_b is not None:
        printed = bill.reader_b.printed_grand_total

    # THE DIRECTION OF THE DIFFERENCE IS THE WHOLE POINT.
    #
    # R2 exists to protect a patient from being asked for more than the bill
    # itemises. A printed total BELOW the line sum is the opposite situation:
    # the patient pays less than the lines justify, which is what a discount
    # or a round-off looks like when we did not manage to read it.
    #
    # Measured on the deployed stack 2026-09-19: Textract read the NET amount
    # (431.00) rather than the subtotal (453.94) on a retail pharmacy bill,
    # and we asked the pharmacy to explain the Rs 22.94 difference -- which
    # was exactly their own printed discount plus round-off. We queried a
    # bill for charging the patient LESS.
    if printed is None:
        reconciliation = Reconciliation.NO_TOTAL_FOUND
    elif line_sum is None:
        reconciliation = Reconciliation.MISMATCH
    elif abs(line_sum - printed) <= MONEY_TOLERANCE:
        reconciliation = Reconciliation.RECONCILED
    elif printed < line_sum:
        reconciliation = Reconciliation.BELOW_LINE_SUM
    else:
        reconciliation = Reconciliation.MISMATCH

    stats = ReadingStats(
        total_items=len(verified),
        auto_high=sum(1 for i in verified if i.is_high),
        # The crop-and-reread pass is an AWS-mode capability; in local mode
        # nothing is ever rescued, and we report 0 rather than implying one ran.
        rescued_by_reread=0,
        still_unverified=sum(1 for i in verified if not i.is_high),
        reconciliation=reconciliation,
        sum_of_line_totals=line_sum,
        printed_grand_total=printed,
    )
    return verified, stats
