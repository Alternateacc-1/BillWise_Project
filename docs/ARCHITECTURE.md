# BillWise — architecture

How a photographed bill becomes a report: what reads it, what checks the
reading, what compares each line against a government price, and what each
component is forbidden from doing.

The sections follow the order the work was built in, which is also roughly the
order data flows: the reference prices first, then brand matching, then the
rules, then cost and deployment. Read [`DECISIONS.md`](DECISIONS.md) first if
you only want to know why the engine behaves the way it does.

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

**Region:** everything in `us-east-1` (N. Virginia), with the second reader
reached through a **US geo** cross-region inference profile
(`us.amazon.nova-2-lite-v1:0`). Textract, including AnalyzeExpense, runs
there at 5 TPS. The whole stack sits in one Region. **We never split Regions:**
a split stack means cross-region transfer charges, two sets of logs, two
places for an IAM policy to be wrong, and a latency path nobody will debug at
2am.

**This was originally specified as `ap-south-1` (Mumbai)**, to sit near the
Indian users the tool is for, and the reversal is worth explaining because the
intuitive answer is wrong.

The vision models evaluated for the reader support **no geo inference profile
from `ap-south-1`** — only the global profile, which routes to 33 Regions
across three continents. From `us-east-1` a US geo profile is available, and it
routes to exactly three: `us-east-1`, `us-east-2`, `us-west-2`. AWS guarantees
a geo-tied profile's destination list never changes.

**The argument is about the PREFIX, not the vendor**, so it survives changing
the model — which this project has done once already.

So **the Region that keeps a patient's bill in the smallest, most predictable
set of places is N. Virginia, not Mumbai.** Choosing India would have meant
choosing worldwide routing.

**Data residency is a design requirement here, not a compliance checkbox.**
What we send Bedrock is a photograph of a real medical bill: a patient's name,
registration number, address, doctor, and a drug list that implies a
diagnosis. `infra/template.yaml` pins the profile ARN and the three
Region-scoped foundation-model ARNs; no statement permits invoking the model
anywhere else. Nothing else in the system would stop a bill leaving, so that
policy is load-bearing rather than decorative.

**The cost, stated plainly rather than quietly:** the deployed demo is further
from its intended users than the design wants, and latency is worse for an
Indian patient than an Indian Region would give. That is a consequence of
model availability, not an architectural preference.

---

## Two guarantees, and we only harden one

These are constantly conflated, including by us. They are not the same claim
and they do not have the same achievability.

### 1. "Never a false accusation" — achievable, and what we work on

We will not tell someone their hospital charged above a published ceiling
when it did not. This is a **soundness** property: everything we *do* assert
is defensible.

It is achievable because we are allowed to decline. Every hard case can be
answered with gray. The upper-bound gate largely closed the biggest hole in
it; the eval's zero-false-reds gate is how we keep it closed. **All hardening
work targets this guarantee.**

### 2. "A correct verdict on every line" — impossible, and not our goal

This is a **completeness** property, and it is out of reach for reasons that
are not engineering problems. Phantom billing is invisible to a bill. Pack
size is often absent from the document. Most hospital charges have no
published ceiling in the first place. See `LIMITS.md`.

**We do not pursue it, and no claim we make should imply we have it.**

### Why the distinction has to stay explicit

The two trade against each other. Every guard that protects guarantee 1 costs
coverage against guarantee 2 — the upper-bound gate turned a real finding
amber-to-gray, deliberately. If the difference blurs under deadline, someone
reasonably asks "why is so much gray?" and the tempting answer is to loosen a
guard. That would trade the guarantee we can actually keep for one we can
never have.

**Gray is not a failure to reach guarantee 2. It is guarantee 1 working.**

---

## The one rule that shapes everything else

**The LLM never does arithmetic and never decides a verdict.** Code decides;
the model explains in prose and normalises names. A language model that is
90% reliable at multiplication is 100% unacceptable at telling someone their
hospital overcharged them.

Corollary: **gray is always an acceptable answer.** We would rather report
three findings and stay silent on twenty than guess at twenty-three.

---

## The reference data

### Sources

