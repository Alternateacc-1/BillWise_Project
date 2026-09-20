# What BillWise cannot do

Written deliberately, and kept where anyone can find it. A tool that tells
people their hospital may have charged them too much has to be clear about
where its authority stops.

Two of these are engineering problems we have solved by refusing to guess.
The rest are not engineering problems at all. Limit 9 is a capability gap in
the reader, and the only one on this list with a clear route out.

> **A limit means "we cannot know", never "we did not look."**
>
> Probing a real pharmacy bill on 2026-09-18 contradicted limits **2** and
> **4** for that bill: it prints a `PACK` column, and it prints its GST slab
> per line. Both limits remain true in general — and both had quietly been
> covering for a column we simply were not reading.
>
> That is a failure mode worth naming, because it is comfortable. A limit
> documented honestly and then left to absorb cases it does not apply to
> stops being honesty and becomes an excuse. Each entry below now says what
> would lift it, and where a bill supplies the missing fact, the rule is
> **read the bill and fall back to the limit only when it stays silent.**

---

## 1. We check what is printed. We cannot see what never happened.

**This is the biggest limitation, and it is total.**

BillWise reads a bill and checks the arithmetic and the prices *of the lines
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

> **A real bill contradicted this, and the contradiction is instructive**
> (2026-09-18). A retail pharmacy sale bill we probed prints a full **`PACK`**
> column — 15, 10, 10, 10, 20, 1 — right next to the quantity. For that bill
> the pack size is not irreducible at all. It is printed. We simply were not
> reading the column.
>
> The limit above stays true **in general**: most hospital bills print no such
> column, and when none is printed the information genuinely is not in the
> document. But "we cannot know" and "we did not look" are different
> statements, and only the first is a limit.
>
> **The fix is to read the column when a bill provides it and fall back to
> this limit when it does not** — `pack_count_source="bill_text"`, which is
> CERTAIN, versus the upper-bound gate, which is the honest answer when
> nothing is stated. Tracked as Class C in `FORMAT_FINDINGS.md`.

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

> **The same real bill contradicted this one too** (2026-09-18). It prints
> **`CGST 2.5%`** and **`SGST 2.5%`** per line — a stated 5% slab, on the
> bill, in the row. For that bill we do not need to assume anything, and
> assuming 12% instead means choosing a guess over printed evidence. Worse,
> it is the *wrong direction*: a genuine 5% item assumed at 12% gets a higher
> cap and is under-flagged, which is the arithmetic above running against a
> bill that told us the answer.
>
> As with limit 2, the limit holds **in general** — most bills state a single
> bill-level tax, or none at all — but the fix is the same shape: **use the
> printed rate when the bill states one, record in the evidence that it came
> from the bill rather than from config, and fall back to the 12% assumption
> only when nothing is stated.** Tracked as Class D in `FORMAT_FINDINGS.md`.
>
> A related and more dangerous question is not "which slab" but "is GST in
> this number at all" — see Class G. That one can under-flag silently.

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

## 9. Textract cannot read Indian scripts at all.

The primary reader is Amazon Textract. Its documented language support is:

> "Amazon Textract supports English, French, German, Italian, Portuguese, and
> Spanish text detection."

Latin script only. **A bill printed in Devanagari, Tamil, Bengali, Telugu or
any other Indian script is unreadable to it by design** — not badly read,
unreadable. The supported character list is a-z, A-Z, 0-9 and accented Latin.
(The rupee sign is supported, which is a small mercy.)

This is a real limit for a tool aimed at Indian patients, and it is the
strongest single answer to "why not just use Textract?". A vision model can
read Devanagari; Textract cannot.

**We have not solved it, and the vision reader alone does not solve it
either.** Claude would return a drug name in Devanagari, and the matcher
normalises to uppercase Latin and compares against NPPA data written in
English. The name would resolve to nothing. A working multilingual path needs
transliteration between reading and matching, which is not built.

**What would it take:** transliteration or translation of the item name
between the reader and the matcher, and a test set of real bills in at least
one Indic script. Neither exists.

**Related, and the other half of the same argument:** on an English bill
Textract read the `PARTICULARS` column HEADER as line item 1, shifting every
drug name onto the next row's numbers — seven rows returned, not one
correctly attributed. A single reader cannot doubt itself. That is why there
are two, and why disagreement is treated as a reason to stay silent.

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

---

## The currency is assumed to be rupees, and nothing checks that

Found 2026-09-20, on a real **Singapore** tax invoice uploaded through the
deployed stack: amounts in **S$** were rendered as **₹**, line for line.

Nothing in the pipeline reads a currency. `format_inr()` is applied to every
figure because every bill this was designed for is Indian, and that assumption
is nowhere stated and nowhere checked.

**The deeper issue is not the symbol.** NPPA ceilings are Indian law. On a
Singapore bill there is nothing to compare against at all, so every line is
correctly unpriceable — but for a reason the report does not give. It says
"No published ceiling" as though it had searched and found none, when the
truth is the whole reference set is the wrong jurisdiction.

What the report got RIGHT on that bill, and it is worth recording:
  - all 7 lines read correctly, names and amounts matching the paper
  - R2 abstained. Textract took a SUBTOTAL as the printed total, the line sum
    came out above it, and the directional rule correctly said nothing rather
    than querying a discount. Class B working on a real foreign bill.

