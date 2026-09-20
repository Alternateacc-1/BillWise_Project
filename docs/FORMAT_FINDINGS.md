# Bill-format findings

What breaks when a real bill meets the pipeline. Recorded **before** fixing
anything, so that each fix can be stated as a general rule rather than a
patch for the bill that exposed it.

**Rule for this document: findings are classes, not instances.** If a fix
cannot be written as "R6", "the ledger", or "a gate", it does not go in.

> **No real bill is stored in this repo.** Findings below are transcribed
> structure and arithmetic only. Patient names, addresses, contacts,
> registration numbers, doctors and invoice numbers from real bills are never
> reproduced, in fixtures or in notes.

---

## Probe 1 — retail pharmacy sale bill (real, anonymised)

An OPD pharmacy sale bill, photographed. 6 lines. Columns:

```
PARTICULARS | HSN | MFG BATCH | EXP | MRP | PACK | QTY | CGST | SGST | TOTAL
```

Totals block: `Bill Amount 453.94` → `Discount 22.70` → `Round Off (-) 0.24`
→ `Net Amount 431.00`.

Its arithmetic is internally perfect: the six line totals sum to 453.94
exactly, and 453.94 − 22.70 − 0.24 = 431.00 exactly.

**Result: 0 false reds, and 0 of 6 lines readable. Every line gray.**

Safe, and useless. Three classes.

---

### Class A — "absent" is being treated as "wrong"

**The bill prints no unit-price column at all.** This is a completely ordinary
Indian pharmacy layout: it prints MRP, PACK, QTY and TOTAL, and expects you to
divide. Our verifier rejected every line for three separate reasons, each of
which conflates *a value not existing* with *a value being untrustworthy*:

1. `readers_disagree_on_unit_price` — both readers returned `None`, and
   `_close(None, None)` is `False`. **Two readers agreeing that a field is
   absent is not a disagreement.**
2. `arithmetic_not_checkable:missing_values` — `arithmetic_holds()` returns
   `None`, and `verify_item` requires it to be `True`. So a bill that does
   not print the inputs to the arithmetic check fails the arithmetic check.
3. `outside_sanity_bounds` — `within_sanity_bounds()` returns `False` when
   `unit_price` is `None`, so a missing field reads as an implausible one.

**Class fix (a gate, not a patch):** the verifier must distinguish
*unavailable* from *disagreeing* and from *implausible*. A check that cannot
run should abstain, not fail. Applicability is not the same as passing.

This is the single highest-value fix on the list: it is the difference
between this bill being useless and being fully readable.

---

### Class B — a totals block is a ledger, not a number

The reader has no way to know which printed number is "the total". Both
candidates appear on the bill:

| Reader takes… | Result |
|---|---|
| `Net Amount 431.00` (what was actually paid) | **R2 false mismatch of ₹22.94** |
| `Bill Amount 453.94` (the pre-adjustment subtotal) | reconciled |

₹22.94 is exactly the discount plus the round-off. The bill is perfectly
consistent; we simply compared the line sum against the wrong line of the
ledger.

**Class fix (the ledger):** model the totals block as
`subtotal → labelled adjustments[] → grand_total`, and make R2 two checks
that name which step broke. Covers discount, round-off, IGST, CGST+SGST and
bill-level charges with one structure.

---

### Class C — the bill supplies facts we declared unknowable

Two columns we do not currently read:

- **`PACK`** — units per pack: 15, 10, 10, 10, 20, 1. This is *exactly* the
  fact the upper-bound gate exists because bills usually omit. When it is
  printed, the per-unit price is fully determinable and the item can get a
  real verdict instead of "price could not be determined".
- **`MRP`** — a per-line maximum retail price, on the same unit basis as the
  line. This is R6, and it needs no pack-size knowledge at all.

Worth noting how well these agree: `252.19 ÷ 15 = ₹16.81/capsule`, and
`134.48 ÷ 8 = ₹16.81/capsule`. The pharmacy charged exactly MRP per unit.
A correct system should be able to say that — quietly, as a green.

**Class fix:** R6 from a printed MRP column; `PACK` feeds `pack_count` with
`pack_count_source="bill_text"`, i.e. CERTAIN.

---

### Class D — the bill states its own GST slab

Per-line `CGST 2.5%` + `SGST 2.5%` = **5% GST**, printed on the bill.

We assume 12% because bills "rarely say which" (LIMITS.md, limit 4). This one
says. When a bill states its slab, using our assumption instead of its
statement is choosing a guess over evidence.

**Class fix:** when a per-line or bill-level GST rate is printed, use it and
record in the evidence that it came from the bill rather than from config.
Fall back to the 12% assumption only when nothing is stated.

---

## Probe 1a — the same bill, read as its NET total

Not a new format: the same bill as Probe 1, showing what Class B costs.

A reader has no way to know which printed number is "the total". Run both:

| Reader takes | Result |
|---|---|
| `Bill Amount 453.94` | 0 findings, **bill total reconciled** |
| `Net Amount 431.00` | **1 finding, Rs 22.94**, bill total mismatch |

