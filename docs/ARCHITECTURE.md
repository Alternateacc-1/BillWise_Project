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

## Phase 0b — brand-to-salt resolution

Bills say "Augmentin 625". The price lists say "AMOXICILLIN (A) + CLAVULANIC
ACID (B)". This is the most error-prone step in the project, so it is
data-driven first and AI second.

### Synonyms are load-bearing, not polish

The ceiling file itself contains **both** `AMOXICILLIN` and `AMOXYCILLIN` as
separate rows, and the brand dataset spells it `Amoxycillin`. Without the
synonym table those never meet and the single most common antibiotic in India
goes gray.

Two kinds of transformation, and the distinction is the whole safety argument:

- **Orthographic rules** are spelling conventions applied to **both** sides of
  a comparison — `sulph` → `sulf`, word-initial `oe` → `e`. Safe because they
  are canonicalisation, not a claim that two drugs are the same. Deliberately
  narrow: a blanket `ph` → `f` would wreck phenytoin and morphine, and a
  blanket `oe` → `e` turns Coenzyme Q10 into "cenzyme q10".
- **Synonyms** are genuine identity claims — aspirin **is** acetylsalicylic
  acid. Hand-curated in `salt_synonyms.json`, every pair unit-tested.

Admission rule for the table: the two names must denote the same active
moiety at the same strength basis. Sodium valproate 200 mg is **not** valproic
acid 200 mg, so that pair is excluded and the exclusions are documented in the
file. A missing synonym costs coverage; a wrong one costs correctness.

### Two-tier matching, gated on the whole product

Tier 1 matches exact spelling. Tier 2 — synonym-expanded — runs **only** if
tier 1 found nothing. "Highest applicable ceiling" is resolved strictly within
the winning tier, so a synonym can never outrank an exact match.

**The gate is applied to the full product match, not to the salt set alone**,
and getting this wrong silently loses real matches. Augmentin's composition
reads AMOXYCILLIN + CLAVULANIC ACID. Gating on salts alone, tier 1 "succeeds"
with four AMOXYCILLIN rows — a dry syrup, an oral suspension and two
injections. None is a tablet. Tier 2 never runs and the tablet ceiling
(CEIL-0189, spelled AMOXICILLIN, ₹18.74) is never found. Gating on the full
match — salts **and** form **and** strength **and** unit — tier 1 correctly
finds nothing, tier 2 runs, and the bridge completes.

Reference rows always keep their original NPPA spelling. Synonyms expand the
query only; nothing is ever merged or rewritten.

### The synonym conflict guard

Synonym expansion is only safe while no two rows that canonicalise to the same
product carry different prices. `prepare_reference.py` checks this on every
build and **currently reports zero conflicts** across all 915 ceiling rows. If
NPPA ever publishes a paracetamol ceiling and a differing acetaminophen
ceiling, the build says so loudly rather than letting the matcher pick one.

Building that check found a real parser bug: ASPIRIN `TABLET DT 75 MG` (₹0.36,
S.O. 1575(E)) and Acetylsalicylic acid `Tablet 75 mg` (₹0.39, S.O. 1581(E))
were collapsing into one group. They are genuinely different products — DT is
a **dispersible** tablet, and NPPA prices release variants separately (plain
Tablet 100 mg is ₹0.21; the Effervescent/Dispersible/Enteric coated Tablet
100 mg is ₹0.22). The fix was to treat the release modifier as part of product
identity, not to weaken the synonym table. `form_modifier` is now a match
criterion, so a plain tablet can never be measured against a modified-release
ceiling.

### The index

`brand_index.csv`: 249,148 names reduced from 253,973 source rows, carrying
only what the bridge needs — normalised name, salts, strength, form, pack
size, manufacturer, and three flags.

- **The price column is dropped and never written.** Those prices are scraped,
  undated and stale — Augmentin's listed price already exceeds the March 2026
  ceiling. A test asserts no brand-file field can reach a verdict.
- **Discontinued brands are kept, flagged** (7,376). An old bill can
  legitimately list a withdrawn product.
- **Unparseable pack labels leave `pack_count` NULL** (61 of 254k), which
  forces gray rather than a per-unit price built on an invented quantity.
- **226 names map to more than one salt set** and are flagged `ambiguous`
  rather than arbitrarily resolved. An ambiguous name must never produce red.

### Deployment: DynamoDB, not the bundle

The reduced index is **36 MB** — too large to sit comfortably in a Lambda
package, and slow to parse on a cold start. Phase 4 loads it into DynamoDB at
deploy time and looks names up by key; `seed_dynamodb.py` does the load. At
on-demand write pricing that is a **one-time ~$0.31** for ~249k items, with
negligible storage after. It is gitignored and regenerable with two commands,
so the repo stays lean; the small build report is committed so the numbers are
reviewable without it.

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

## Cost controls

The project runs on $100 of credits and a cost mistake ends it. Expected
total spend is **$8–13**; the design keeps it there deliberately rather than
by luck. Four of these are structural — they cost nothing to add and cannot
be forgotten under deadline.

### Offline by default

`PROVIDER=local` is the default in `.env.example` **and** hard-defaulted in
`config.py`, so an unset environment variable can never silently select the
paid path. `eval/run_eval.py` pins `PROVIDER=local` explicitly and refuses to
run otherwise: the eval suite is the thing most likely to be run in a loop,
and it must never be able to spend money.

This matters more than any other control, because **Textract is ~70–80% of
the projected bill**. Building the engine, the rules and the eval entirely
offline is what turns $8 into $1.50.

### Reserved concurrency of 5

Every Lambda that calls Textract or Bedrock carries
`ReservedConcurrentExecutions: 5` in `infra/template.yaml`. A retry storm or a
runaway client then costs five concurrent invocations' worth of API calls, not
a thousand. It is a hard ceiling enforced by the platform rather than by our
own retry logic being correct.

Retry logic is capped at one attempt as well — but that is a code fix for a
code risk. The concurrency limit is what holds when the code is wrong.

### Reject before you pay

Page count and upload size are checked **before any billable call is made**:
bills over 10 pages and oversized uploads are rejected at the API boundary.
Textract is priced per page, so a 400-page PDF is a $4 mistake from a single
careless upload. The check is cheap, the failure mode is not.

### No always-on resources

The SAM template has **no VPC**, therefore no NAT Gateway (~$32–45/month, the
classic hackathon killer). DynamoDB is on-demand, never provisioned. S3
carries a 1-day lifecycle delete and CloudWatch a 7-day log retention. There
is no OpenSearch, no vector store, no EC2, no Fargate. **Idle cost is
effectively zero** — the stack can sit untouched between the demo and judging
without accruing anything.

### Guardrails outside the code

`docs/AWS_STEPS.md` Section 0 sets up a $10 budget alerting at 50% and 100%,
a $25 tripwire, and account-level billing alerts — **before any resource is
created**. Free, and it means a runaway loop pages us at $5 rather than
surfacing at $80.

### What stays despite the cost

**Both readers.** Running Textract and a Bedrock vision model over the same
file and requiring them to agree is the most interesting thing this project
does, and it is not where the money goes — the second reader is cents. Cost
control never came at the expense of the verification design.

---

## Phases 2–5

Filled in as they land.
