# Running BillWise yourself

Two ways to run this. **Start with local** — it is free, needs no AWS account,
and exercises the whole rule engine.

| | Local | Your own AWS |
|---|---|---|
| AWS account needed | no | yes |
| Cost | **zero** | a few dollars a month idle; see below |
| Reads a real photo of a bill | **no** | yes |
| Rule engine, eval, tests | **yes, in full** | yes |
| Time to first run | ~10 minutes | ~1–2 hours, mostly waiting on AWS |

Nothing in this repository points at anyone else's infrastructure. Every AWS
identifier is empty in `.env.example` and you fill in your own.

---

# 1. Local — free, offline, no AWS

## Prerequisites

- **Python 3.12.** Not 3.14 — AWS Lambda tops out at 3.13, so 3.12 is the
  target. Other 3.12+ versions will probably work; 3.12 is what is tested.
- **Node 20+** for the frontend.

## Backend

```bash
git clone <your fork> && cd <repo>
py -3.12 -m venv venv
source venv/Scripts/activate      # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env.example` already sets `PROVIDER=local`, which makes **zero network calls
and costs nothing**. You do not need to edit it.

The NPPA price reference ships with the repo, so there is nothing to build.
Check it works:

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/ -q
```

```bash
PYTHONIOENCODING=utf-8 python eval/run_eval.py
```

You should see tests passing and `caught 46/46 · missed 0 · FALSE REDS 0`.

> **`PYTHONIOENCODING=utf-8` is not optional on Windows.** The code prints `₹`
> and the default console codec raises `UnicodeEncodeError` on it.

To lint, from the repo root:

```bash
ruff check backend/ scripts/ eval/ tests/
```

`ruff.toml` pins the rule set, so this gives the same answer on every machine
and every ruff version. It should report no findings.

A few tests will skip until you generate the demo bills. They are synthetic
and not committed:

```bash
PYTHONIOENCODING=utf-8 python scripts/make_demo_bills.py
```

## Run it

```bash
PYTHONIOENCODING=utf-8 python -m uvicorn app.main:app --reload --app-dir backend --port 8000
```

In a second terminal, create `frontend/.env` (it is gitignored, so it is not
in the repo):

```
VITE_API_BASE=http://127.0.0.1:8000
VITE_USE_MOCKS=false
```

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173> and click **Try a sample bill**. Add
`?fixture=bill_06` to the `/check` URL for a retail-pharmacy layout where
nothing is price-controlled — the most interesting path in the product.

## What local mode does NOT do

**There is no OCR.** Uploading a photo returns zero lines and says so, rather
than inventing a reading. The sample bills work because their readings are
fixtures. Everything downstream of reading — matching, verification, the rule
engine, the report, the letter — is the real thing.

**Only port 5173 is allowed by CORS** (`backend/app/main.py`). On any other
port every request fails as a bare "Network error".

---

# 2. Your own AWS account

You are creating your own stack, in your own account, with your own bucket,
table and endpoints. Nothing is shared with anyone else's deployment.

## What it costs

Idle, this is a few dollars a month — Lambda, API Gateway, S3 and DynamoDB
are near-free at rest, and Amplify hosting is cheap. The variable cost is per
upload: **Textract is priced per page and Bedrock per token**, so each bill
processed costs real money.

**Set a budget before you create anything.** `AWS_STEPS.md` section 0 walks
through a $10 budget and a $25 tripwire; both are free and take ten minutes.
Do not skip this.

## Prerequisites

- An AWS account, and the **AWS CLI** signed in (`aws configure sso`, or an
  IAM user)
- **AWS SAM CLI**
- **Docker**, for `sam build --use-container`
- Model access in **Bedrock** if you want the second reader — see below

## The order, and why it matters

There is a circular dependency: the API only accepts requests from your
frontend's origin, but that origin does not exist until the frontend is
deployed. So:

```
0.  Budgets                    AWS_STEPS.md section 0
1.  Bedrock model access       AWS_STEPS.md section 1   (optional, see below)
2.  Deploy the backend         with FrontendOrigin EMPTY
3.  Deploy the frontend        Amplify gives you a domain
4.  Redeploy the backend       now with FrontendOrigin set to that domain
```

**Do not try to guess the Amplify domain in advance.**

### The second reader is optional

Leave `BedrockInferenceProfileId` empty and the app runs on **Textract
alone**. It degrades deliberately rather than failing: with one reader it
applies a stricter confidence bar, and says on each report that the
cross-check did not run.

You lose the thing the project is proudest of — two readers disagreeing
catches confident misreads a single confidence score does not — but you get a
working deployment without touching Bedrock.

If you do want it: any Converse-capable model works, because the reader uses
Bedrock's **Converse** API and is model-agnostic. Keep a **geo prefix** like
`us.` rather than `global.` — a geo profile routes to a small fixed set of
Regions that `infra/template.yaml` pins in IAM, and that pin is the only thing
constraining where a medical bill travels.

## Step 2 — deploy the backend

Stage the reference data into the Lambda bundle first. **Staging must come
before the build**, because it writes into `backend/` and the build copies
`backend/`:

```bash
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe scripts/stage_lambda.py
```

On Linux or macOS that interpreter is `./venv/bin/python`.

Use the venv interpreter, not a bare `python` — the system Python has no
pydantic and this dies halfway through, after copying the data, which looks
like partial success.

**You do not need to download anything for brand matching.** The reduced
brand index (13.5 MB of a 36 MB source) is committed, so staging finds it
already in place and says so. `fetch_brand_data.py` and `build_brand_index.py`
exist for rebuilding it if the NPPA reference data changes — not for a first
deploy.

```bash
sam build --use-container --template infra/template.yaml --build-dir <ABSOLUTE_PATH_OUTSIDE_THE_REPO>
```

Pick a path outside the repo and outside any synced folder (OneDrive,
Dropbox, iCloud) — a sync client holds file handles open while SAM wipes the
build directory.

**`--build-dir` is not optional.** Omit it and `sam build` and `sam deploy`
can read different directories, so you ship an older build while
CloudFormation reports complete success. `stage_lambda.py` prints the full
command with this flag when it finishes, so you can copy it from there.

```bash
sam deploy --guided
```

`samconfig.toml` is gitignored, so you will not inherit anyone's settings —
`--guided` prompts for everything and writes your own. Leave `FrontendOrigin`
empty this first time.

Note the **ApiUrl** in the outputs.

## Step 3 — deploy the frontend

Point the production build at your API. Create `frontend/.env.production`:

```
VITE_API_BASE=https://<your-api-id>.execute-api.<your-region>.amazonaws.com
VITE_USE_MOCKS=false
```

```bash
cd frontend && npm run build
```

Then zip the **contents** of `frontend/dist`, so `index.html` sits at the root
of the archive:

```bash
python -c "import zipfile,os; r='frontend/dist'; z=zipfile.ZipFile('frontend.zip','w',zipfile.ZIP_DEFLATED); [z.write(os.path.join(d,f), os.path.relpath(os.path.join(d,f),r).replace(os.sep,'/')) for d,_,fs in os.walk(r) for f in fs]; z.close()"
```

Zipping the **folder** instead puts everything under `/dist/` and every path
404s. On Windows, do not use PowerShell's `Compress-Archive` — it writes
backslash separators, which some unzippers take literally and the site serves
a blank page.

In the Amplify console: **Create new app → Deploy without Git provider**,
upload the zip, and note the domain it gives you.

Add a rewrite rule so deep links work — **App settings → Rewrites and
redirects**: source `/<*>`, target `/index.html`, type `404 (Rewrite)`.

## Step 4 — redeploy the backend with the origin

```bash
sam deploy --parameter-overrides FrontendOrigin=https://<your-amplify-domain>
```

Until this runs, the browser cannot reach the API and every request fails as
a bare "Network error".

## Verify

A green CloudFormation stack says the deploy worked, **not that it deployed
what you built**. Check the behaviour:

```bash
curl https://<your-api>/health
```

Then open your Amplify URL and run **Try a sample bill**. If a report renders,
the whole path works: browser → Amplify → API Gateway → Lambda → engine.

---

# 3. Tearing it down

`sam delete` removes the backend stack. Delete the Amplify app from its
console. The S3 bucket and DynamoDB table both expire their contents after one
day, but the resources themselves go with the stack.

If you only want to stop spending while keeping the stack, the honest answer
is that an idle stack already costs almost nothing — the spend is per upload.

---

# 4. Known limits before you invest time

Full detail with measurements in [`LIMITS.md`](LIMITS.md).

- Only the **915 price-controlled formulations** can produce a finding. Most
  of a real bill is out of NPPA's remit and reports as "no published ceiling".
- **English and Latin script only.** The matcher compares against English NPPA
  data, so a Hindi or Marathi bill resolves to nothing.
- **Uploads cap at 4 MB**, a transport limit rather than a policy choice.
- **The API is unauthenticated and unthrottled.** If you deploy this publicly,
  add rate limiting first — `AWS_STEPS.md` 9.3. Every upload spends money.
- **No reading-accuracy figure is claimed.** Good on clean PDFs, poor on
  degraded photographs, and it goes grey rather than guessing.

---

# 5. If something goes wrong

`AWS_STEPS.md` is the long form of everything above, written as it was
actually done, including six environment failures on the first deploy and what
each one really meant. Its "Troubleshooting the first deploy" section covers
the ones most likely to hit you: Lambda reserved concurrency on a new account,
`sam build` appearing to hang, and Bedrock access errors that look like IAM
problems but are not.
