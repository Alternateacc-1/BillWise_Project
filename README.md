# BillSahi

Upload an Indian hospital or pharmacy bill and see which charges may need
clarification — with the evidence behind each one, and a polite letter you can
send asking the hospital to explain them.

> **Status: Phase 2 of 6.** The engine runs end to end offline and is scored
> against ground truth: **39/39 findings caught, 0 missed, 0 false reds**
> across 5 synthetic bills. 207 tests green. The API and UI are not built yet.

---

## What it does

A bill is read, the reading is **verified against itself**, item names are
resolved to their salts, and those are matched against India's published
price ceilings. Deterministic rules then produce a red / amber / green / gray
report where every flag cites its source row, SO number and date.

Three things it deliberately will not do:

- **It never accuses anyone.** The words illegal, fraud, cheating and
  overcharged appear nowhere in the interface. An item is "above the listed
  ceiling price" and "may need clarification".
- **It never guesses a verdict.** If we cannot confidently match an item, it
  is gray and we say so. Most items on a real hospital bill — room rent,
  nursing, consumables, procedure fees — have **no public price ceiling at
  all**, and the report says that plainly rather than implying a gap.
- **No language model does the arithmetic.** Code decides every verdict; the
  model only writes the explanation.

---

## Data sources

**Price ceilings — NPPA (National Pharmaceutical Pricing Authority),
Government of India.** Retrieved **18 September 2026**. Ceiling prices are
exclusive of GST and carry the S.O. number and date under which they were
fixed. Every verdict in the interface displays this retrieval date.

| File | Rows | Role |
|---|---|---|
| All Drugs Ceiling Prices | 915 | Scheduled formulations. The only source that can produce a red flag. |
| Special Feature Schedule | 22 | Higher ceilings for special-feature packs. Additional to the above. |
| Retail Price Information | 3,881 | Non-scheduled new drugs. Context only, never a red flag. |

**Brand names — [Indian Medicine Dataset](https://github.com/junioralive/Indian-Medicine-Dataset)**
(~254,000 products, **MIT licence**). Used **only** to map brand names and
pack sizes to salts. Its prices are scraped and stale and are **never** used
as a price reference — a test enforces that no field from it can reach a
verdict.

NPPA data is used for public-interest price transparency. BillSahi is not
affiliated with or endorsed by NPPA or any government body.

---

## Running it

Requires **Python 3.12** (Lambda's ceiling is 3.13; 3.12 is the target).

```bash
git clone <this repo> && cd BillSahi_v1
py -3.12 -m venv venv
source venv/Scripts/activate        # Windows Git Bash; use bin/activate on Linux/macOS
pip install -r requirements.txt
cp .env.example .env
```

Build the price reference from the NPPA source files:

```bash
PYTHONIOENCODING=utf-8 python scripts/prepare_reference.py
```

Build the brand-name index. This is the **only** step that needs the network:

```bash
PYTHONIOENCODING=utf-8 python scripts/fetch_brand_data.py
```

```bash
PYTHONIOENCODING=utf-8 python scripts/build_brand_index.py
```

Audit a sample bill and see a full report:

```bash
cd backend && python -m app.cli audit ../eval/fixtures/bill_01.json
```

Score the engine against ground truth:

```bash
python eval/run_eval.py
```

Run the tests:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/ -q
```

`PYTHONIOENCODING=utf-8` is not optional on Windows — the rupee sign crashes
the default console codec.

Everything runs **offline**. `PROVIDER=local` (the default) uses no network
and costs nothing.

---

## Layout

```
data/raw/           the NPPA source files, unmodified
data/reference/     generated: reference_prices.csv, quarantine_log.csv, unit_coverage.json
scripts/            prepare_reference.py and friends
backend/app/        config, models, pipeline
tests/              pytest
docs/               ARCHITECTURE.md, OPEN_QUESTIONS.md, AWS_STEPS.md
```

`NOTES.md` holds the working notes — environment gotchas, data quirks, and
the bugs already found and fixed.

---

## Licence

Code: MIT. NPPA price data is public government information. The brand
dataset is MIT and credited above.