Rs 22.94 is exactly `Discount 22.70 + Round Off 0.24`, both printed one line
above `Net Amount`. The bill is perfect. We generated a polite, well-worded
question to a pharmacy that did nothing wrong.

**This is worse than Class A.** Class A produces silence, which is safe.
Class B produces a WRONG QUESTION, on the commonest retail layout in India.

Also confirmed from the printed `MRP` and `PACK` columns: every line is billed
at or fractionally BELOW its MRP.

| Item | MRP / PACK | billed / QTY |
|---|---|---|
| PANTOCID DSR CAP | 16.8127 | 16.8100 |
| OFIVAY OZ TAB | 13.4000 | 13.4000 |
| SINALATE TAB | 6.7500 | 6.7500 |
| EFERIM SP TAB | 9.7970 | 9.7900 |
| BECOSULE CAP | 3.1185 | 3.1100 |
| MEDINOZE NASAL SPRAY | 67.5000 | 67.5000 |

**The correct verdict on this bill is six greens and nothing to ask about.**
Now a permanent fixture: `bill_06`.

---

# The format experiment (2026-09-18)

Six further formats, run through the engine with a DELIBERATELY PERFECT read.
Reading quality is not the variable here — the question is what the ENGINE
does with a shape it has never seen, given flawless input.

**Headline: 0 false REDS across every format.** The strongest claim survives
everything below. What does not survive is the amber band and the silence.

| Probe | Format | red | amber | green | gray | Verdict |
|---|---|---|---|---|---|---|
| P2 | Wholesale B2B, per-strip pricing | 0 | 0 | 0 | 3 | safe, silent |
| P3 | Diagnostic lab bill | 0 | 0 | 0 | 5 | safe, mislabelled |
| P4 | Thermal receipt, no qty/rate | 0 | 0 | 0 | 3 | safe, silent |
| P5 | Multi-page, section subtotals | 0 | **1** | 2 | 6 | **FALSE, Rs 11,368** |
| P6 | GST-exclusive line pricing | 0 | **2** | 1 | 1 | **FALSE, Rs 40.68** |
| P7 | Per-line discount column | 0 | **2** | 0 | 2 | **FALSE, both** |

Five new classes. In severity order.

---

### Class E — a printed SUBTOTAL row read as a line item

**The single worst result in the experiment.** P5 is an ordinary multi-page
hospital bill with `SUBTOTAL - ROOM & NURSING`, `SUBTOTAL - PHARMACY` and
`SUBTOTAL - LABORATORY` rows before the grand total.

The reader returns those rows as line items, because on the page they look
exactly like line items — a label and an amount. The line sum becomes
Rs 22,736.00 against a printed total of Rs 11,368.00, and R2 fires:

```
R2 AMBER  item -1  amount affected 11368.00
```

**The amount affected is the entire bill.** Every rupee, flagged, on a bill
that adds up perfectly. A user shown this has been told their whole bill is
in question.

**Class fix:** a row whose amount equals the sum of the rows above it since
the last subtotal is a SUBTOTAL, not a charge. Detect it structurally and
exclude it from the line sum. This belongs in the ledger (fix 3) — the same
structure that models `subtotal -> adjustments[] -> grand_total` must also
model *section* subtotals. **Never match on the word "SUBTOTAL"** — that is a
fix by instance and it dies on the first bill that says "Total (Pharmacy)".

---

### Class F — a per-line discount makes the arithmetic "fail"

P7 prints `qty`, `rate`, a discount column, and a line total that is
`qty * rate - discount`. R1 checks `qty * rate == line_total`, so both lines
come back as arithmetic failures:

```
R1 AMBER item 1  amount 35.00     R1 AMBER item 2  amount 2.00
```

Both are false. The bill is correct; we are checking an equation the bill
never claimed.

**Class fix:** the ledger again, one level down. A line is
`qty * rate -> line adjustments[] -> line_total`. R1 must name which step
broke, and must ABSTAIN when the line carries an adjustment it cannot read —
Class A's rule applied per line. Class B, E and F are all the same bug at
three scales, which is why they get one structure and not three patches.

---

### Class G — we do not know whether a line price includes GST

P6 prints rates ex-GST and adds 12% once at the bottom. Two failures:

1. **A false R2 of Rs 40.68** — exactly the GST. The lines sum to 339.00, the
   printed total is 379.68, and we call that a mismatch.
2. **Silent under-flagging, which is the dangerous half.** The gate compares
   the billed per-unit against `ceiling_ex_gst * 1.12`, i.e. it ASSUMES the
   billed figure already includes GST. When it does not, we compare an
   ex-GST price against a GST-inclusive allowance and let roughly 12% of
   excess through unflagged. Nothing on screen says we did this.

MRP is always GST-inclusive in India, so the assumption holds for retail — and
fails for exactly the hospital bills where the money is larger.

**Class fix:** make the GST basis of a line an explicit, recorded field with
three states — inclusive, exclusive, unknown. On `unknown`, state the
assumption in the evidence. This is Class D's sibling: Class D is *which
slab*, Class G is *whether it is in there at all*.

---

### Class H — a finding worth Rs 0.00

P6 line 1 produced this:

