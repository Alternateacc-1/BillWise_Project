"""Generate the synthetic demo bills, their fixtures, and their ground truth.

ONE SOURCE OF TRUTH. Each bill is declared once, below, and this script emits
three artefacts from that declaration so they can never drift apart:

    eval/fixtures/bill_NN.json       what the readers would produce
    eval/ground_truth/bill_NN.json   what the engine is expected to find
    eval/demo_bills/bill_NN.pdf      the bill as a human would see it
    eval/demo_bills/bill_05.jpg      one deliberately noisy scan

The bills are shaped like REAL Indian hospital bills: mostly room rent,
nursing, OT and lab charges and consumables, with only a handful of priced
medicines. That ratio is the point. A demo that shows ten red flags would be
lying about what this system can actually check, and the gray majority is
what makes the honest answer visible.

No real hospital. No patient names. Nothing here is a real bill.

Run:  python scripts/make_demo_bills.py
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "eval" / "fixtures"
GROUND_TRUTH = REPO_ROOT / "eval" / "ground_truth"
DEMO_BILLS = REPO_ROOT / "eval" / "demo_bills"

HOSPITAL = "Sunrise Multispeciality Hospital"
ADDRESS = "Plot 14, MIDC Road, Pune 411001  |  GSTIN 27XXXXX0000X1ZX (sample)"


@dataclass
class Line:
    """One bill line, plus what we expect the engine to say about it."""

    name: str
    qty: str
    #: None means THE BILL PRINTS NO UNIT-PRICE COLUMN. That is not an
    #: omission in the fixture -- it is the single most common retail pharmacy
    #: layout in India, which prints MRP/PACK/QTY/TOTAL and expects you to
    #: divide. A line with unit_price=None MUST set line_total_override.
    unit_price: str | None = None
    #: Printed maximum retail price for one PACK. Read by nothing today; this
    #: is R6's input (fix 2) and it is here so the fixture does not need
    #: rewriting when R6 lands.
    mrp: str | None = None
    #: Units per pack, as printed. This is the fact the upper-bound gate
    #: exists because bills usually omit -- when it IS printed the per-unit
    #: price is fully determinable. Class C in FORMAT_FINDINGS.md.
    pack: int | None = None
    #: Set only to plant a deliberate arithmetic error.
    line_total_override: str | None = None
    #: What reader B sees. None means "the same as reader A".
    alt_name: str | None = None
    confidence_a: str = "97"
    confidence_b: str = "95"
    #: Make the two readers disagree on the total, to force unverified.
    alt_line_total: str | None = None
    #: Expected findings: list of (rule_id, severity).
    expect: list[tuple[str, str]] = field(default_factory=list)
    #: Expected gray reason, when the item is expected gray.
    expect_gray_reason: str | None = None
    why: str = ""

    @property
    def line_total(self) -> str:
        if self.line_total_override is not None:
            return self.line_total_override
        if self.unit_price is None:
            raise ValueError(
                f"{self.name!r}: a line with no printed unit price must state "
                "line_total_override -- we never compute a total the bill did "
                "not print."
            )
        return str(Decimal(self.qty) * Decimal(self.unit_price))


@dataclass
class BillSpec:
    bill_id: str
    title: str
    bill_date: str
    lines: list[Line]
    #: Deliberately break the printed total to plant an R2. None = reconciled.
    printed_total_override: str | None = None
    #: None, "mild" (a phone photo: slight rotation, shadow, soft contrast)
    #: or "heavy" (a bad fax-grade scan).
    noisy_image: str | None = None
    #: Override the vendor name. Demo bills are synthetic and say so; a format
    #: fixture copied from a real layout uses a different synthetic name so it
    #: is never mistaken for the hospital bills.
    vendor: str | None = None
    #: "standard"  -> # | Particulars | Qty | Rate | Amount
    #: "retail"    -> PARTICULARS | HSN | MRP | PACK | QTY | CGST | SGST | TOTAL
    #: The retail layout prints NO unit-price column, which is the point.
    layout: str = "standard"
    #: Printed totals-block adjustments, as (label, amount) applied AFTER the
    #: subtotal, e.g. [("Discount", "22.70"), ("Round Off (-)", "0.24")].
    #: Printed on the PDF today; the engine does not read them yet -- that is
    #: Class B, "a totals block is a ledger, not a number".
    adjustments: list[tuple[str, str]] = field(default_factory=list)
    #: Per-line GST as printed, e.g. "2.5" for CGST 2.5% + SGST 2.5% = 5%.
    #: The engine assumes 12% regardless today; Class D.
    printed_gst_half_rate: str | None = None

    def subtotal(self) -> str:
        return str(sum(Decimal(l.line_total) for l in self.lines))

    def net_total(self) -> str:
        """Subtotal less every printed adjustment -- what was actually paid."""
        net = Decimal(self.subtotal())
        for _label, amount in self.adjustments:
            net -= Decimal(amount)
        return str(net)

    def printed_total(self) -> str:
        """What the READER hands the engine as "the total".

        For a bill with a totals block this is the SUBTOTAL, not the net. That
        is the reading that reconciles today. The net-amount reading is the
        Class B case and is exercised separately, because encoding it here
        would bake a known-false R2 into ground truth.
        """
        if self.printed_total_override is not None:
            return self.printed_total_override
        return self.subtotal()


# --------------------------------------------------------------------------
# The bills
#
# bill_01 carries all six required plants. The rest exist to prove the engine
# stays quiet on ordinary bills -- which is what "zero false reds" means.
# --------------------------------------------------------------------------

BILLS = [
    BillSpec(
        bill_id="bill_01",
        title="Inpatient - Minor Surgical Procedure",
        bill_date="2026-09-12",
        lines=[
            Line("Room Rent - Semi Private Ward (3 days)", "3", "3500.00",
                 alt_name="Room Rent Semi Private Ward 3 days",
                 confidence_a="98", expect=[("R9", "gray")],
                 expect_gray_reason="no_public_ceiling",
                 why="room rent has no published ceiling"),
            Line("Nursing Charges", "3", "800.00", confidence_a="98",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("Consultation - Dr. Visit", "4", "600.00",
                 alt_name="Consultation Doctor Visit",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("OT Charges - Minor Procedure", "1", "4500.00",
                 alt_name="OT Charges Minor Procedure", confidence_a="96",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("CBC - Complete Blood Count", "2", "350.00",
                 alt_name="CBC Complete Blood Count",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),

            # PLANT 4: duplicated consumable (this line and the next-but-two).
            Line("Disposable Syringe 5ml", "12", "18.00", confidence_a="95",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("IV Set with Cannula", "4", "95.00", confidence_a="96",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("Surgical Gloves Pair", "10", "22.00", confidence_a="96",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("Disposable Syringe 5ml", "12", "18.00", confidence_a="95",
                 expect=[("R3", "amber")],
                 why="PLANT: duplicate consumable, same name and quantity"),

            # PLANT 1: branded medicine above its ceiling.
            # PLANT 1: branded medicine above its ceiling -- but a PLAUSIBLE
            # amount. The ceiling is 18.74/tablet, so a strip of 10 caps at
            # 187.40 ex-GST, 209.89 with GST, and red starts near 262/strip.
            # 350 is genuinely above it without being a straw man a judge can
            # dismiss. (An earlier draft used 640, which no pharmacy would
            # print.)
            Line("Augmentin 625 Duo Tablet", "2", "350.00",
                 expect=[("R5", "red")],
                 why="PLANT: ceiling 18.74/tab = 262/strip red threshold; "
                     "billed 350/strip. Both interpretations exceed it."),

            # PLANT 5: correctly priced item that must stay green.
            Line("Paracetamol 500mg Tablet", "20", "0.90",
                 expect=[("R5", "green")],
                 why="PLANT: ceiling 0.93/tab; 0.90 is within it"),

            # A second green, and a better demo moment than another red.
            Line("Ringer Lactate Injection 500 ml", "4", "72.00",
                 confidence_a="96",
                 expect=[("R5", "green")],
                 why="ceiling 66.52 per 500ml bag; 72.00 is inside the "
                     "GST-inclusive cap of 74.50"),

            # PLANT 3: arithmetic error. 10 x 12.50 = 125.00, not 130.00.
            Line("Pantop 40mg Tablet", "10", "12.50", line_total_override="130.00",
                 confidence_a="95", confidence_b="93",
                 expect=[("R1", "amber"), ("R9", "gray")],
                 expect_gray_reason="could_not_verify",
                 why="PLANT: arithmetic error of Rs 5.00"),

            # PLANT 2: stent above its ceiling.
            Line("Bare Metal Stent", "1", "24500.00", confidence_a="96",
                 expect=[("R5", "red")],
                 why="PLANT: ceiling 10762.15 per unit; billed at 2.3x"),

            Line("Oxygen Charges per hour", "18", "120.00",
                 confidence_a="94", confidence_b="92",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),

            # PLANT 6: deliberately blurry line -> could_not_verify.
            Line("Bl00d Sug@r Rndm", "1", "180.00",
                 alt_name="Blood Suqar Random",
                 confidence_a="41", confidence_b="38",
                 alt_line_total="190.00",
                 expect=[("R9", "gray")], expect_gray_reason="could_not_verify",
                 why="PLANT: readers disagree and both are low confidence"),
        ],
    ),

    BillSpec(
        bill_id="bill_02",
        title="Pharmacy - Discharge Medication",
        bill_date="2026-09-13",
        # A realistic phone photo. The heavy scan on bill_05 may return
        # nothing at all from real Textract, and total failure is a weaker
        # story than the re-read pass rescuing lines -- so we need a
        # degradation level that is recoverable.
        noisy_image="mild",
        lines=[
            Line("Paracetamol 650mg Tablet", "15", "2.00",
                 expect=[("R5", "green")], why="ceiling 2.05/tab"),
            Line("Amoxicillin 500mg Capsule", "10", "7.40",
                 expect=[("R5", "green")], why="ceiling 7.54/capsule"),
            # PLANT: lands in the 0-25% amber band. A BRANDED name, so the
            # brand index supplies a pack size of 10 and the price is
            # determinable. A generic line without a pack size would now go
            # gray under the upper-bound gate -- correctly, but it would
            # leave the band metric permanently empty.
            # PLANT: the SAME molecule at the SAME per-tablet price as the
            # Acimol line below -- but generic, so nothing supplies a pack
            # size and the upper-bound gate cannot conclude anything. The two
            # lines side by side are the clearest statement of what the gate
            # does: identical prices, one determinable, one not.
            # This line showed AMBER before the gate and shows GRAY after.
            Line("Paracetamol 500mg Tablet", "20", "1.10",
                 expect=[("R5", "gray")],
                 expect_gray_reason="could_not_verify",
                 why="PLANT: 1.10/tab is over the 1.0416 allowance, but with "
                     "no pack size the real per-tablet price is unknowable. "
                     "Was amber before the upper-bound gate; gray is correct."),

            Line("Acimol 500mg Tablet", "2", "11.50",
                 expect=[("R5", "amber")],
                 why="PLANT: ceiling 0.93/tab, allowance 1.0416; strip of 10 "
                     "at 11.50 = 1.15/tab = 10.4% over the allowance, inside "
                     "the 25% red margin so it must stay amber"),
            Line("Pantoprazole 40mg Tablet", "10", "8.50",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling",
                 why="RESOLVES fully (PANTOPRAZOLE, 40mg, tablet) and the "
                     "published list holds only PANTOPRAZOLE INJECTION 40 MG "
                     "-- no tablet row exists. Absence is PROVEN, so this is "
                     "no_public_ceiling, not could_not_identify. Moved "
                     "2026-09-19."),
            Line("Cotton Roll 100gm", "1", "85.00",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("Micropore Tape", "2", "45.00",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
        ],
    ),

    BillSpec(
        bill_id="bill_03",
        title="Outpatient - Consultation and Diagnostics",
        bill_date="2026-09-14",
        lines=[
            Line("Registration Charges", "1", "250.00",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("Consultation - Cardiology", "1", "900.00",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("ECG", "1", "400.00",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("X-Ray Chest PA View", "1", "550.00",
                 alt_name="X Ray Chest PA View",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("Lipid Profile", "1", "1200.00",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("Creatinine - Serum", "1", "300.00",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
        ],
    ),

    BillSpec(
        bill_id="bill_04",
        title="Inpatient - Observation, all charges compliant",
        bill_date="2026-09-15",
        lines=[
            Line("Room Rent - General Ward (2 days)", "2", "1800.00",
                 alt_name="Room Rent General Ward 2 days",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("Nursing Charges", "2", "600.00",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("Ringer Lactate Injection 1000 ml", "2", "120.00",
                 expect=[("R5", "green")],
                 why="ceiling 116.95 per 1000ml special-feature bag"),
            Line("Paracetamol 500mg Tablet", "10", "0.85",
                 expect=[("R5", "green")], why="ceiling 0.93/tab"),
            Line("IV Cannula 20G", "2", "110.00",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("Attendant Charges", "2", "300.00",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
        ],
        # PLANT: the printed total does not match the lines -> R2.
        printed_total_override="6500.00",
    ),

    BillSpec(
        bill_id="bill_05",
        title="Pharmacy - poor quality scan",
        bill_date="2026-09-16",
        noisy_image="heavy",
        lines=[
            Line("Paracetamol 500mg Tablet", "10", "0.88",
                 confidence_a="93", confidence_b="91",
                 expect=[("R5", "green")], why="ceiling 0.93/tab"),
            Line("Surgical Gloves Pair", "5", "22.00",
                 confidence_a="90", confidence_b="88",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling"),
            Line("Amox1cill1n 5OOmg Cap", "10", "7.20",
                 alt_name="Amoxicilln 500rng Cap",
                 confidence_a="44", confidence_b="39",
                 alt_line_total="75.00",
                 expect=[("R9", "gray")], expect_gray_reason="could_not_verify",
                 why="PLANT: OCR garbling, readers disagree"),
        ],
    ),

    # ----------------------------------------------------------------------
    # bill_06 -- FORMAT FIXTURE, not a plant bill.
    #
    # Structure copied from a real OPD pharmacy sale bill (Probe 1 in
    # docs/FORMAT_FINDINGS.md). Line items, quantities, MRP, PACK, the GST
    # split and the totals block are faithful; the vendor name is synthetic
    # and no patient, doctor, invoice, registration or address detail from the
    # source bill exists anywhere in this repo.
    #
    # It plants NOTHING. Its job is to be an ordinary, correctly-priced
    # pharmacy bill in the commonest Indian retail layout, and to fail loudly
    # when we cannot read that layout. Every line is billed at or fractionally
    # below its printed MRP, so there is nothing here to ask about.
    #
    # These six stay GRAY and that is the correct answer. Not one of the
    # medicines on this bill is ceiling-controlled, so 0 of 6 priced is the
    # honest outcome -- measured by eval/bill_06_gap.py. If a change makes
    # these lines produce a price verdict, something is wrong.
    # ----------------------------------------------------------------------
    BillSpec(
        bill_id="bill_06",
        title="Retail pharmacy sale bill - no unit-price column",
        bill_date="2025-12-24",
        vendor="Nagpur City Pharmacy (sample)",
        layout="retail",
        printed_gst_half_rate="2.5",
        adjustments=[("Discount", "22.70"), ("Round Off (-)", "0.24")],
        lines=[
            Line("PANTOCID DSR CAP", "8", mrp="252.19", pack=15,
                 line_total_override="134.48",
                 expect=[("R9", "gray")], expect_gray_reason="no_public_ceiling",
                 why="Resolves via the form-abbreviation alias to DOMPERIDONE "
                     "30 + PANTOPRAZOLE 40, capsule, pack 15 -- the pack count "
                     "independently matching the bill's PACK column. The "
                     "COMBINATION has no row in the 915, so the absence is "
                     "real. MRP/pack 16.8127, billed/unit 16.8100."),
            Line("OFIVAY OZ TAB", "8", mrp="134.00", pack=10,
                 line_total_override="107.20",
                 expect=[("R9", "gray")], expect_gray_reason="could_not_verify",
                 why="Blocked on brand resolution. MRP/pack 13.40 = billed/unit."),
            Line("SINALATE TAB", "8", mrp="67.50", pack=10,
                 line_total_override="54.00",
                 expect=[("R9", "gray")], expect_gray_reason="could_not_verify",
                 why="MOVED 2026-09-19 when the REDUCED brand index shipped. "
                     "SINALATE is CAFFEINE + DIPHENHYDRAMINE, and "
                     "DIPHENHYDRAMINE appears in ZERO ceiling rows, so the "
                     "member-rule filter drops the brand and the deployed data "
                     "cannot identify it. could_not_identify is the ACCURATE "
                     "statement about what ships: we hold nothing at all about "
                     "that molecule. With the full 36 MB index it resolves and "
                     "reads no_public_ceiling -- which is why local and "
                     "production must use the SAME file."),
            Line("EFERIM SP TAB", "8", mrp="97.97", pack=10,
                 line_total_override="78.32",
                 expect=[("R9", "gray")], expect_gray_reason="could_not_verify",
                 why="Blocked on brand resolution. MRP/pack 9.797, billed 9.79."),
            Line("BECOSULE CAP", "4", mrp="62.37", pack=20,
                 line_total_override="12.44",
                 expect=[("R9", "gray")], expect_gray_reason="could_not_verify",
                 why="Blocked on brand resolution. MRP/pack 3.1185, billed 3.11."),
            Line("MEDINOZE NASAL SPRAY", "1", mrp="67.50", pack=1,
                 line_total_override="67.50",
                 expect=[("R9", "gray")], expect_gray_reason="could_not_verify",
                 why="Blocked on brand resolution. Single unit, billed at MRP."),
        ],
    ),
]


# --------------------------------------------------------------------------
# Emit the fixture (what the readers would produce)
# --------------------------------------------------------------------------

def build_fixture(spec: BillSpec) -> dict:
    reader_a, reader_b = [], []
    for n, line in enumerate(spec.lines, start=1):
        reader_a.append({
            "index": n, "name": line.name, "quantity": line.qty,
            "unit_price": line.unit_price, "line_total": line.line_total,
            "confidence": line.confidence_a, "page": 1 if n <= 9 else 2,
        })
        reader_b.append({
            "index": n, "name": line.alt_name or line.name, "quantity": line.qty,
            "unit_price": line.unit_price,
            "line_total": line.alt_line_total or line.line_total,
            "confidence": line.confidence_b, "page": 1 if n <= 9 else 2,
        })

    total = spec.printed_total()
    return {
        "bill_id": spec.bill_id,
        "hospital_name": spec.vendor or f"{HOSPITAL} (sample)",
        "bill_date": spec.bill_date,
        "reader_a": {"source": "fixture_textract", "printed_grand_total": total,
                     "items": reader_a},
        "reader_b": {"source": "fixture_vision", "printed_grand_total": total,
                     "items": reader_b},
    }


def build_ground_truth(spec: BillSpec) -> dict:
    expected, allowed_red = [], []
    for n, line in enumerate(spec.lines, start=1):
        for rule_id, severity in line.expect:
            entry = {
                "item_index": n, "rule_id": rule_id, "severity": severity,
                "item_name": line.name,
            }
            if line.expect_gray_reason and rule_id == "R9":
                entry["gray_reason"] = line.expect_gray_reason
            if line.why:
                entry["why"] = line.why
            expected.append(entry)
            if severity == "red":
                allowed_red.append(n)

    if spec.printed_total_override is not None:
        expected.append({
            "item_index": -1, "rule_id": "R2", "severity": "amber",
            "item_name": "(whole bill)",
            "why": "PLANT: printed total does not match the sum of lines",
        })

    truth = {
        "bill_id": spec.bill_id,
        "description": spec.title,
        "expected": expected,
        # Every line NOT in this list must never come back red. This is the
        # list that makes "zero false reds" a testable claim rather than a
        # slogan.
        "allowed_red_item_indexes": sorted(set(allowed_red)),
    }

    if spec.layout == "retail":
        truth["note"] = (
            "FORMAT FIXTURE. The grays below are the CORRECT answer for this "
            "bill, not a gap waiting to be closed. All six lines read at high "
            "confidence and the bill reconciles; they go gray because not one "
            "of these six medicines is a DPCO ceiling-controlled formulation. "
            "Measured by eval/bill_06_gap.py: five stop at IDENTITY (the brand "
            "resolves but carries no salts) and one at CEILING (identified, no "
            "published ceiling row). "
            "0 of 6 PRICED is the honest outcome and no brand index changes "
            "it. An earlier version of this note promised six GREENS once "
            "brand resolution landed -- brand resolution HAS landed and the "
            "number did not move, because the blocker was never resolution. "
            "Do NOT relax the fixture to make a change pass, and do not go "
            "looking for six greens."
        )

    return truth


# --------------------------------------------------------------------------
# Emit the PDF and the noisy JPG
# --------------------------------------------------------------------------

def write_pdf(spec: BillSpec, path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"{spec.vendor or HOSPITAL} - {spec.bill_id} (sample)",
    )

    story = [
        Paragraph(f"<b>{spec.vendor or HOSPITAL}</b>", styles["Title"]),
        Paragraph(ADDRESS, styles["Normal"]),
        Spacer(1, 6 * mm),
        Paragraph(
            f"<b>{spec.title}</b><br/>Bill No: {spec.bill_id.upper()}-SAMPLE"
            f" &nbsp;&nbsp; Date: {spec.bill_date}<br/>"
            f"Patient: <i>(sample bill - no patient data)</i>",
            styles["Normal"],
        ),
        Spacer(1, 5 * mm),
    ]

    if spec.layout == "retail":
        # The commonest Indian retail pharmacy layout: MRP, PACK, QTY and
        # TOTAL, and NO unit-price column. The reader is expected to divide.
        half = spec.printed_gst_half_rate or "2.5"
        data = [["PARTICULARS", "HSN", "MRP", "PACK", "QTY",
                 f"CGST {half}%", f"SGST {half}%", "TOTAL"]]
        for line in spec.lines:
            gst = (Decimal(line.line_total) * Decimal(half) / Decimal("100")
                   ).quantize(Decimal("0.01"))
            data.append([
                line.name, "3004",
                f"{Decimal(line.mrp):,.2f}" if line.mrp else "",
                str(line.pack) if line.pack else "",
                line.qty, f"{gst:,.2f}", f"{gst:,.2f}",
                f"{Decimal(line.line_total):,.2f}",
            ])
        data.append(["", "", "", "", "", "", "Bill Amount",
                     f"{Decimal(spec.subtotal()):,.2f}"])
        for label, amount in spec.adjustments:
            data.append(["", "", "", "", "", "", label,
                         f"{Decimal(amount):,.2f}"])
        data.append(["", "", "", "", "", "", "Net Amount",
                     f"{Decimal(spec.net_total()):,.2f}"])
        table = Table(data, colWidths=[52 * mm, 12 * mm, 18 * mm, 13 * mm,
                                       12 * mm, 18 * mm, 22 * mm, 24 * mm])
    else:
        data = [["#", "Particulars", "Qty", "Rate", "Amount"]]
        for n, line in enumerate(spec.lines, start=1):
            data.append([
                str(n), line.name, line.qty,
                f"{Decimal(line.unit_price):,.2f}",
                f"{Decimal(line.line_total):,.2f}",
            ])
        data.append(["", "", "", "TOTAL",
                     f"{Decimal(spec.printed_total()):,.2f}"])
        table = Table(data,
                      colWidths=[10 * mm, 88 * mm, 16 * mm, 25 * mm, 28 * mm])

    last_line_row = len(spec.lines)          # row 0 is the header
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # The grid covers the LINE ITEMS only. The totals block below it is
        # ungridded, exactly as a printed bill has it -- which is part of why
        # a reader struggles to tell a subtotal from a net.
        ("GRID", (0, 0), (-1, last_line_row), 0.4, colors.grey),
        ("LINEABOVE", (-2, last_line_row + 1), (-1, last_line_row + 1),
         1.0, colors.black),
        ("FONTNAME", (-2, -1), (-1, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "<i>This is a synthetic sample bill generated for testing. It does not "
        "represent a real hospital, a real patient, or a real transaction.</i>",
        styles["Normal"],
    ))
    doc.build(story)


def write_noisy_jpg(spec: BillSpec, path: Path, grade: str = "heavy") -> None:
    """A degraded scan, for the reader-quality part of the demo.

    Two grades, and we need both:

      "mild"   a phone photo -- slight rotation, a soft shadow across one
               corner, reduced contrast, light compression. Real OCR should
               still read most of this, which is what makes the re-read pass
               a story worth telling: some lines come back low-confidence and
               get rescued.

      "heavy"  a bad fax-grade scan. Real Textract may return almost nothing
               from this. Useful as the failure case -- it shows what the
               system does when it genuinely cannot read something -- but on
               its own it is a weaker demo than a recoverable one.
    """
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    width, height = 1240, 780
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    draw.text((40, 30), HOSPITAL, fill="black")
    draw.text((40, 50), spec.title, fill="black")
    draw.text((40, 70), f"Date: {spec.bill_date}   (sample - no patient data)",
              fill="black")
    draw.line([(40, 95), (width - 40, 95)], fill="black", width=1)

    y = 115
    draw.text((40, y), "#   Particulars", fill="black")
    draw.text((760, y), "Qty", fill="black")
    draw.text((850, y), "Rate", fill="black")
    draw.text((1000, y), "Amount", fill="black")
    y += 25
    for n, line in enumerate(spec.lines, start=1):
        draw.text((40, y), f"{n}.  {line.name}", fill="black")
        draw.text((760, y), line.qty, fill="black")
        draw.text((850, y), f"{Decimal(line.unit_price):,.2f}", fill="black")
        draw.text((1000, y), f"{Decimal(line.line_total):,.2f}", fill="black")
        y += 26
    draw.line([(760, y + 6), (width - 40, y + 6)], fill="black", width=1)
    draw.text((850, y + 14), "TOTAL", fill="black")
    draw.text((1000, y + 14), f"{Decimal(spec.printed_total()):,.2f}", fill="black")

    # Seeded, so the artefacts are byte-reproducible across runs.
    rng = random.Random(20260916 if grade == "heavy" else 20260913)

    if grade == "mild":
        # A phone photo. Everything here is recoverable by real OCR.
        image = image.rotate(1.4, resample=Image.BICUBIC, fillcolor="white")

        # Soft shadow falling across one corner, as a hand or phone would cast.
        shadow = Image.new("L", (width, height), 255)
        shade_draw = ImageDraw.Draw(shadow)
        for offset in range(0, 380):
            value = 255 - int(58 * (1 - offset / 380))
            shade_draw.line([(width - 380 + offset, 0),
                             (width - 120 + offset, height)], fill=value)
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=55))
        image = Image.composite(
            image, Image.new("RGB", image.size, (150, 150, 150)), shadow
        )

        image = ImageEnhance.Contrast(image).enhance(0.78)
        image = ImageEnhance.Brightness(image).enhance(1.04)
        image = image.filter(ImageFilter.GaussianBlur(radius=0.45))

        pixels = image.load()
        for _ in range(int(width * height * 0.004)):
            x, y2 = rng.randrange(width), rng.randrange(height)
            shade = rng.randrange(150, 215)
            pixels[x, y2] = (shade, shade, shade)

        image.save(path, "JPEG", quality=72)
        return

    # "heavy": a bad scan. Possibly unreadable, deliberately.
    image = image.rotate(0.7, resample=Image.BICUBIC, fillcolor="white")
    image = image.filter(ImageFilter.GaussianBlur(radius=0.9))
    pixels = image.load()
    for _ in range(int(width * height * 0.02)):
        x, y2 = rng.randrange(width), rng.randrange(height)
        shade = rng.randrange(90, 190)
        pixels[x, y2] = (shade, shade, shade)
    image = image.filter(ImageFilter.GaussianBlur(radius=0.4))
    image.save(path, "JPEG", quality=38)


# --------------------------------------------------------------------------

def main() -> int:
    for directory in (FIXTURES, GROUND_TRUTH, DEMO_BILLS):
        directory.mkdir(parents=True, exist_ok=True)

    print("=" * 68)
    print("BillWise demo bills")
    print("=" * 68)

    for spec in BILLS:
        fixture = build_fixture(spec)
        truth = build_ground_truth(spec)

        (FIXTURES / f"{spec.bill_id}.json").write_text(
            json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
        (GROUND_TRUTH / f"{spec.bill_id}.json").write_text(
            json.dumps(truth, indent=2) + "\n", encoding="utf-8")
        write_pdf(spec, DEMO_BILLS / f"{spec.bill_id}.pdf")
        if spec.noisy_image:
            write_noisy_jpg(spec, DEMO_BILLS / f"{spec.bill_id}.jpg",
                            grade=spec.noisy_image)

        reds = len(truth["allowed_red_item_indexes"])
        grays = sum(1 for e in truth["expected"] if e["severity"] == "gray")
        print(f"  {spec.bill_id}  {len(spec.lines):>2} lines  "
              f"{len(truth['expected']):>2} expected findings  "
              f"({reds} red, {grays} gray)   {spec.title}")

    print()
    print(f"  Fixtures      -> {FIXTURES.relative_to(REPO_ROOT)}")
    print(f"  Ground truth  -> {GROUND_TRUTH.relative_to(REPO_ROOT)}")
    print(f"  PDFs and JPG  -> {DEMO_BILLS.relative_to(REPO_ROOT)}")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