| Source | Rows | Role |
|---|---|---|
| `All_Drugs_Ceiling_Prices.csv` | 915 | DPCO scheduled formulations. **The only source allowed to produce a red flag.** |
| `Special_Feature_..._Companies.pdf` | 22 | Higher ceilings for special-feature packs. Additional to the above, never replacements. |
| `Retail_Price_Information.csv` | 3,881 | Non-scheduled new drugs. Per-company approved prices. **Amber/context only, never red.** |

All three are parsed into one schema by `scripts/prepare_reference.py`.

Only the first two are WRITTEN to `data/reference/reference_prices.csv`: that
file is the engine's reference, and the matcher accepts `ceiling` and
`special_feature` only, so the retail rows would be 3,881 rows nothing reads.
`prepare_reference.build()` still returns all three in memory, which is what
the reference-data tests parse. Nothing in the running app reads `data/raw/`
directly.

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

Current state, across everything the parser reads: 4,582 usable of 4,818.
(The file it writes carries the 937 ceiling and special-feature rows only --
see above.)

All 4 ceiling quarantines are unit strings that genuinely do not state what one
unit is. Two read `1 gm or 1 ml` and `Per mg of Phospholipids in the pack`; the
other two put two conflicting bases in a single cell. Those four are pinned by
a test, so a parser regression cannot quietly add a fifth.

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

## Brand-to-salt resolution

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

### Shipping it: a reduced index in the bundle

The full index is **36 MB** -- too large for a Lambda package and slow to parse
on a cold start. So only part of it ships: the brands whose salts appear
somewhere in the 915 ceiling rows, which is **13.5 MB and 96,489 of 249,148
names**, committed at `backend/reference_data/`.

Local runs read that same file, so what the tests exercise is what runs.

**The filter keeps a brand if ANY of its salts is in the ceiling list, not only
if the whole combination is.** That matters because the engine has three
answers, not two:

    priced   /   no_public_ceiling   /   could_not_identify

Saying "no public ceiling" needs the brand too. A stricter filter would keep
only brands we can price, and turn "we identified this, and India does not
price-control it" back into "we could not identify it" -- a worse answer, on a
real medicine from a real bill.

Brands whose salts appear nowhere in the 915 are dropped: they can produce
neither answer, so carrying them costs cold-start time for nothing. They report
`could_not_identify`, which is honest -- with the shipped data we know nothing
about those molecules.

`scripts/measure_reduced_index.py` re-measures this if the reference data
changes.

---

## The rules

The engine's rules are numbered, and those numbers are used throughout this
repo's documentation and code comments. All of them live in
`backend/app/pipeline/audit.py`.

| Rule | What it checks | Strongest verdict it can give |
|---|---|---|
| **R1** | Line arithmetic: does `quantity × rate` equal the printed line total? Only runs on a line we trust. | amber |
| **R2** | Bill reconciliation: does the sum of the lines equal the printed grand total? Only runs when both are trusted. | amber |
| **R3** | Exact duplicates: the same item name and quantity billed twice. | amber |
| **R4** | Near duplicates: two lines at the same unit price with near-identical names. | amber |
| **R5** | Above ceiling: the billed per-unit price against the NPPA ceiling plus GST. | **red** |
| **R9** | Why a line got no price verdict at all. It explains a grey, it never raises a finding. | grey |

**Only R5 can produce a red.** Everything else tops out at amber — a question,
not a claim. So every red in the product traces to one comparison against one
published government ceiling, which is what makes a red explainable to the
hospital that issued the bill.

**R6, R7 and R8 do not exist.** The numbering has gaps because those rules were
designed and not built. R6 in particular — checking a billed rate against an
MRP printed on the bill — is the most valuable unbuilt one, because it needs no
identification of the medicine at all.

**R1 and R2 only ever ask a question about arithmetic. R5 is the only rule
that compares against a government price**, and therefore the only one that can
say a charge looks too high.

---

## The audit thresholds

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

## The upper-bound gate — a correctness argument

This is the strongest claim the system makes, and it is a proof rather than a
heuristic, so it is written out here in full.

### The problem