```
R5 AMBER item 1  amount affected 0.00
```

`audit.py` decides WHETHER to flag from the highest interpretation
(`any_reading_above_amber`) but computes the AMOUNT from the `decisive` one.
When the pack size is ambiguous those are different interpretations, so a flag
is raised on one reading and priced from another.

The UI then renders *"We found 1 thing worth asking about, worth Rs 0.00"* —
the incoherent sentence, and it also inflates the findings count.

**Class fix:** one interpretation decides both, or the flag states plainly
that the amount depends on a pack size we do not know. A finding whose amount
is zero must not be a finding. **Add it to the eval as its own assertion:
no flag may carry `amount_affected == 0`.**

---

### Class I — a feature reported as a failure

P3 is a diagnostic lab bill. Nothing on it is price-controlled, so every line
should be `no_public_ceiling` — the "feature, not a gap" answer. Two were not:

```
HbA1c                      -> could_not_identify
Sample Collection Charges  -> could_not_identify
```

`could_not_identify` means WE FAILED. `no_public_ceiling` means the item is
genuinely outside NPPA's remit. A lab test and a collection fee are the
second, and calling them the first overstates our own unreliability — the
mirror image of a false positive, and it corrupts the one gray split we
report to users.

**Class fix:** when an item resolves to a category that is out of scope by
nature (lab test, service charge, room, nursing), that is
`no_public_ceiling`. Reserve `could_not_identify` for a thing we believe IS a
medicine or device and still could not resolve.

---

### Class J — no quantity and no rate column at all (Class A, harder)

P4 is a thermal till receipt: a name and an amount, nothing else. All three
lines come back `could_not_read`.

Class A's rule handles it — a check that cannot run should abstain — but with
no quantity, a per-unit price cannot be derived at all, only bounded. This is
the format where the **units-per-pack user input** stops being a nicety.

**Class fix:** Class A first, then treat a line with a total but no quantity
as quantity = 1 for the UPPER BOUND only. Never for a red.

---

## What this changes

Nothing here weakens "zero false reds" — that held on every format, including
the ones built to break it. Three things do change:

1. **The ledger (fix 3) now covers B, E and F.** One structure, three scales:
   bill totals, section subtotals, line adjustments. It is the highest-value
   item on the list and it is no longer co-equal with Class A — it is first.
2. **Class H is a one-line eval assertion** and should land immediately,
   because it is a correctness bug in the number we put on screen.
3. **Class G is the only one that can cause silent UNDER-flagging.** Everything
   else fails loud or fails silent-but-safe. Worth its own test.

Order: ledger (B/E/F) -> Class A + H -> Class G -> R6 -> Class C/D -> I -> J.

---

---

# The format experiment, round 2 (2026-09-19)

Five more formats. Same method: a deliberately perfect read, so what breaks is
the engine and not the reader.

| Probe | Format | red | amber | Verdict |
|---|---|---|---|---|
| P8 | Insurance / TPA co-pay split | 0 | **1** | **FALSE — Rs 15,280** |
| P9 | Return line (negative amount) | 0 | 0 | safe, reconciled |
| P10 | Package / bundle line | 0 | 0 | safe |
| P11 | Fractional quantity (0.5 vial) | 0 | 0 | **MISSED a 2x overcharge** |
| P12 | Zero-amount / waived lines | 0 | 0 | safe, no divide-by-zero |

Still **zero false reds**, now across eleven formats. Two new classes, and one
of them is the first structural UNDER-flag the experiment has produced.

---

### Class K — the printed total is the patient's SHARE, not the bill

**The largest false finding yet, and a different bug from B/E/F.**

An insurance/TPA bill lists Rs 19,100.00 of goods and services, the insurer
pays 80%, and the number printed at the bottom — the number the patient
actually owes — is their Rs 3,820.00 co-pay. R2 compares the line sum against
it and fires:

```
R2 AMBER  item -1  amount affected 15280.00
```

Rs 15,280 is exactly the insurer's 80%. **We flagged the part of the bill the
patient was never asked to pay**, on a bill that is entirely correct.

This is NOT the ledger bug. B, E and F are all "we compared against the wrong
row of an arithmetic chain". Here the printed total is a **different quantity
altogether** — a share of the bill, not a subtotal of it. No amount of
subtotal-and-adjustment modelling reaches it.

**Class fix:** the grand total must be TYPED, not just located. `sum_of_lines`,
`net_payable` and `patient_share` are three different things, and R2 may only
compare like with like. When the type cannot be determined, R2 must ABSTAIN —
Class A's rule at bill level. A reconciliation we cannot perform is not a
reconciliation that failed.

---

### Class L — a fractional quantity turns an overcharge into silence

The first structural **under-flag** found by the experiment, and the reason it
matters more than its size suggests.

```
Meropenem 1000 MG Injection | qty 0.5 | rate 1702.86 | total 851.43
```

Half a vial. The implied price for one full vial is Rs 1,702.86 against an
NPPA special-feature ceiling of Rs 851.43 — **exactly 2x**, the cleanest
overcharge in the whole experiment.

Verdict: **gray, `pack_size_unknown`. We said nothing.**

