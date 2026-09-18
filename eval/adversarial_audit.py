"""ADVERSARIAL AUDIT. Goal: make BillSahi emit a FALSE RED.

Every bill below is CORRECTLY PRICED. Any red is a false accusation.
"""
import pathlib
import sys
from decimal import Decimal as D
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
from app.models import BillInput, ReaderItem, ReaderOutput
from app.pipeline.audit import audit
from app.pipeline.normalize import normalize_bill
from app.pipeline.verify import verify_bill

ATTACKS = []
def attack(n, why, items, total, two_readers=True):
    ATTACKS.append((n, why, items, D(total), two_readers))

def I(i, name, qty, rate, total, conf="98"):
    return ReaderItem(index=i, name=name,
                      quantity=D(qty) if qty is not None else None,
                      unit_price=D(rate) if rate is not None else None,
                      line_total=D(total), confidence=D(conf))

# A1: strip price read as unit price. 10 tablets at ceiling => 9.30/strip.
#     Per-unit reads 9.30 vs allowance 1.0416 = 8.9x. Under the 50x guard,
#     far over the 25% margin. The bill is CORRECT.
attack("A1 strip-as-unit, ratio 8.9x (under the 50x guard)",
       "a strip of 10 priced exactly at ceiling, read as one unit",
       [I(1, "Paracetamol 500mg Tablet", "1", "9.30", "9.30")], "9.30")

# A2: same, engineered to sit just under 50x. 0.93*50*1.12 = 52.08/unit.
attack("A2 ratio engineered to 45x, just under the guard",
       "pack of 45 at ceiling, read as one unit",
       [I(1, "Paracetamol 500mg Tablet", "1", "41.85", "41.85")], "41.85")

# A3: OCR digit substitution inflating a rate, SINGLE READER (as measured on
#     the deployed stack for bill_05/bill_06). 1.10 misread as 7.10.
attack("A3 digit substitution 1->7, single reader, high confidence",
       "compliant 1.10/tab misread as 7.10; no second reader to disagree",
       [I(1, "Paracetamol 500mg Tablet", "10", "7.10", "71.00", conf="99")],
       "11.00", two_readers=False)

# A4: decimal shift. 1.10 -> 11.00 (10x).
attack("A4 decimal shift 1.10 -> 11.00, single reader",
       "compliant rate shifted one decimal place",
       [I(1, "Paracetamol 500mg Tablet", "10", "11.00", "110.00", conf="99")],
       "110.00", two_readers=False)

# A5: Ringer Lactate 500ml bag priced correctly at the 500ml ceiling, but if
#     matched against the 100ml row (0.3062/ml) it looks 2.3x over.
attack("A5 pack-size crossing: 500ml bag vs 100ml ceiling",
       "500ml at its own ceiling; 100ml row is dearer PER ML",
       [I(1, "Ringer Lactate Injection 500 ml", "1", "66.50", "66.50")], "66.50")

# A6: form_modifier collision after the alias table. Plain aspirin at the
#     PLAIN ceiling (0.39); if matched to the DT row (0.36) it looks over.
attack("A6 form_modifier collision via alias: ASPIRIN TAB",
       "plain aspirin at its own ceiling; DT row is CHEAPER",
       [I(1, "ASPIRIN TAB 75 MG", "10", "0.43", "4.30")], "4.30")

# A7: GST-INCLUSIVE line pricing presented as if ex-GST.
attack("A7 GST-inclusive rate treated as ex-GST",
       "1.04 incl GST = 0.93 ex GST, exactly at ceiling",
       [I(1, "Paracetamol 500mg Tablet", "10", "1.04", "10.40")], "10.40")

# A8: bill-level discount making a compliant line look excessive.
attack("A8 bill-level discount vs compliant line",
       "line at ceiling; bill total far below the line sum",
       [I(1, "Paracetamol 500mg Tablet", "10", "1.00", "10.00"),
        I(2, "Augmentin 625 Duo Tablet", "10", "20.00", "200.00")], "150.00")

# A9: quantity ambiguity engineered so BOTH interpretations exceed red.
#     qty 2 "boxes" of 15 strips of 10. Billed 300 for 2 -> 150/unit.
attack("A9 both interpretations over the red threshold",
       "deep pack nesting; every reading looks excessive",
       [I(1, "Paracetamol 500mg Tablet", "2", "150.00", "300.00")], "300.00")

# A10: brand alias reaching a modified-release ceiling.
attack("A10 alias + release modifier: PANTOCID TAB vs SR row",
       "plain tablet priced correctly; SR variants exist in the index",
       [I(1, "PANTOCID TAB", "15", "8.50", "127.50")], "127.50")

print("=" * 78)
print("ADVERSARIAL AUDIT -- every bill below is CORRECTLY PRICED")
print("=" * 78)
false_reds = 0
for name, why, items, total, two in ATTACKS:
    ra = ReaderOutput(source="textract", items=items, printed_grand_total=total)
    rb = ReaderOutput(source="vision", items=items, printed_grand_total=total) if two else None
    bill = BillInput(bill_id="atk", hospital_name="", bill_date="",
                     reader_a=ra, reader_b=rb)
    v, st = verify_bill(bill)
    flags = audit(v, normalize_bill(v), st)
    reds = [f for f in flags if f.severity.value == "red"]
    ambers = [f for f in flags if f.severity.value == "amber"]
    grays = [f for f in flags if f.severity.value == "gray"]
    greens = [f for f in flags if f.severity.value == "green"]
    verdict = "*** FALSE RED ***" if reds else (
        f"{len(ambers)} amber" if ambers else
        f"{len(greens)} green / {len(grays)} gray")
    if reds:
        false_reds += 1
    print(f"\n  {name}")
    print(f"     {why}")
    print(f"     -> {verdict}")
    for f in flags:
        d = f.gray_detail.value if f.gray_detail else ""
        print(f"        {f.rule_id} {f.severity.value:<6} amt {str(f.amount_affected):>9} {d}")
print("\n" + "=" * 78)
print(f"  FALSE REDS: {false_reds} / {len(ATTACKS)} attacks")
print("=" * 78)