A bill line reads `Paracetamol 500 mg Tablet | Qty 10 | ₹360.00`. The ceiling
is ₹0.93 per **tablet**. Is ₹360 for ten tablets, or ten strips?

**The bill does not say, and no amount of processing recovers it.** The
information is not in the document. This is not an OCR limitation or a parsing
gap — it is absent at the source.

### The argument

Let one billed unit contain `N` base units, where `N ≥ 1` and `N` is unknown.
Then the real price per base unit is

```
    price_per_base_unit  =  line_total / (qty × N)
                         ≤  line_total / qty          because N ≥ 1
```

So `line_total / qty` is an **upper bound** on the per-unit price — never the
price itself. The two cases are **not symmetric**:

| Case | What follows |
|---|---|
| bound **≤** allowance | The item is within the ceiling **for every possible N**. Green, and no later discovery of the pack size can overturn it. |
| bound **>** allowance | **Nothing follows.** N=1 may be above the cap and N=10 comfortably under it. Gray. |

So an item whose pack size is unknown can be **green or gray — never red, and
never amber on price**. The verdict we can still give is the stronger one: a
green reached this way holds universally, not just for the reading we happened
to take.

### What it cost, and why it was worth it

The rule was written after a real wholesale invoice produced a **false red**:
`₹36 per strip` measured against a `₹0.93 per tablet` ceiling looked like
38.7×, which slipped under the 50× misread guard. The line was priced
perfectly normally. The bill simply never said "strip".

The gate costs coverage — most retail pharmacy lines state no pack size, so
they now resolve green-or-gray rather than sometimes amber. Three things
recover most of it:

- the **brand index** supplies a pack size for branded names;
- an **explicit volume** on the line ("Injection 500 ml") supplies it directly;
- **R6 against a printed MRP** would need no pack size at all, because MRP and
  the billed rate sit on the same row in the same unit. **R6 is not built** --
  the engine ships R1-R5 and R9. Listed here because it is the mitigation with
  the most headroom, not because it is running.

Regression tests: `test_wholesale_strip_price_is_never_red`,
`test_under_the_allowance_is_green_whatever_the_pack_size`,
`test_an_unknown_pack_size_can_never_produce_red_or_amber_on_price`.

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

### Reserved concurrency -- available, but off by default

`infra/template.yaml` takes a `ReservedConcurrency` parameter. Set it and a
retry storm costs that many concurrent invocations rather than a thousand -- a
ceiling the platform enforces, rather than one that depends on our retry logic
being right.

**It defaults to 0, which sets no reservation at all.** AWS refuses a
reservation that would leave the account under 10 unreserved concurrent
executions, and a new account's whole limit is often exactly 10 -- so reserving
even 1 fails and rolls the stack back. At 0 the template omits the property
rather than passing it, because passing 0 would mean "this function may never
run".

Nothing is lost on such an account: its own limit is the harder cap. Raise the
quota in Service Quotas first, then set this.

### Reject before you pay

Page count and upload size are checked **before any billable call is made**:
bills over 10 pages and oversized uploads are rejected at the API boundary.
Textract is priced per page, so a 400-page PDF is a $4 mistake from a single
careless upload. The check is cheap, the failure mode is not.

### No always-on resources

The SAM template has **no VPC**, therefore no NAT Gateway (~$32–45/month, the
the classic surprise on a small AWS bill). DynamoDB is on-demand, never
provisioned. S3
carries a 1-day lifecycle delete and CloudWatch a 7-day log retention. There
is no OpenSearch, no vector store, no EC2, no Fargate. **Idle cost is
effectively zero** — the stack can sit untouched indefinitely without
accruing anything. The spend is per upload, not per hour.

### Guardrails outside the code

`docs/AWS_STEPS.md` Section 0 sets up a $10 budget alerting at 50% and 100%,
a $25 tripwire, and account-level billing alerts — **before any resource is
created**. Free, and it means a runaway loop is caught at $5 rather than
surfacing at $80.

### What stays despite the cost

**Both readers.** Running Textract and a Bedrock vision model over the same
file and requiring them to agree is the most interesting thing this project
does, and it is not where the money goes — the second reader is cents. Cost
control never came at the expense of the verification design.