The upper-bound gate divides by `qty * pack_count`. With `qty = 0.5` the
divisor drops below one, so a second interpretation (`N = 2`) sits exactly at
the ceiling, `every_reading_above_red` is false, and the gate does what it was
built to do — declines to speak when one reading is compliant.

The gate is not wrong. It is being fed a quantity that is not a count of
packs. **A fractional quantity means "part of one unit", which makes
`pack_count = 1` CERTAIN, not unknown** — you cannot buy half a vial out of a
box of ten.

**Class fix:** `qty < 1` implies `pack_count_source = CERTAIN, pack_count = 1`.
This narrows the gate rather than widening it, so it cannot introduce a false
red. **Add the Meropenem half-vial as a named regression test** alongside the
existing `test_meropenem_strength_inversion` — this file already records that
Meropenem is where pack and strength assumptions go to die.

---

### Three confirmations of Class A, in formats that look unrelated

None of these is a new class. All three are the same rule — *a check that
cannot run should abstain, not fail* — showing up where it was not expected:

- **P9, a return line** (`qty -5`, `total -100.00`): `could_not_read`. A
  negative quantity is legitimate on any bill with a return, and it is being
  treated as implausible. The bill still **reconciled correctly**, which is
  the encouraging half.
- **P12, a waived line** (`rate 0.00`, `total 0.00`): `could_not_read`. Free
  is a price. It also confirms there is **no divide-by-zero** anywhere in the
  per-unit path, which was the thing worth checking.
- **P10, a package line** (one price covering a room, an OT and consumables):
  correctly `no_public_ceiling`. Nothing to fix — recorded because a bundle
  price is genuinely not decomposable, and that is a limit, not a bug.

---

## Revised order after round 2

Unchanged at the top: **the ledger (B/E/F) first, then Class A + H.** Round 2
adds two items and moves nothing above them.

1. **Ledger** — B, E, F. Three scales, one structure.
2. **Class A + H** — abstain instead of fail; no flag worth Rs 0.00.
   Class A now also buys P9's returns and P12's waived lines.
3. **Class K** — type the grand total. Same shape as the ledger and probably
   the same commit: `sum_of_lines` / `net_payable` / `patient_share`, and R2
   abstains when the type is unknown.
4. **Class L** — `qty < 1` implies `pack_count = 1`, CERTAIN. Small, and it
   closes the only clean under-flag we have found. Regression-test it.
5. **Class G** — the GST basis of a line. The other under-flag, and the
   quieter one.
6. **R6**, then Class C/D, then I, then J.

**Eleven formats, zero false reds.** The claim has now survived formats built
specifically to break it. What it has not survived is the amber band: five of
eleven formats produced a false amber, and every one traces to comparing two
numbers that were never the same kind of number.

---

---

# The first REAL reading measurement (2026-09-19, deployed)

Everything above this line describes hand-written fixtures. This section is
the first time Textract and Claude read an actual image, on the deployed
stack. **It is the section that replaces the fixture numbers in the video.**

## What was run

Three files through `POST /bills` on the live API, then the stored reports
pulled back from DynamoDB and compared against ground truth line by line.

| File | `items_read` | Ground truth |
|---|---|---|
| `bill_02.jpg` — mild scan | 7 | 7 lines |
| `bill_05.jpg` — fax-grade scan | 2 | 3 lines |
| `bill_06.pdf` — retail layout | 6 | 6 lines |

**`items_read` matched ground truth on two of three. That number is
worthless, and believing it would have been the single worst mistake
available.** It counts ROWS RETURNED, not rows read correctly.

## Finding 1 — the column header is read as a line item, shifting every name

`bill_02.jpg`, read vs ground truth:

| # | Name read | Qty | Rate | Total | Whose numbers these are |
|---|---|---|---|---|---|
| 1 | **"Particulars"** | 15 | 2.00 | 30.00 | line 1 — the name is the COLUMN HEADER |
| 2 | Paracetamol 650mg Tablet | null | 7.40 | **7400** | line 2 |
| 3 | Amoxicillin 500mg Capsule | 20 | 1 | 22.00 | line 3 |
| 4 | Paracetamol 500mg Tablet | 2 | 11.50 | 23.00 | line 4 |
| 5 | "4 Acimol500mg Tablet" | 10 | 8.50 | 85.00 | line 5 |
| 6 | Pantoprazole 40mg Tablet | null | 85.00 | 85.00 | line 6 |
| 7 | Cotton Roll 100gm | 2 | 45.00 | 90.00 | line 7 |

Textract read the `PARTICULARS` header as a line item. Every subsequent drug
name landed on the NEXT row's numbers. `Micropore Tape` was dropped entirely.

**Not one of the seven rows has the right name against the right numbers**,
and yet `items_read` was a perfect 7 of 7.

**This is Class E's sibling.** Class E is a SUBTOTAL row read as a line item;
this is a HEADER row read as a line item. Same shape, same fix family: a row
whose cells are not values is not a charge. Detect it structurally -- a row
with no parseable amount in the amount column, appearing before any line -- and
never by matching the word "Particulars", which dies on the first bill saying
"Item" or "Description".