What it got WRONG:
  - S$ shown as ₹
  - no statement that the bill is outside the reference data's jurisdiction

**Fix, when there is time:** read the currency (Textract AnalyzeExpense
returns it), carry it as an explicit field, and ABSTAIN from the whole price
comparison with a plain message when it is not INR -- the same shape as every
other abstention here. Do not merely swap the symbol: that would make a
jurisdiction error look like a formatting one.

### The two readers' confidence numbers are NOT the same kind of number

Recorded 2026-09-20, when the second reader moved from an Anthropic model to
Amazon Nova. The swap is a parameter, not a code change -- the reader uses the
Converse API, which is model-agnostic -- but it makes an existing asymmetry
worth stating plainly.

**Textract's confidence is a calibrated extraction score per field.** The
model's confidence is SELF-REPORTED: the prompt asks it for "your own
confidence in that line", and it answers. One is a measurement, the other is
an opinion, and `verify.py` applies the same >= 95 floor to both.

That is tolerable while Textract is the primary reader and the model is a
cross-check, because agreement between two independent readings is what the
verdict actually rests on -- not either score.

**It stops being tolerable on a bill Textract cannot read.** `verify_item()`
takes `primary = a or b`, so when Textract returns nothing the vision model
becomes the sole reader, and a line can reach HIGH on nothing but the model's
own say-so. Today that path is unreachable for Indic scripts, because the
matcher would fail anyway. **It becomes reachable the moment transliteration
is built, and the floor must be reconsidered in the same change** -- not
afterwards.

**Multilingual is FUTURE SCOPE and is not claimed.** Say so plainly rather
than implying a vision model makes it work; it does not, for the matching
reason above.

### Why Nova rather than another Claude

Not preference -- availability. The Claude Sonnet 4.6 AWS Marketplace offer
EXPIRED on 2026-09-19, which surfaced as an acceptance email followed a minute
later by an expiry notice, the model vanishing from Model access, and a
misleading `AccessDeniedException` about `aws-marketplace:Subscribe` on the
Lambda role. That last one looks like an IAM bug and is not: the function was
trying to auto-subscribe to an offer that no longer exists. **No IAM change
would have fixed it.**

Nova is a first-party AWS model, so it carries no Marketplace subscription and
no offer to expire. A different model family is also arguably a BETTER
cross-check than a second Anthropic model: the second reader exists to
DISAGREE, and two similar models make correlated mistakes.

### The upload ceiling is 4 MB, and it is not our choice

Measured against the deployed stack on 2026-09-20, after a user hit a bare
"Network error" uploading a phone photo:

      3 MB  reached our code
      4 MB  reached our code
      5 MB  HTTP 413 from the gateway
      8 MB  HTTP 413 from the gateway

API Gateway base64-encodes a binary body into the Lambda invocation event,
inflating it by about a third, and Lambda caps a synchronous event at 6 MB.
So ~4.5 MB of file is the hard ceiling no matter what the UI claims. We had
been advertising 10 MB in three places.

**The failure mode is worse than the limit.** The gateway's 413 is generated
BEFORE our code runs, so it carries no CORS headers, so the browser cannot
read the response and reports a bare "Network error" instead. The user is told
a file is within the limit, uploads it, and gets a network failure with no
reason given.

**A phone photo of a bill is routinely 3-8 MB, so this is the common case,
not an edge case.** 4 MB will still reject plenty of them.

**The real fix is not a smaller number.** Either downscale in the browser
before upload -- a bill needs legibility, not 12 megapixels, and Textract does
not benefit from the extra -- or upload straight to S3 with a presigned URL and
have Lambda read it from there, which removes the 6 MB event limit entirely.
The presigned route is the right one and is not built.

Until then the honest thing is to state 4 MB and mean it.

### The two readings are paired by ROW INDEX, and that is fragile

Measured 2026-09-20 on a photographed bill. `verify_bill()` does:

    verify_item(a_items.get(index), b_items.get(index))
    for index in sorted(set(a_items) | set(b_items))

So line 3 of Textract is compared with line 3 of the vision model, and nothing
checks that those are the same ROW OF THE BILL. One extra or missing row near
the top -- a column header read as an item, a wrapped description counted
twice -- shifts every index after it and destroys agreement for the rest of
the bill. Unmatched indices report `only_one_reader_ran` even though the
second reader ran normally on every other line.

On one real bill this produced all three outcomes at once: line 1 agreed at
100 similarity, line 2 disagreed at 34, line 3 had no partner at all.

**The failure is SAFE but LOSSY.** A shifted pairing produces disagreement,
and disagreement produces gray -- never a false red. The cost is silence on
lines both readers actually read correctly.

**The fix is to pair on CONTENT rather than position** -- match each reading's
rows to the other's by name similarity and amount, the way a person would,
and treat leftovers as single-reader. Not built. Until it is, a single stray
row at the top of a bill costs most of the cross-check.

**A reporting bug rode on this and is fixed.** The summary said "Only one
reader ran on this bill" whenever ANY line was unpaired, which claimed the
second reader had not run at all. It now states how many lines of how many.
