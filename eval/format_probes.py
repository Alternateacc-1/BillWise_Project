"""Bill-format experiment. Run every format we have not tried; record what
breaks.

Each probe is a READING of a bill -- what a perfect OCR pass would hand the
engine. Reading quality is deliberately NOT the variable: the question is what
the ENGINE does with a shape it has never seen, given flawless input. That
isolates engine bugs from reader bugs, which is the whole point.

NOT part of the eval gate, deliberately. Three of these probes produce findings
that are KNOWN TO BE FALSE (Classes E, F and G in docs/FORMAT_FINDINGS.md).
Writing those into eval/ground_truth/ would bless the bug as expected
behaviour and make the eval defend it. They live here as a reproducible
measurement instead, and each graduates into the eval set as its class is
fixed.

Run:  python eval/format_probes.py
"""

import pathlib
import sys
from decimal import Decimal as D

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from app.models import BillInput, ReaderItem, ReaderOutput
from app.pipeline.audit import audit
from app.pipeline.normalize import normalize_bill
from app.pipeline.verify import verify_bill


def item(n, name, qty, unit, total, conf="97"):
    return ReaderItem(
        index=n, name=name,
        quantity=D(qty) if qty is not None else None,
        unit_price=D(unit) if unit is not None else None,
        line_total=D(total) if total is not None else None,
        confidence=D(conf),
    )


PROBES = []


def probe(name, question, items, total, note=""):
    PROBES.append((name, question, items, D(total) if total else None, note))


# -- P2 wholesale B2B: priced per STRIP, line discounts ---------------------
probe("P2 wholesale B2B invoice",
      "priced per strip, not per tablet; per-line discount column",
      [item(1, "AMOXYCILLIN 500MG CAP 10'S", "10", "36.00", "360.00"),
       item(2, "PARACETAMOL 500MG TAB 15'S", "20", "13.95", "279.00"),
       item(3, "PANTOPRAZOLE 40MG TAB 10'S", "5", "85.00", "425.00")],
      "1064.00",
      "per-line trade discount of 10% is printed but not modelled at all")

# -- P3 diagnostic lab: no drugs at all ------------------------------------
probe("P3 diagnostic lab bill",
      "every line is a test; nothing is price-controlled",
      [item(1, "Complete Blood Count (CBC)", "1", "350.00", "350.00"),
       item(2, "Lipid Profile", "1", "800.00", "800.00"),
       item(3, "HbA1c", "1", "550.00", "550.00"),
       item(4, "Thyroid Profile (T3 T4 TSH)", "1", "700.00", "700.00"),
       item(5, "Sample Collection Charges", "1", "50.00", "50.00")],
      "2450.00")

# -- P4 thermal receipt: no quantity column at all -------------------------
probe("P4 thermal-printer receipt",
      "name and amount only; NO quantity and NO rate column",
      [item(1, "PARACETAMOL 500", None, None, "22.00"),
       item(2, "AZITHRO 500 TAB", None, None, "168.00"),
       item(3, "COUGH SYRUP 100ML", None, None, "95.00")],
      "285.00")

# -- P5 multi-page with per-section subtotals ------------------------------
# The trap: a reader that treats a printed SUBTOTAL row as a line item.
probe("P5 multi-page, per-section subtotals",
      "section subtotal rows are read as if they were line items",
      [item(1, "Room Rent - Private (2 days)", "2", "4500.00", "9000.00"),
       item(2, "Nursing Charges", "2", "900.00", "1800.00"),
       item(3, "SUBTOTAL - ROOM & NURSING", None, None, "10800.00"),
       item(4, "Paracetamol 500mg Tablet", "20", "0.90", "18.00"),
       item(5, "Augmentin 625 Duo Tablet", "10", "20.00", "200.00"),
       item(6, "SUBTOTAL - PHARMACY", None, None, "218.00"),
       item(7, "CBC - Complete Blood Count", "1", "350.00", "350.00"),
       item(8, "SUBTOTAL - LABORATORY", None, None, "350.00")],
      "11368.00",
      "line sum incl. subtotal rows = 22736.00, exactly double the true total")

# -- P6 GST-exclusive line pricing, GST added at the bottom ----------------
# Our gate compares the billed per-unit against ceiling*1.12, i.e. it assumes
# the billed figure ALREADY includes GST. Here it does not.
probe("P6 GST-exclusive line pricing",
      "line rates are ex-GST; GST is added once at the bottom",
      [item(1, "Augmentin 625 Duo Tablet", "10", "23.00", "230.00"),
       item(2, "Paracetamol 500mg Tablet", "20", "0.95", "19.00"),
       item(3, "Pantoprazole 40mg Tablet", "10", "9.00", "90.00")],
      "379.68",
      "339.00 + 12% GST = 379.68; the per-unit figures the engine sees are "
      "ex-GST but it treats them as GST-inclusive")

# -- P7 per-line discount column -------------------------------------------
probe("P7 per-line discount",
      "line total is qty*rate MINUS a discount printed on the same row",
      [item(1, "Augmentin 625 Duo Tablet", "10", "35.00", "315.00"),
       item(2, "Paracetamol 500mg Tablet", "20", "1.00", "18.00")],
      "333.00",
      "10% off each line; qty*rate does not equal the printed line total")


def main() -> int:
    print("=" * 78)
    print("BILL-FORMAT EXPERIMENT -- measurement pass")
    print("=" * 78)

    false_findings = 0
    for name, question, items, total, note in PROBES:
        r = ReaderOutput(source="probe", items=items, printed_grand_total=total)
        bill = BillInput(bill_id="probe", hospital_name="(probe)",
                         bill_date="2026-09-18", reader_a=r, reader_b=r)
        verified, stats = verify_bill(bill)
        flags = audit(verified, normalize_bill(verified), stats)

        print()
        print("-" * 78)
        print(name)
        print(f"  what it tests : {question}")
        if note:
            print(f"  note          : {note}")
        print(f"  reconciliation: {stats.reconciliation.value}")
        print(f"  read HIGH     : {stats.auto_high}/{stats.total_items}")

        by = {s: [f for f in flags if f.severity.value == s]
              for s in ("red", "amber", "green", "gray")}
        print(f"  verdicts      : {len(by['red'])} red  {len(by['amber'])} amber"
              f"  {len(by['green'])} green  {len(by['gray'])} gray")
        for f in flags:
            if f.severity.value in ("red", "amber"):
                false_findings += 1
                print(f"     -> {f.rule_id} {f.severity.value.upper()} item "
                      f"{f.item_index} amount {f.amount_affected}")
        reasons = {}
        for f in by["gray"]:
            k = (f.gray_detail.value if f.gray_detail
                 else f.gray_reason.value if f.gray_reason else "?")
            reasons[k] = reasons.get(k, 0) + 1
        if reasons:
            print(f"  gray reasons  : {reasons}")

    print()
    print("=" * 78)
    print("  Every red/amber above is on a bill that is arithmetically PERFECT.")
    print("  See docs/FORMAT_FINDINGS.md for the class each one belongs to.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