## Finding 2 — a lost decimal point is Textract's dominant failure mode

`bill_05.jpg`, line 2. Ground truth `7.20` per unit, `72.00` total:

```
unit_price  "7"        (should be 7.20)
line_total  "7200"     (should be 72.00)  <- 100x
```

Same pattern on `bill_02.jpg` line 2: `74.00` read as `7400`.

A lost decimal is a **100x error**, and it is far more dangerous than an
unreadable field, because it is perfectly plausible as a number.

## Finding 3 — the guards held, and this is the result that matters most

Despite every line of `bill_02.jpg` being misattributed:

**ZERO FALSE REDS.** Measured on real OCR, not asserted.

The mechanism is worth stating precisely, because it is the whole design:

  - The two readers DISAGREED on the shifted names
    (`readers_disagree_on_name:similarity=34`), so every line came back
    `unverified_reading` and went gray.
  - Misaligned names did not resolve against NPPA data
    (`name_did_not_resolve`), so no ceiling was ever selected.
  - R5, the price rule, never fired on bad data. The `<=50x` sanity guard is
    exactly what stops a lost decimal becoming an accusation about price.

**Garbage in, silence out.** The system was comprehensively wrong and said
almost nothing, which is the behaviour it was built for.

## Finding 4 — but the ARITHMETIC rules produced two large false ambers

`bill_05.jpg`, on a bill whose true total is Rs 190:

```
R1 amber  item 2      amount_affected  7130.00
R2 amber  whole bill  amount_affected  7018.80
```

Both are arithmetically correct and both are nonsense: 10 x 7 really does not
equal 7200. The engine faithfully reported a discrepancy invented by OCR.

A user would see **"Rs 7,130 may need clarification"** on a Rs 190 bill.

**This is the gap the two-reader check does not cover.** R1 and R2 operate on
NUMBERS, and the numbers were internally consistent nonsense -- there was
nothing for a second reader to disagree with. The name check saved the price
rules; nothing equivalent protects the arithmetic rules.

**Class fix:** an arithmetic rule must not fire on a line whose reading is
`unverified_reading`. R5 already refuses to price an unverified line; R1 and
R2 do not refuse to do arithmetic on one. That asymmetry is the bug.
Additionally, a line total that exceeds the printed grand total is not a
discrepancy -- it is a misread, and should be gray.

## What is ours to claim, after this

**Legitimately ours, now measured on real OCR rather than fixtures:**

  - zero false REDS on genuinely misread bills
  - the two-reader disagreement check catches column misalignment
  - the <=50x ratio guard stops a lost decimal reaching a price verdict

**NOT ours, and not to be repaired by rewording:**

  - any claim about reading accuracy. On a degraded scan it is poor.
  - "7 of 7 lines read" -- FALSE. Seven rows, one a header, none correctly
    attributed. **`items_read` must never appear as an accuracy number.**

**Still unmeasured:** `bill_06.pdf` (the retail layout) was read as 6 rows,
but the report could not be retrieved, so whether MRP and PACK come back as
usable fields is still unknown. That answer decides how much of Class B and
Class C we get for free.

---

## bill_06.pdf on the deployed stack — the retail layout, answered

The last open question from the Textract probe. `bill_06.pdf` is the layout
copied from a real OPD pharmacy bill: MRP, PACK, QTY, TOTAL, no unit-price
column, Discount and Round Off in the totals block.

### Textract read it almost perfectly

| # | Name | Qty | Line total | Correct? |
|---|---|---|---|---|
| 1 | PANTOCID DSR CAP | 8 | 134.48 | yes |
| 2 | OFIVAY OZ TAB | 8 | 107.20 | yes |
| 3 | SINALATE TAB | 8 | 54.00 | yes |
| 4 | EFERIM SP TAB | 8 | 78.32 | yes |
| 5 | BECOSULE CAP | 4 | 12.44 | yes |
| 6 | MEDINOZE NASAL SPRAY | 1 | 67.50 | yes |

**Six of six names, quantities and totals correct.** Sum 453.94, matching the
printed Bill Amount exactly. On a clean PDF, Textract is excellent — the
earlier failures were all on degraded photographs.

### Three findings, all previously predicted, now confirmed on real OCR

**1. MRP and PACK do NOT survive.** `unit_price` is `null` on all six lines.
AnalyzeExpense returned the columns it recognises as line-item fields and
dropped the rest. **Class C is NOT free** -- R6 needs work, not just wiring.

**2. Textract takes the NET amount as the total.** `printed_grand_total` came
back `431.00`, not the `453.94` subtotal. This is exactly the reading that
triggers Class B, and it did:

```
R2 amber  whole bill  amount_affected 22.94
```

Rs 22.94 = Discount 22.70 + Round Off 0.24. **A false finding, on the
deployed system, against a bill that is arithmetically perfect.** Predicted
from the local probe; now measured live.

The new misread invariant did not catch this and should not have: no line
exceeds the bill total, and the numbers are all real. This is a genuine
ledger-modelling gap, not a reading error.

**3. Not one brand name resolved.** All six returned `name_did_not_resolve`:
PANTOCID DSR, OFIVAY OZ, SINALATE, EFERIM SP, BECOSULE, MEDINOZE.

