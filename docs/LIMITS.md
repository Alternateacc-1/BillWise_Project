# What BillSahi cannot do

Written deliberately, and kept where anyone can find it. A tool that tells
people their hospital may have charged them too much has to be clear about
where its authority stops.

Two of these are engineering problems we have solved by refusing to guess.
The rest are not engineering problems at all.

---

## 1. We check what is printed. We cannot see what never happened.

**This is the biggest limitation, and it is total.**

BillSahi reads a bill and checks the arithmetic and the prices *of the lines
on it*. A charge for a syringe that was never used, a doctor's visit that
never took place, a test that was billed but not run — all of it is invisible
to us. The line looks perfect. The arithmetic holds. The price is under the
ceiling.

Phantom billing is plausibly the most common real-world overcharge in Indian
healthcare, and we cannot detect a single instance of it. Nothing in the
architecture could. Detecting it needs the medical record, not the bill.

**What would it take:** a second source — discharge summary, prescription,
nursing chart — and permission to cross-reference them. That is a different
and much larger product, with much heavier privacy obligations.

---

## 2. Pack size is irreducible when the bill does not state it.

A line reads `Paracetamol 500 mg Tablet | Qty 10 | ₹360.00`. Ten tablets, or
ten strips? **The bill does not say, and no amount of processing recovers it.**
The information is not in the document — this is not an OCR limitation.

We have not solved this. We have made it **safe**: `line_total ÷ qty` is an
upper bound on the per-unit price, so under the allowance we can say green for
every possible pack size, and over it we say nothing at all. The full argument
is in `ARCHITECTURE.md`.

This cost us real coverage. It was worth it: the alternative was a false red
on an ordinary wholesale invoice.

**What would it take:** the bill states the pack, or the brand is one of the
249,148 we have indexed, or the user tells us. All three are external to the
bill line itself.

---

## 3. Coverage is capped at 915 formulations, permanently.

India price-controls scheduled formulations. It does **not** control room
rent, nursing charges, consultation fees, OT charges, consumables, or
diagnostic tests. On a real hospital bill that is most of the money.

Our demo bills come out roughly two-thirds gray, and that ratio is honest
rather than a limitation of our matching. **No amount of engineering changes
it, because the ceilings do not exist.** When we say "no published ceiling
exists for this item", we are describing Indian pharmaceutical regulation, not
apologising for our software.

---

## 4. We do not know which GST slab applies, so we assume the one that
##    flags least.

Indian medicines attract **either 5% or 12%** GST depending on the
formulation, and a bill line rarely says which. The NPPA ceiling is quoted
**exclusive of tax**, so the maximum legitimate price is `ceiling × (1 + GST)`.

Worked, on paracetamol 500 mg (ceiling ₹0.93) and amoxicillin+clavulanate
625 mg (ceiling ₹18.74):

| Assumed GST | Allowance = ceiling × (1+GST) | Effect |
|---|---|---|
| 5% | ₹18.74 × 1.05 = **₹19.68** | lower cap → **more** items exceed it → more flags |
| **12% (what we use)** | ₹18.74 × 1.12 = **₹20.99** | higher cap → **fewer** items exceed it → fewer flags |

So **assuming the higher slab makes us flag less, not more.** A price of
₹20.50 per tablet is above the 5% cap and below the 12% cap; we call it fine.
If that drug is genuinely a 5% item, we have **under-flagged** — we stayed
silent about something that was over its real limit.

That is the direction we want the error to run. An unflagged overcharge is a
missed finding; a flagged compliant price is an accusation. We choose to miss.

**What would it take:** the per-formulation GST slab, which is not in any file
we hold and is not published in a form we could join against the ceiling list.

---

## 5. OCR is a hard floor.

The crop-and-re-read pass recovers lines that were marginal. It cannot create
information that is not in the pixels. A scan bad enough to be unreadable
stays unreadable, and the honest output is that we could not read it.

---

## 6. Brand resolution has a long tail.

249,148 brand names are indexed. India has more, plus hospital-formulary
items, compounded preparations, and imports. 226 indexed names map to more
than one salt set — those are flagged ambiguous and can never produce a red
flag rather than having one arbitrarily picked.

---

## 7. The reference data goes stale.

Our lists were retrieved on a stated date and every verdict displays it. NPPA
revises ceilings through the year by individual S.O. and applies an annual WPI
revision. We stamp the date and provide a diff mode so a new release can be
compared against the old one — but we cannot make the data current, and a
verdict is only as good as the day it was computed.

---

## 8. We never prove a price is wrong — only that it is above a published
##    ceiling, as we understood the line.

There are legitimate reasons a price exceeds a naive comparison: a
special-feature pack with its own higher ceiling, an unusual strength, a
hospital pack, or our own misidentification of the item.

This is exactly why nothing in the interface says *illegal*, *fraud*,
*cheating* or *overcharged*, and why the output is a question a patient can
ask rather than a finding they can assert. **We are not an authority and the
product never pretends to be one.**

---

## The point

These limits are not a weakness of the design. **Handling them honestly is the
product.**

Anyone can build something that reads a bill and shows sixteen confident
verdicts. The hard part is knowing which six you are entitled to, and saying
so about the other ten.

The clearest example is in the git history. An item that showed **amber**
yesterday shows **gray** today, because we proved we could not actually tell
what its per-unit price was. The system got quieter and more correct in the
same commit. That trade — made deliberately, with an argument behind it — is
the thing worth demonstrating.
