# Decisions — the short list

Every ruling that would otherwise get re-litigated, in one place, with the
evidence behind it.

**The rule for this file: nothing goes in without a measurement, or a reason
that survived contact with a real bill.**

---

## The one that governs everything

**D0 — Never tell a patient a charge is wrong when it is not.**

A false accusation against a hospital or pharmacy that billed correctly ends
this product's credibility permanently. Silence does not. Every rule below is
downstream of that, and every guard errs toward saying less.

Enforced by `eval/run_eval.py` reporting **FALSE REDS: 0**, and by
`eval/adversarial_audit.py`, which actively tries to construct a bill that
produces one. Currently 0 of 10 attacks succeed.

---

## Architecture

**D1 — The model reads; the code decides.** Never the reverse. The readers
return text and numbers. Every comparison, every calculation and every
verdict is plain Python. A language model that does your arithmetic cannot
explain its answer, and this product has to be able to explain itself to a
hospital.

**D2 — Two readers, and the second one exists to DISAGREE.** Not to be more
accurate. Measured on the deployed stack, same bill, one variable changed:
0 of 7 lines high-confidence with two readers, 4 of 7 with one — and the
one-reader run produced a FALSE finding. Textract reported 96–99 confidence
both times. **Confidence is not accuracy, and a single reader cannot doubt
itself.**

**D3 — Gray is a correct answer.** Roughly half of a real bill comes back not
price-controlled or not confidently readable. That is the system working, and
the UI must never present it as an error state.

**D10 — Pair the two readings by CONTENT, not by row position.** Readers
rarely agree on how many rows a bill has, and one stray header row shifts
every index after it. Position pairing silently discarded most of the
cross-check on exactly the bills that needed it most. A wrong pairing cannot
manufacture agreement, because `verify_item()` re-checks everything after.

**D11 — An interpretation we hold evidence AGAINST must not raise a flag.**
Newly-trusted evidence may NARROW a claim immediately; broadening one waits
for its own validation pass. Asymmetric, and deliberate.

---

## Thresholds, and why each number

**GST 12%** — medicines attract 5% or 12% and a bill rarely says which. A
HIGHER assumed GST gives a HIGHER permitted price and therefore FEWER flags:
silence in the ambiguous band. **Known gap:** an inpatient bill may carry no
GST at all, which makes 12% too generous and under-flags by that margin.

**Red needs ≥ 25% excess** — Augmentin 625 Duo, India's best-selling
amoxicillin-clavulanate, lists about 6% above the GST-inclusive cap. A "any
excess is red" rule flags a GSK blockbuster on day one. Inside 25% is far
more likely a stale price, a pack-size ambiguity or a tax-slab difference.

**Red needs ≥ ₹50 affected** — a few rupees on a strip of paracetamol is not
worth a patient raising with a hospital.

**Red needs ≤ 50× ratio** — beyond that, OUR READING is wrong, not the bill.
A real overcharge is a small multiple: a stent at 3.8× the ceiling is real, a
100× is a lost decimal point.

---

## The asymmetry that produced four separate bugs

> **The rule numbers**, in case you have not met them yet: **R1** checks a
> line's arithmetic, **R2** reconciles the bill total, **R3** and **R4** find
> duplicates, **R5** compares against the NPPA ceiling and is the only rule
> that can raise a red, and **R9** explains why a line got no verdict.
> `ARCHITECTURE.md` has the full table.

**R5 refuses to PRICE an unverified line. R1 and R2 went on doing ARITHMETIC
on one.** Four fixes over two days to close it:

- R1 abstains when a single line exceeds the whole bill
- R2 abstains on the whole reconciliation for the same reason
- R2 abstains when ANY line feeding the sum was untrusted
- R1 abstains unless something CONFIRMED the reading — both readers agreed,
  or a lone reader cleared the 95 floor

**If you add a rule that reads a line's numbers, check what it does when
nothing confirmed them.**

Gating on `is_high` is CIRCULAR and does not work: `verify.py` grants HIGH
only when the arithmetic already holds, so a line with an arithmetic error is
never HIGH and the rule becomes dead code. Gate on the reader markers
instead — those are set before arithmetic is considered.

---

## Direction matters, at every scale

**A computed amount ABOVE the printed one means we failed to read a
deduction, not that the bill is wrong.** Applied at three scales:

- bill totals — a printed total *under* the line sum is a discount, not a
  discrepancy (`BELOW_LINE_SUM`)
- section subtotals read as line items
- per-line discount columns

All three were closed by that one question. The original plan was a full
`subtotal → adjustments → grand total` ledger with a structural subtotal
detector; asking about the direction instead turned out to cover every case and
cannot create a false red, because it only ever NARROWS a rule. Measured on all
three scales after the change: no R1 or R2 fires on a bill carrying a discount,
a round-off or a section subtotal.

---

## Data

**Ceiling prices only. Retail prices are NOT a substitute.** Measured: 372
salt sets versus 1,818, with **zero overlap**. They cover different medicines
by design — ceilings are scheduled formulations binding on everyone, retail
prices are per-company approvals for non-scheduled drugs. Swapping them would
delete every finding the system can currently make.

**Retail as a future second tier — context only, never a red.** Blocked on
21% clean salt parsing, a manufacturer field we drop although it is 100%
present in the source, and no way to tell whether a 2013 notification is
still in force.

**The brand dataset's price column is DROPPED and never written.** Those
prices are scraped, undated and stale — that dataset's own Augmentin 625 Duo
price already exceeds the March 2026 NPPA ceiling. A test asserts no field
originating in the brand file can reach a verdict.

**Never invent a price, ceiling, S.O. number or date.** Unparseable rows are
quarantined and logged, never filled in.

---

## Product language

**Never:** illegal · fraud · cheating · overcharged
**Always:** may need clarification · above the listed ceiling · worth asking
about · we could not check this

**State the denominator before the numerator.** A finding count means nothing
without the count of what was actually checked. A report that compared
nothing must say so, not render as a clean bill.

**No sentence in the UI may state a number it did not derive from the
rendered data.** Counts come from the arrays the page renders, never from a
separate summary field — those drifted once and the headline disagreed with
the list directly below it.

---

## Infrastructure

**us-east-1, and the `us.` inference-profile prefix.** `global.` routes to 33
Regions; `us.` routes to exactly three, and the IAM policy pins those three.
**That policy IS the data-residency control** for a document containing
someone's medical bill. The cost is latency for Indian users — say it plainly
rather than glossing it. The argument is about the PREFIX, not the vendor, so
it survives a model change.

**Trust the bytes, not the header.** A client-declared content type is a
claim. The PDF page-count guard hung off that claim until it was tested
against the live API: a PDF sent as `image/jpeg` skipped the check and
reached Textract, which bills per page.

**A green CloudFormation stack does not mean it deployed what you built.**
`sam build` and `sam deploy` can read different directories. The tell is
`File with same data already exists ... skipping upload` appearing after you
edited code. Pass `--build-dir` explicitly, and verify by calling the deployed
API and checking the behaviour you changed, rather than trusting the stack
status. `AWS_STEPS.md` section 10.4 has the exact calls.