**This settles the brand-index question empirically.** The measurement on
2026-09-19 showed the 36 MB index changes NOTHING across all six fixtures --
because the fixtures use generic names. A real retail bill is ENTIRELY brand
names, and without the index none of them resolve to an NPPA formulation. The
index is load-bearing exactly where the fixtures cannot see it, and it is
currently NOT DEPLOYED.

### What it would take for this bill to return six greens

All three, in this order, and none is optional:

1. **Class B / the ledger** -- stops the false Rs 22.94 question. This is the
   only one that is actively WRONG today rather than merely silent.
2. **Class A** -- a missing unit-price column must not make a line unreadable.
   Today it produces `arithmetic_not_checkable:missing_values` AND
   `outside_sanity_bounds` on every line.
3. **Brand resolution** -- the DynamoDB brand index, which has never been
   written. Without it the lines become readable but still unpriceable.

Class A alone is not enough. That is new information: the local probe could
not show it, because the local fixture bypasses brand resolution entirely.

---

---

# Adversarial audit (2026-09-19)

Goal: **actively construct a bill that makes BillWise emit a FALSE RED.** Not
a regression suite -- an attack. Every bill below is CORRECTLY PRICED, so any
red is a false accusation of a hospital or pharmacy.

Harness: `eval/adversarial_audit.py`. Deliberately NOT in the eval gate --
their expected outcome is "nothing fired", and encoding that as ground truth
would turn an absence of evidence into a passing test.

**Result: 0 false reds in 15 attacks. One false AMBER, on the most ordinary
bill line in India.** The near-misses matter more than the total.

## Round 1 -- attacks against the system as deployed

| # | Attack | Outcome |
|---|---|---|
| A1 | Strip of 10 at ceiling read as ONE unit (8.9x, under the 50x guard) | gray `pack_size_unknown` |
| A2 | Ratio engineered to 45x, just under the guard | gray `pack_size_unknown` |
| A3 | OCR digit substitution 1 -> 7, SINGLE reader at 99% confidence | gray `pack_size_unknown` |
| A4 | Decimal shift 1.10 -> 11.00, single reader | gray `pack_size_unknown` |
| A5 | Ringer Lactate 500 ml bag vs the dearer-per-ml 100 ml ceiling | **green** (correct row selected) |
| A6 | `ASPIRIN TAB` via the new alias table vs the cheaper DT row | gray `pack_size_unknown` |
| A7 | GST-inclusive rate presented as ex-GST | **green** |
| A8 | Bill-level discount against a compliant line | **2 green** |
| A9 | Pack nesting where every interpretation looks excessive | gray `pack_size_unknown` |
| A10 | Brand alias reaching a modified-release ceiling | gray (unresolved) |

**The uncomfortable part of a clean sheet: SIX of ten were stopped by the SAME
gate.** `pack_size_unknown` is doing nearly all the work, and Class C exists
specifically to open it. A defence with one load-bearing member is not as
strong as its score suggests.

A5 and A7 are genuine passes worth noting. A5 selected the 500 ml row rather
than the dearer-per-ml 100 ml row -- the Phase 0 regression holding under
attack. A7 stayed green because a GST-inclusive rate compared against a
GST-inclusive allowance is the CORRECT comparison; the error runs the other
way (Class G, under-flagging), which is the direction we chose.

## Round 2 -- attacking the system AFTER Class C lands

Round 1 said almost nothing about the future, so round 2 supplies a known
`pack_count` and re-runs. **The first attempt was INVALID and is recorded
because the invalidity was itself the finding.**

### NEAR-MISS 1: `pack_count` as `unit_qty` kills the ceiling lookup

Setting `pack_count_source="bill_text"` -- exactly what Class C will do --
made the CONTROL and the TRUE POSITIVE both come back gray. The pricing rule
never ran, so "0 false reds" from that run meant nothing.

Cause, at `audit.py:747`:

```python
unit_qty=norm.pack_count if norm.pack_count_source == "bill_text" else Decimal("1")
```

`unit_qty` means **the CEILING ROW's unit quantity** ("1 tablet", "500 ml"),
not a pack count. Feeding it 10 searches for a ceiling priced per-ten-tablets,
which does not exist:

```
unit_qty=1   -> FOUND 0.93
unit_qty=10  -> NO CEILING FOUND
unit_qty=15  -> NO CEILING FOUND
```

**Dead code today**, because nothing sets `pack_count_source="bill_text"` yet.
It activates the instant Class C reads the PACK column, and would turn every
packed tablet from green to GRAY -- the exact opposite of Class C's purpose.
Not a false red. A false SILENCE, and a trap laid for the next change.

### NEAR-MISS 2 -- **THE REAL FINDING**: a false amber on a compliant line

With a working lookup and `pack_count=10` from the brand index:

```
THE BILL: one strip of 10 tablets at Rs 1.00/tablet = Rs 10.00   COMPLIANT
          ceiling 0.93/tab, allowance 1.0416 -- the line is UNDER it

per_billed_unit   divisor=1    per_unit=10.00   <- over allowance
per_pack_unit     divisor=10   per_unit=1.00    <- compliant, and TRUE

VERDICT: R5 AMBER, amount_affected Rs 0.00
```

