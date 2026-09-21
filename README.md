# BillWise

**Upload an Indian hospital or pharmacy bill and find out which charges have a
published government price ceiling — and where each one sits against it.**

Every claim on screen shows its arithmetic, the government order number, and
the date that order was published. If a line cannot be checked, the report
says so plainly instead of implying the bill is fine.

Runs **fully offline with no AWS account** — the rule engine, the eval suite
and the whole UI work locally at zero cost. Deploying to AWS is optional and
uses **your own** account; nothing here points at anyone else's
infrastructure.

```
46/46 planted findings caught, 0 missed   ·   0 FALSE REDS
0 of 10 adversarial attacks succeeded     ·   301 tests, 11 frontend tests
```

**Those hold on a fresh clone with no extra steps** — clone, install, run. Do
not trust this block; regenerate it:

```bash
python -m pytest tests/ -q          # 253 passed, 48 skipped
python eval/run_eval.py             # caught 46/46 · missed 0 · FALSE REDS 0
python eval/adversarial_audit.py    # FALSE REDS: 0 / 10 attacks
```

The 48 skips are honest and each names the command that enables it. The
reduced brand index **is** committed, so matching and the eval work
immediately — nothing here is skipped for want of a download you need.

Two offline commands take it to **263 passed, 38 skipped**:
`scripts/make_demo_bills.py` and `scripts/stage_lambda.py`. The last 38 test
the FULL 36 MB brand-index build and only pass after
`scripts/fetch_brand_data.py` and `scripts/build_brand_index.py`, which need
a 254k-row download. All 301 pass here, where that index is built.

---

## The problem

India's National Pharmaceutical Pricing Authority publishes a maximum legal
price for **915 scheduled formulations** under the DPCO. No hospital or
pharmacy may charge above them.

It is a spreadsheet. Nobody standing at a pharmacy counter with a bill in
their hand is going to look it up.

BillWise is that lookup, pointed at a photo of your bill.

---

## What it deliberately will not do

These three constraints shaped every part of the build.

- **It never accuses anyone.** The words *illegal*, *fraud*, *cheating* and
  *overcharged* appear nowhere in the interface. A line is "above the listed
  ceiling" and "may need clarification". A false accusation against a pharmacy
  that billed correctly would end this product's credibility permanently;
  silence would not.
- **It never guesses a verdict.** If an item cannot be matched confidently, it
  is grey and the report says which kind of "we don't know" applies. Most
  lines on a real hospital bill — room rent, nursing, consumables, procedure
  fees — have **no public ceiling at all**, and saying so is the correct
  answer, not a failure.
- **No language model does the arithmetic.** Every comparison and every
  verdict is plain Python. A model that does your maths cannot explain its
  answer, and this product has to be able to explain itself to a hospital.

There is a fourth, learned the hard way: **state the denominator before the
numerator.** A report that checked nothing once rendered as "0 things worth
asking about" — every word true, and the whole screen a lie. The summary now
always leads with how many charges were actually compared.

---

## Try it

**Locally, offline, free** — `PROVIDER=local` makes zero network calls and
needs no AWS account. Full setup, including deploying to **your own AWS
account**, is in [`docs/self-hosting.md`](docs/self-hosting.md).

```bash
py -3.12 -m venv venv
source venv/Scripts/activate      # Linux/macOS: venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

The price reference ships with the repo, so there is nothing to build before
the tests and the eval will run. **The demo bills do not ship** — they are
generated, and this one offline command emits them:

```bash
PYTHONIOENCODING=utf-8 python scripts/make_demo_bills.py
```

Skip it and everything still works; a handful of artefact tests skip with a
message naming that exact command.

```bash
PYTHONIOENCODING=utf-8 python -m uvicorn app.main:app --reload --app-dir backend --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Create `frontend/.env` first (it is gitignored):

```
VITE_API_BASE=http://127.0.0.1:8000
VITE_USE_MOCKS=false
```

Open <http://localhost:5173> and click **Try a sample bill**. Add
`?fixture=bill_06` for a real retail-pharmacy layout where nothing is
price-controlled — the most interesting path in the product.

> **`PYTHONIOENCODING=utf-8` is not optional on Windows.** The code prints `₹`
> and the default console codec throws on it.
>
> **Local mode has no OCR**, so uploading a file will not work. Use the sample
> bills, or point `VITE_API_BASE` at the deployed API.

---

## How it works

```
  browser
     │  photo or PDF, up to 4 MB
     ▼
  API Gateway ──► Lambda (Python 3.12, FastAPI via Mangum)
                     │
                     ├──► S3            the uploaded bill
                     ├──► DynamoDB      the finished report
                     │
                     ├──► Textract AnalyzeExpense ──┐
                     │                              ├─► two independent readings
                     └──► Bedrock / Amazon Nova ────┘   cross-checked against
                                                         each other
                     │
                     ▼
              the rule engine — pure Python, no ML
              match → verify → price against NPPA ceilings
                     │
                     ▼
              red / amber / green / grey, every flag citing its S.O. number
```

Frontend is React 19 + Vite 8 + Tailwind 3.4 on **Amplify**. Infrastructure is
one **AWS SAM** template. Everything runs in `us-east-1`.

Full detail in [`docs/architecture.md`](docs/architecture.md).

