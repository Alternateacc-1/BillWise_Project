# BillSahi — architecture

Living document. Phase 0 sections are final; later sections fill in as the
phases land.

---

## The shape

```
frontend (React + Vite)  ->  API (FastAPI)  ->  pipeline
                                                ├── Reader     (fixture | Textract | Bedrock vision)
                                                ├── Verifier   (pure Python)
                                                ├── Normalizer (dataset lookup + optional Bedrock)
                                                ├── Matcher    (rapidfuzz, pure Python)
                                                ├── Auditor    (pure Python, always local)
                                                └── Explainer  (templates | Bedrock)
                                              store (SQLite | DynamoDB)
                                              blobs (local dir | S3)
```

One env var, `PROVIDER=local|aws`, switches every adapter. `local` runs with
no network at all. Verifier, Matcher and Auditor have no AWS variant — they
are pure functions and stay that way, because they are the parts that decide
what a patient is told.

**Region:** everything in `ap-south-1`, with Claude reached through a global
cross-region inference profile. If that proves impossible the whole stack
moves to `us-east-1` — we never split regions. See OPEN_QUESTIONS.md Q1.

---

## The one rule that shapes everything else

**The LLM never does arithmetic and never decides a verdict.** Code decides;
the model explains in prose and normalises names. A language model that is
90% reliable at multiplication is 100% unacceptable at telling someone their
hospital overcharged them.

Corollary: **gray is always an acceptable answer.** We would rather report
three findings and stay silent on twenty than guess at twenty-three.

---

## Phase 0 — the reference data

### Sources

| Source | Rows | Role |
|---|---|---|
| `All_Drugs_Ceiling_Prices.csv` | 915 | DPCO scheduled formulations. **The only source allowed to produce a red flag.** |
| `Special_Feature_..._Companies.pdf` | 22 | Higher ceilings for special-feature packs. Additional to the above, never replacements. |
| `Retail_Price_Information.csv` | 3,881 | Non-scheduled new drugs. Per-company approved prices. **Amber/context only, never red.** |

All three collapse into one schema in `data/reference/reference_prices.csv`.
Nothing downstream reads `data/raw/` directly.

### Two hard rules

1. **Zero dropped from the ceiling file.** All 915 rows parse or the build
   fails. If a row does not parse, the regex is wrong — not the data.
2. **Nothing is ever invented.** No price, unit, SO number or date is filled
   in. Unparseable rows are quarantined with a reason code.

### usable/quarantined vs price_checkable

Two different ideas that would be a bug to conflate:

- **`status`** — is the row's DATA sound? `quarantined` means no price, a
  withdrawn price, or an unreadable unit. Reason codes: `price_withdrawn`,
  `price_unparseable`, `unit_missing`, `unit_unmappable`.
- **`price_checkable`** — does the unit basis support a per-unit comparison?
  A `pack` row with an unknown count is perfectly good data that still cannot
  be divided into a per-unit price.

A `price_checkable=false` row is still shown as evidence and still counts for
R9 messaging. It just never produces a price verdict.

Current state: 4,582 usable of 4,818. All 4 ceiling quarantines are unit
strings that genuinely do not state what one unit is (`1 gm or 1 ml`,
`Per mg of Phospholipids in the pack`, and two rows with two conflicting
bases in one cell). Those four are pinned by a test so a parser regression
cannot quietly add a fifth.

### Ceiling selection

`select_highest_applicable_ceiling()` requires an **exact** match on all of:
salt set, dosage form, strength, unit basis, **and pack size**. Only then does
it take the highest per-base-unit price among survivors, so a legitimate
special-feature pack is never measured against the ordinary ceiling.

Two findings from the real data drove this, both now regression tests:

- **Pack size is product identity.** NPPA prices Ringer Lactate in four
  volumes and the small packs are dearer per ml — 30.62/100 ml is 0.3062/ml,
  66.52/500 ml is 0.1330/ml. Without matching pack size, a 500 ml bag selects
  the 100 ml row as "highest" and a price 2.3x the real cap passes as
  compliant. (`test_ringer_lactate_does_not_match_another_pack_size`)
- **The Meropenem inversion.** In the special-feature file the 500 mg vial
  (1121.96) costs more than the 1000 mg vial (851.43). Any fuzzy strength
  match hands a 1000 mg item the 500 mg ceiling. Strength matching is exact,
  and the inversion is asserted so nobody "corrects" the source data.
  (`test_meropenem_strength_inversion`)

A third finding shaped the retail parser: **a drug strength is not a
container size.** Reading a pack size out of the retail file's free-text
composition column priced RETL-0434 per "1.4 gm" — which was the amount of
gemcitabine in the vial, not the vial's size. Pack-size recovery now runs only
against the ceiling file's terse, structured strength column.

---

## Phase 1 — the audit thresholds

Four numbers, all in `backend/app/config.py`, all erring toward silence. They
are the entire defence against false red flags, which is the project's one
hard correctness requirement.

| Setting | Value | Why |
|---|---|---|
| `GST_PERCENT` | 12 | Medicines are 5% or 12% and a bill rarely says which. The ceiling is ex-tax, so a **higher** assumed GST permits a **higher** price and yields **fewer** reds. Assume the taxpayer-favourable slab. |
| `RED_EXCESS_FRACTION` | 0.25 | Below 25% over the cap, a stale price or pack-size ambiguity is a likelier explanation than an overcharge. |
| `RED_MIN_AMOUNT_AFFECTED` | ₹50 | A few rupees on a strip is not worth a patient's letter. |
| `RED_MAX_RATIO` | 50x | Above this, assume **our** reading is wrong, not the bill. Real overcharges are small multiples. |

### Why 25% specifically

Measured, not chosen. Augmentin 625 Duo — the most widely sold
amoxicillin-clavulanate brand in India — lists at ₹223.42 for a strip of 10,
i.e. ₹22.34/tablet, against a ceiling of ₹18.74. At 12% GST the cap is
₹20.99, so a GSK blockbuster sits ~6% above it. A rule of "any excess is red"
accuses Glaxo SmithKline on its first run. The margin between a legitimate
market price and a naive red line is that thin.

Meanwhile a genuine finding is a *multiple*: a stent billed at ₹1,50,000
against a ₹39,186 ceiling is 3.8x. A 25% floor costs us nothing real.

### What the user sees

Every price flag shows the **excess percentage and the full arithmetic** —
ceiling, GST multiplier, threshold, billed per-unit price, and the difference
— so the verdict can be checked by hand. The 0–25% band is reported as its
own amber category, and `eval/run_eval.py` reports its count separately from
reds so we can watch the band's size as the rules change.

Language rules: never "illegal", "fraud", "cheating" or "overcharged". Always
"above the listed ceiling price", "may need clarification", "amount affected".
Every verdict carries "prices as per NPPA data retrieved 18 Sept 2026".

---

## Phases 2–5

Filled in as they land.