**A perfectly compliant line, with a pack size we KNOW, flagged.** And flagged
for Rs 0.00 -- Class H, still open, now shown firing on innocent lines rather
than only on ambiguous ones.

Reproduced across the round-2 set:

| # | Attack | Outcome |
|---|---|---|
| C1 | **CONTROL: pack 10, priced AT ceiling** | **FALSE AMBER Rs 0.00** |
| C2 | True positive, genuinely 4.8x over | amber Rs 39.58 (correct, but *downgraded from red*) |
| C3 | Pack misread 100 -> 10 | false amber Rs 89.58 |
| C4 | Pack misread 50 -> 10, under the 50x guard | false amber Rs 36.08 |
| C5 | Same numbers, pack unknown (today) | gray `pack_size_unknown` |

## THE CLASS, and the rule proposed

**Class M -- an interpretation we have evidence AGAINST must not raise a flag.**

`_interpretations()` always emits `per_billed_unit` (divisor = 1), treating
the billed quantity as a count of base units. When `pack_count` is known,
that reading is not merely unlikely -- **we hold evidence that contradicts
it.** A strip of 10 is not 1 tablet, and we know it is 10.

The gate currently asks "does ANY reading exceed the allowance?" It should ask
"does any reading WE STILL BELIEVE exceed the allowance?"

**Proposed rule:** when `pack_certainty` is CERTAIN or BOUNDED and
`pack_count > 1`, the `per_billed_unit` interpretation is dropped, not merely
outvoted. It survives only when `pack_count == 1`, where the two readings
coincide anyway.

**Why this is safe rather than a loosening.** It removes an interpretation
that is *known false*, so it cannot manufacture a red that a true reading
would not support. It NARROWS what the system will say, in the direction of
silence -- the same direction as every other guard here. It also restores
C2 to the red it should be: with the nonsense reading gone,
`every_reading_above_red` becomes true on a line that genuinely is 4.8x over.

**Consequence worth stating plainly:** this makes the system flag MORE on
genuinely excessive lines with known pack sizes, and LESS on compliant ones.
Both directions are improvements, but the first increases exposure and
deserves its own eval pass before it ships.

**NOT PATCHED. Awaiting approval**, per the audit's own rule: state the class,
propose the general rule, change nothing.

## What was NOT tried, and should be

- Synonym-tier crossing where the tier-2 row is CHEAPER than the true tier-1
  row (A6 was blocked by the pack gate before it could test the collision)
- A bill where two different lines resolve to the same ceiling row
- Negative quantities combined with a known pack size
- A line whose `form_modifier` is present on the bill but absent from the
  index row, and vice versa

---

---

# The accidental controlled experiment (2026-09-19)

**The same bill, read by the deployed system twice, two hours apart. The only
variable that changed was whether the second reader was available.**

Bedrock stopped working mid-session: the account cannot complete the AWS
Marketplace subscription for the model (`INVALID_PAYMENT_INSTRUMENT: A valid
payment instrument must be provided`). Credits do not satisfy a Marketplace
subscription. Textract was unaffected, so the primary reading is identical.

This is the cleanest evidence the project has for its own architecture, and
nobody designed it.

## `bill_02.jpg`, both ways

| | 22:46 UTC — TWO readers | 00:4x UTC — ONE reader |
|---|---|---|
| Line 1, `"Particulars"` (the column HEADER) | `readers_disagree_on_name:34` -> gray | **`confidence: high`** |
| Line 3, Amoxicillin `20 x "1" = 22.00` | `readers_disagree_on_name:57` -> gray | **`R1 amber Rs 2.00`** |
| Lines rated HIGH confidence | **0 of 7** | **4 of 7** |
| Findings reported | **0** | **1, and it is FALSE** |

## The false finding, in detail

Ground truth for line 3 is `20 x 1.10 = 22.00`. **The bill is correct.**
Textract lost the decimal and read `1.10` as `1`, so `20 x 1 = 20` and the
arithmetic rule reported a Rs 2.00 discrepancy that does not exist.

With a second reader, that line never reached the rule: the readers disagreed
on the name, the line went `unverified_reading`, and R1 abstained.

Note also line 1. `"Particulars"` is a COLUMN HEADING. With one reader it is
now `confidence: high` and classified as an unidentified medicine. The system
is confidently wrong about what the line even is.

## What it demonstrates, precisely

**A single reader cannot doubt itself.** Textract returned the same values
both times, with per-field confidences of 96-99. Nothing in that output
signals the decimal loss or the column shift. Confidence is not accuracy, and
a reader's own score cannot detect a systematic misalignment.

**Disagreement is the signal.** The second reader is not there to be more
accurate than the first. It is there to DISAGREE, and disagreement is what
converts a confident misread into an honest silence.

**The cost of losing it is a false accusation, not a missed finding.** Both
degradations here run toward saying MORE, not less: four lines promoted to
high confidence, and one amber raised against a correct bill.

## Consequences for what may be claimed

