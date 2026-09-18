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

## Still to probe (Saturday)

Hospital inpatient · wholesale B2B invoice · diagnostic lab bill ·
thermal-printer receipt · multi-page with per-section subtotals ·
GST-inclusive line pricing · discount and round-off rows.

Every format that gets probed joins the permanent eval set.
