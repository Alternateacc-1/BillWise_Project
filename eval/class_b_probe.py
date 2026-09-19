"""CLASS B / E / F -- is the ledger bug still live, and at which of its scales?

NOTES.md's START HERE names Class B as "the ONLY thing currently WRONG rather
than merely silent", citing a false `R2 amber Rs 22.94` measured on the
deployed stack. That measurement predates `93184bd`, which made R2 directional.
The deployed stack is stale, so the note may be describing a bug the code no
longer has.

THIS SCRIPT DECIDES THAT BY RUNNING IT, not by reading the diff.

B, E and F were declared one bug at three scales -- bill totals, section
subtotals, line adjustments -- so all three are run here. A directional R2
cannot help F at all, because F is an R1 failure.

Run:  python eval/class_b_probe.py
"""

from __future__ import annotations

import pathlib
import sys
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from app.models import (  # noqa: E402
    BillInput, ReaderItem, ReaderOutput,
)
from app.pipeline.audit import audit  # noqa: E402
from app.pipeline.normalize import normalize_bill  # noqa: E402
from app.pipeline.verify import verify_bill  # noqa: E402


def _reader(items, total, source):
    return ReaderOutput(
        source=source,
        items=[ReaderItem(**i) for i in items],
        printed_grand_total=Decimal(total) if total is not None else None,
    )


def run(label, why, items, printed, expect):
    """Two identical readers: this isolates the ledger from reader disagreement."""
    bill = BillInput(
        bill_id="probe", hospital_name="", bill_date="",
        reader_a=_reader(items, printed, "textract"),
        reader_b=_reader(items, printed, "bedrock"),
    )
    verified, stats = verify_bill(bill)
    flags = audit(verified, normalize_bill(verified), stats)
    bill_flags = [f for f in flags if f.item_index is None]
    r1 = [f for f in flags if f.rule_id == "R1"]
    r2 = [f for f in flags if f.rule_id == "R2"]

    print(f"\n  {label}")
    print(f"     {why}")
    print(f"     reconciliation : {stats.reconciliation.value}")
    print(f"     line sum       : {stats.sum_of_line_totals}")
    print(f"     printed total  : {stats.printed_grand_total}")
    ok = (not r1 and not r2) if expect == "silent" else bool(r1 or r2)
    for f in r1 + r2 + bill_flags:
        print(f"     -> {f.rule_id} {f.severity.value} Rs {f.amount_affected}")
    if not r1 and not r2:
        print("     -> no R1, no R2")
    print(f"     EXPECTED {expect}: {'PASS' if ok else '*** FAIL ***'}")
    return 0 if ok else 1


def main() -> int:
    print("=" * 74)
    print("CLASS B / E / F -- the ledger bug, run rather than read")
    print("=" * 74)
    bad = 0

    # ---- CLASS B: the deployed observation, reproduced exactly. ------------
    # A real retail pharmacy bill. Lines sum to the SUBTOTAL 453.94; the bill
    # prints discount 20.94 and round-off 2.00, NET 431.00. Textract returned
    # 431.00 as the total. The bill is arithmetically perfect.
    lines_b = [
        {"index": 1, "name": "Item A", "quantity": "1", "line_total": "120.50"},
        {"index": 2, "name": "Item B", "quantity": "2", "line_total": "88.00"},
        {"index": 3, "name": "Item C", "quantity": "1", "line_total": "145.44"},
        {"index": 4, "name": "Item D", "quantity": "1", "line_total": "100.00"},
    ]
    bad += run(
        "CLASS B  printed total is the NET, lines sum to the SUBTOTAL",
        "453.94 lines vs 431.00 printed; 22.94 is the bill's own discount + round-off",
        lines_b, "431.00", expect="silent")

    # ---- CLASS E: a printed SUBTOTAL row read as a line item. -------------
    # The subtotal is counted twice, so the line sum is ~double the total.
    lines_e = [
        {"index": 1, "name": "Item A", "quantity": "1", "line_total": "120.50"},
        {"index": 2, "name": "Item B", "quantity": "2", "line_total": "88.00"},
        {"index": 3, "name": "SUBTOTAL", "quantity": None, "line_total": "208.50"},
    ]
    bad += run(
        "CLASS E  a SUBTOTAL row read as a line item",
        "line sum 417.00 against a printed 208.50 -- the whole bill, twice",
        lines_e, "208.50", expect="silent")

    # ---- CLASS F: a per-line discount column. ------------------------------
    # qty * rate disagrees with the printed line total BY DESIGN: the bill
    # shows a discount on the line. R1 has no ledger, so it calls correct
    # arithmetic broken. A directional R2 cannot help here.
    lines_f = [
        {"index": 1, "name": "Item A", "quantity": "10", "unit_price": "12.00",
         "line_total": "108.00"},
    ]
    bad += run(
        "CLASS F  a per-line discount column",
        "10 x 12.00 = 120.00, line total reads 108.00 after a 10% line discount",
        lines_f, "108.00", expect="silent")

    print()
    print("=" * 74)
    print(f"  SCALES STILL BROKEN: {bad} of 3")
    print("=" * 74)
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
