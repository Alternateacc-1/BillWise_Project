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

## Still to probe

A bill in a regional script · handwritten annotations over a printed bill ·
a bill where one line spans two pages · itemised vs summary duplicates of the
same charge.

Every format that gets probed joins the permanent eval set.