**Claimable, and now measured rather than argued:** the two-reader
cross-check catches confident misreads that no single-reader confidence
score exposes. Both sides of the comparison are recorded in the deployed
system's own stored reports.

**NOT claimable while the subscription is unresolved:** that the DEPLOYED
system currently performs this check. It does not. Every bill uploaded now
gets one reader, and `only_one_reader_ran` appears on every line saying so.

The honest sentence, and it must be said in the video if the claim is made:

> The two-reader design is implemented and measured. The deployed demo is
> currently running one reader, because the AWS account cannot complete the
> Marketplace subscription for the model.

## Resolution

A valid payment method on the AWS account. Anthropic models on Bedrock are
Marketplace subscriptions, and credits alone do not satisfy one. This is the
only blocker found tonight that is not fixable in code.

**The PDF document-block fix is UNTESTED, not disproven.** It never got far
enough to fail on its own terms -- the same AccessDeniedException occurs for
JPEG, which previously worked.

---

---

# A6 -- synonym-tier crossing, enumerated and attacked (2026-09-19)

D4 accepted an asymmetry on the grounds that its impact stayed inside the 25%
red margin. That was an observation about ASPIRIN. This tests whether it holds
across the whole published list.

Harness: `eval/cross_tier_audit.py`.

## Part 1 -- the enumeration, and it is a much stronger claim than D4's

Every salt+form+strength+unit group in the 915 usable ceiling rows was grouped
by its SYNONYM-canonical key, then split by EXACT spelling. Any group holding
more than one exact spelling is a place where the two tiers can see different
rows, and therefore different ceilings.

**Result: exactly ONE such group exists in the entire published list.**

| Group | Tier 1 (exact) | Tier 2 (synonym) | Gap |
|---|---|---|---|
| `aspirin`, tablet 75 mg, per 1 tablet | **0.3600** dispersible `CEIL-0214` | **0.3900** plain `CEIL-0009` | **8.3%** |

  groups where the tiers disagree : 1
  red margin                      : 25%
  gaps EXCEEDING the margin       : 0
  widest gap measured             : 8.3%

**D4's asymmetry is now BOUNDED, not merely accepted.** No cross-tier
disagreement in the published data is wide enough to change a verdict, because
the widest is 8.3% against a 25% margin -- a factor of three of headroom. The
aspirin note stops being an anecdote about one drug and becomes a measured
property of the reference data.

**This bound is a property of the DATA, not of the code**, and it must be
re-measured whenever the reference list is rebuilt. If NPPA ever publishes a
cross-tier pair wider than 25%, the asymmetry becomes capable of producing a
red and D4 must be revisited. `eval/cross_tier_audit.py` exists so that check
is one command.

## Part 2 -- the attacks, with the pack gate stubbed

The previous A6 attempt proved nothing: `pack_size_unknown` blocked it before
the ceiling comparison ran. Setting `pack_count=1` from `bill_text` makes the
pack CERTAIN and collapses the interpretations to one, so the pricing path
actually executes.

| # | Attack | Result |
|---|---|---|
| A6a | Aspirin priced AT the plain-row ceiling, gated on the DT row | **amber Rs 0.03** |
| A6b | Same, just under the tier-1 red threshold (0.504) | **amber Rs 0.10** |
| A6c | Two lines resolving to the SAME ceiling row | 2 green |
| A6d | `form_modifier` on the bill, absent from every matched row | gray |

**FALSE REDS: 0.**

### NEAR-MISS: the asymmetry does cost an amber

A6a is a line priced exactly at the ceiling that genuinely governs it -- the
plain 75 mg tablet at Rs 0.39 ex-GST -- and it comes back AMBER, because
"Aspirin" matches tier 1, which holds only the dispersible row at Rs 0.36.

The amount affected is **Rs 0.03**. It cannot become red: the 25% margin
needs Rs 0.504 and `RED_MIN_AMOUNT_AFFECTED` needs Rs 50, so this is doubly
blocked. But it IS a flag on a compliant line, and D4 should say so rather
than implying the asymmetry is free. It costs an amber, not a red.

Worth noting separately: an amber worth **Rs 0.03** is noise in its own right.
The red path has a Rs 50 floor; the amber path has none. That is a candidate
rule -- an amber below some floor is not worth a patient's attention -- but it
is a NEW rule rather than a fix, and it is not being made tonight.

### A6d confirms D5 holds under attack

A bill stating `SR` where the published rows are plain and dispersible only
did NOT silently borrow the plain row's ceiling. It returned **gray**, because
no row matched the stated modifier. `form_modifier` is product identity and
the matcher refuses rather than approximates -- exactly the Phase 0b rule,
now tested adversarially instead of assumed.

### A6c: no interaction between lines sharing a ceiling row

Two distinct lines resolving to the same reference row were priced
independently and both came back green. Neither poisoned the other, and the
duplicate rules did not fire on different products that happen to share a
ceiling.

---

## Still to probe

A bill in a regional script · handwritten annotations over a printed bill ·
a bill where one line spans two pages · itemised vs summary duplicates of the
same charge.

Every format that gets probed joins the permanent eval set.