---

## The two readers, and why

**The second reader is not there to be more accurate. It is there to
disagree.**

We measured this on the deployed system — same bill, two hours apart, one
variable changed:

| `bill_02.jpg` | **Two readers** | One reader |
|---|---|---|
| Lines at high confidence | 0 of 7 | 4 of 7 |
| Findings produced | **0** | **1, and it was wrong** |

Textract reported per-field confidence of **96–99% both times**. It had read a
column header as a line item and shifted every value onto the next row.

**Confidence is not accuracy, and a single reader cannot doubt itself.** When
the two readings disagree, the line goes grey and is never priced. Garbage in,
silence out.

---

## How we know it is not confidently wrong

```
python eval/run_eval.py            46/46 caught · 0 missed · FALSE REDS 0
python eval/adversarial_audit.py   0 of 10 attacks produced a false red
python -m pytest tests/ -q         301 passed
```

`run_eval.py` scores the engine against six bills with known planted problems.
**`FALSE REDS: 0` is the number that matters** — it means the system has never
told a patient a charge was wrong when it was not.

`adversarial_audit.py` actively tries to construct bills that cause one:
pack-size ambiguity, lost decimal points, alias collisions, fractional
quantities. None currently succeeds.

---

## What it cannot do

Stated plainly, because a tool like this is only useful if it admits its
limits. Measurements in [`docs/limitations.md`](docs/limitations.md).

- **Only the 915 price-controlled formulations can produce a finding.** Most
  of a real bill is out of NPPA's remit by nature. We report that as
  "no published ceiling", which is true and honest and not the answer anyone
  wanted.
- **English and Latin script only.** A vision model can read Devanagari, but
  the matcher normalises to Latin and compares against English NPPA data, so a
  Hindi or Marathi bill resolves to nothing.
- **Uploads cap at 4 MB**, which most phone cameras exceed. Browser-side
  downscaling is not built yet.
- **No reading-accuracy figure is claimed.** On clean PDFs it reads well; on
  degraded photographs it does not, and it goes grey rather than guessing.
  We do not have a number here we would defend.
- **Brand-name coverage is the real ceiling on usefulness.** On two real
  pharmacy bills, zero of ten brand names resolved.

---

## Deploying

Backend and frontend deploy separately and the frontend usually does not need
the backend.

**To deploy this to your own AWS account, follow
[`docs/self-hosting.md`](docs/self-hosting.md).** Nothing in this repo points
at anyone else's infrastructure — every AWS identifier is empty in
`.env.example` and you supply your own. The second reader is optional; without
Bedrock the app runs on Textract alone and says so on every report.

Every console step, with the failures that cost us hours, is in
[`docs/aws-deployment.md`](docs/aws-deployment.md). Two traps worth naming here:

- **`--build-dir` is not optional on `sam build`.** Without it, build and
  deploy can read different directories and you ship the previous build while
  CloudFormation reports complete success.
- **Amplify manual deploy takes a zip of `dist`'s CONTENTS**, so `index.html`
  sits at the archive root. Zipping the folder puts everything under `/dist/`
  and every path 404s.

---

## Repo layout

```
backend/app/        config, models, and the pipeline (match → verify → audit)
frontend/src/       React app; lib/api.ts is the ONLY file that knows the
                    backend's field names
eval/               the correctness suites, plus six bill fixtures and their
                    ground truth (the bill files themselves are generated)
tests/              pytest
scripts/            reference-data builders; the only networked one fetches brands
data/raw/           NPPA source files, unmodified
data/reference/     generated price reference and quarantine log
                    see data/README.md for what each file is and what reads it
infra/              the SAM template
docs/               see docs/README.md for an index
```

Every ruling that shaped the engine — thresholds, the two-reader design, why
gray is a correct answer — is in [`docs/decisions.md`](docs/decisions.md),
with the measurement behind each one. Read that first; it is short.

---

## Data sources

**Price ceilings — NPPA, Government of India.** Retrieved **18 September
2026**. Ceilings are exclusive of GST and carry the S.O. number and date under
which they were fixed. Every verdict displays this retrieval date.

| File | Rows | Role |
|---|---|---|
| All Drugs Ceiling Prices | 915 | Scheduled formulations. **The only source that can produce a red flag.** |
| Special Feature Schedule | 22 | Higher ceilings for special-feature packs. Additional to the above. |
| Retail Price Information | 3,881 | Non-scheduled new drugs. Context only, never a red flag. |

**Brand names — [Indian Medicine Dataset](https://github.com/junioralive/Indian-Medicine-Dataset)**
(~254,000 products, MIT). Used **only** to map brand names and pack sizes to
salts. Its prices are scraped and undated and are **never** used as a
reference — a test enforces that no field originating in it can reach a
verdict.

NPPA data is used for public-interest price transparency. **BillWise is not
affiliated with or endorsed by NPPA or any government body, and nothing here
is legal or medical advice.**

---

## Use of this code

This is a hackathon project, shared so the approach and the measurements can be
checked. No licence is attached, so the usual default applies: the code is not
offered for reuse. Ask if you want to build on it.

The data is a different matter and is not ours to restrict. NPPA price data is
public government information. The brand-name index comes from the MIT-licensed
Indian Medicine Dataset, credited above.
