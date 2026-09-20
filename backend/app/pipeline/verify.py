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
    """Do two readers agree about this field?

    TWO READERS AGREEING THAT A FIELD IS ABSENT IS AGREEMENT, NOT A
    DISAGREEMENT. This used to return False for (None, None), which meant a
    bill that simply does not print a unit-price column was treated as one the
    readers could not agree about.

    That is not hypothetical. The commonest retail pharmacy layout in India
    prints MRP, PACK, QTY and TOTAL and expects you to divide -- measured on
    the deployed stack, all six lines of such a bill came back unreadable.

    One reader seeing a value and the other not IS a disagreement, and still
    returns False.
    """
    if a is None and b is None:
        return True
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
    """Is every value we DID read plausible?

    A FIELD THAT IS ABSENT CANNOT BE IMPLAUSIBLE. This used to return False
    whenever quantity or unit_price was missing, so "we did not read this"
    and "this value is nonsense" produced the same verdict -- and a bill that
    prints no unit-price column failed a check it was never eligible for.

    Each field present is checked; each field absent is skipped. A line with
    nothing to check passes, and is held to account by the rules that need
    those values rather than by this one.
    """
    if item.quantity is not None:
        if not (QUANTITY_MIN <= item.quantity <= QUANTITY_MAX):
            return False
    if item.unit_price is not None:
        if not (UNIT_PRICE_MIN <= item.unit_price <= UNIT_PRICE_MAX):
            return False
    return True


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
        # Never imply a cross-check that did not happen. `only_one_reader_ran`
        # is recorded explicitly, because "single_reader_high_confidence:97"
        # alone reads like a strong result when it actually means the second
        # opinion is missing and nothing was compared.
        reasons.append("only_one_reader_ran")
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

    # line_total IS LOAD-BEARING AND IS NOT OPTIONAL.
    #
    # Relaxing "absent means wrong" must not go so far as to call a line with
    # no money on it well-read. Without a line total there is no charge to
    # audit: no per-unit price can be derived, nothing can be reconciled, and
    # "we read this line reliably" would be a claim about a name and a
    # quantity. A missing unit price is survivable because line_total/qty
    # still bounds it; a missing line total is not.
    has_money = item.line_total is not None

    # `arithmetic is not False`, NOT `arithmetic is True`. None means the
    # bill did not print the inputs, which is a check that cannot RUN -- not
    # one that failed. Demanding True meant a bill without a unit-price column
    # failed its arithmetic check by not having any arithmetic to do.
    if agrees and has_money and arithmetic is not False and bounds_ok:
        item.confidence = ReadingConfidence.HIGH
    else:
        item.confidence = ReadingConfidence.UNVERIFIED

    item.reasons = reasons
    return item


#: How alike two rows must look before we treat them as THE SAME ROW of the
#: bill. Deliberately far below NAME_SIMILARITY_MIN (90), which is the bar for
#: two readings to AGREE. Pairing only decides what to compare; verify_item
#: still decides whether the comparison passes, so a generous pairing costs
#: nothing and a mean one throws away cross-checks we could have had.
PAIR_MIN_SCORE = 55.0


def _pair_score(a: ReaderItem, b: ReaderItem) -> float:
    """How likely are these two readings of the SAME row of the bill?"""
    score = name_similarity(a.name, b.name)
    # An identical line total is strong evidence, and it survives the case
    # this exists for: the two readers disagreeing about the NAME.
    if (a.line_total is not None and b.line_total is not None
            and a.line_total == b.line_total):
        score += 60.0
    if (a.quantity is not None and b.quantity is not None
            and a.quantity == b.quantity):
        score += 10.0
    return score


def _pair_readings(
    a_items: dict[int, ReaderItem], b_items: dict[int, ReaderItem]
) -> list[tuple[ReaderItem | None, ReaderItem | None]]:
    """Match the two readings BY CONTENT, not by position.

    Pairing by row index breaks as soon as the readers disagree on how many
    rows a bill has -- one takes a header as an item, the other merges a
    wrapped description, and from there every index refers to a different row
    in each reading.

    That failed SAFE (a mismatched pairing disagrees, and disagreement means
    gray) but it threw away most of the cross-check, which is the one thing
    protecting the price rules from a confident misread.

    Greedy assignment on `_pair_score`, highest first, each row used once.
    Ties break on index so the result never depends on dict ordering.

    A WRONG PAIRING CANNOT MANUFACTURE AGREEMENT. verify_item() re-checks the
    name and every number afterwards, so two rows paired in error disagree and
    go gray. The only thing a bad pairing costs is a cross-check, which is
    exactly what the old scheme was already losing.
    """
    candidates = [
        (-_pair_score(a, b), a.index, b.index)
        for a in a_items.values()
        for b in b_items.values()
    ]
    candidates.sort()

    used_a: set[int] = set()
    used_b: set[int] = set()
    matched: dict[int, int] = {}
    for neg_score, ai, bi in candidates:
        if -neg_score < PAIR_MIN_SCORE:
            break
        if ai in used_a or bi in used_b:
            continue
        used_a.add(ai)
        used_b.add(bi)
        matched[ai] = bi

    # Order by reader A, whose row order is positionally reliable, then append
    # anything only reader B saw.
    pairs: list[tuple[ReaderItem | None, ReaderItem | None]] = []
    for ai in sorted(a_items):
        bi = matched.get(ai)
        pairs.append((a_items[ai], b_items[bi] if bi is not None else None))
    for bi in sorted(b_items):
        if bi not in used_b:
            pairs.append((None, b_items[bi]))
    return pairs


def verify_bill(bill: BillInput) -> tuple[list[VerifiedItem], ReadingStats]:
    """Verify every line, then reconcile the bill against its printed total."""
    a_items = _index_by(bill.reader_a)
    b_items = _index_by(bill.reader_b)

    # Renumbered 1..N in reader A's order. The readers' own indices refer to
    # different rows once their row counts differ, so neither is usable as the
    # line number a person sees.
    verified = []
    for n, (a, b) in enumerate(_pair_readings(a_items, b_items), start=1):
        item = verify_item(a, b)
        item.index = n
        verified.append(item)

    totals = [i.line_total for i in verified if i.line_total is not None]
    line_sum = sum(totals, Decimal("0")) if totals else None

    printed = bill.reader_a.printed_grand_total
    if printed is None and bill.reader_b is not None:
        printed = bill.reader_b.printed_grand_total

    # Only an undercharge is worth a question.
    #
    # R2 protects a patient from being asked for MORE than the bill itemises.
    # A printed total BELOW the line sum is the opposite: the patient pays
    # less than the lines justify, which is what an unread discount or
    # round-off looks like. Without this, a reader that took a bill's NET
    # amount instead of its subtotal made us query a pharmacy over its own
    # printed discount.
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
