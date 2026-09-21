# BillWise — brief for the next person working on the frontend

**Paste this whole file to your AI assistant as the first message of the
session.** It is written to be read cold, by someone who has never seen this
project, and to be enough on its own.

---

## 1. What you are working on

A patient uploads a photo or PDF of an Indian hospital or pharmacy bill. The
system reads it, compares each line against India's published NPPA/DPCO
ceiling prices, and shows what may be worth asking the hospital about — with
the arithmetic and the government order number shown for every claim.

It is **live and working**:

- Frontend: AWS Amplify, React 19 + Vite 8 + Tailwind 3.4 + TypeScript
- API: AWS Lambda (FastAPI via Mangum) in `us-east-1`
- Readers: AWS Textract **and** Amazon Nova via Bedrock — two independent
  readings of every bill, cross-checked against each other
- Engine: pure Python, no ML in the verdict path
- 300 tests, plus an eval suite over six bill fixtures

**It is not a fraud detector.** It helps a patient ask an informed question.
That framing runs through every word of the interface.

---

## 2. Your remit

**Change anything you want.** Frontend, backend, engine, copy, layout,
architecture. There is no part of this you are forbidden from touching, and
if something is badly built you should say so and fix it.

**One obligation, and it is absolute: write down what you did and why.**

Every change goes in `docs/CHANGES_BY_<yourname>.md`, in the format in
section 6. The owner will read that file to understand the work — it is how
they review it, so an unlogged change is worse than no change.

---

## 3. Get it running (10 minutes)

**Backend** — Python 3.12. From the repo root:

```bash
python -m venv venv
./venv/Scripts/python.exe -m pip install -r requirements.txt
cp .env.example .env
```

`.env.example` defaults to `PROVIDER=local`, which runs fully offline, makes
zero AWS calls and costs nothing. Then:

```bash
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -m uvicorn app.main:app --reload --app-dir backend --port 8000
```

`PYTHONIOENCODING=utf-8` is not optional on Windows — the code prints `₹` and
the default console encoding throws `UnicodeEncodeError`.

**Frontend** — Node 24:

```bash
cd frontend && npm install
```

Create `frontend/.env` yourself (it is gitignored, so it is not in the repo):

```
VITE_API_BASE=http://127.0.0.1:8000
VITE_USE_MOCKS=false
```

```bash
npm run dev
```

**Local mode has no OCR, so uploading a file will not work.** Click **Try a
sample bill**. Add `?fixture=bill_06` to the URL for a different layout — that
one is a real retail-pharmacy structure where nothing is price-controlled, and
it exercises the most interesting path.

To test real uploads, point `VITE_API_BASE` at the deployed API instead. Ask
the owner for the URL.

---

## 4. How to know if you broke something

Two commands. They take about a minute.

```bash
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -m pytest tests/ -q
```

```bash
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe eval/run_eval.py
```

Current state: **300 tests pass**, and the eval reports:

```
caught 46/46 · missed 0 · FALSE REDS 0
```

**`FALSE REDS: 0` is the number that matters.** A false red means the system
told a patient a charge was wrong when it was not. That is the one failure
this product cannot survive — a hospital or pharmacy that billed correctly,
publicly accused by a tool a patient trusted.

If your change makes that non-zero, it is not a tradeoff to weigh. Something
is wrong. Fix it or revert it, and either way write down what happened.

There is also `PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe eval/adversarial_audit.py`,
which actively tries to construct bills that produce a false red. It currently
reports 0 out of 10 attacks succeeding.

If you rebuild the engine such that these suites no longer apply, that is
allowed — but replace them with something that proves the same property, and
explain in your log why the new thing is at least as strong.

---

## 5. What you need to know before changing the UI

### The architecture seam

**`frontend/src/lib/api.ts` is the only file that touches the network or
knows the backend's field names.** Everything above it works in UI types. It
has survived a complete frontend replacement without the pages changing.

Read its header comment before editing it. It documents four places where the
engine returns more than the UI's original contract expected, and flattening
any of them makes the interface state something untrue.

### Five things that look like clutter and are not

Each of these is a bug that reached a real user's screen. **Reword them
freely — the current wording is too technical and a patient should not have to
read it. But do not delete the information they carry**, and if you decide the
information is not worth carrying, say so explicitly in your log so the owner
can disagree.

| On screen | Why it is there |
|---|---|
| "We compared **4 of 16** charges" | Without the denominator, a bill where *nothing* could be checked looked identical to a clean bill. It rendered "0 things worth asking about" on a bill it had not checked at all. |
| "This does not mean the bill is fine" | Same bug. Falsely reassuring a patient about a medical bill is as damaging as falsely accusing a pharmacy. |
| No "write a letter" button when there are 0 findings | Offering to complain when nothing was found is a credibility leak in the exact place the product earns trust. |
| Separate "could not be read" and "could not be identified" groups | Different admissions. One blames our reading; the other says the medicine is unknown to us. Collapsing them claimed we had misread 5 of 6 lines we had read perfectly. |
| "N of M lines were seen by only one reader" | The two-reader cross-check is what protects the price rules from a confident misread. When it did not run on a line, the report has to say so. |

The **"Show evidence"** expander is the right pattern for anything technical:
lead with the plain answer, put the machinery behind the expander. The current
report leans too far toward showing everything at once — six groups is a lot
for someone who just wants to know whether their bill is okay. Improving that
is real work and it is wanted.

### Words that must not appear in user-facing text

**illegal · fraud · cheating · overcharged**

The product says "may need clarification" and "above the listed ceiling". It
never accuses. This is a deliberate legal and ethical position, not timidity.

### Gray is a good answer

Roughly half of a real bill comes back gray — not price-controlled, or not
confidently readable. **That is the system working.** Do not redesign gray as
an error state or hide it; a patient learning "we could not check 8 of these
12 charges, and here is why" is being told something true and useful.

---

## 6. The log — the one thing that is required

Create `docs/CHANGES_BY_<yourname>.md` and append an entry as you go. Not at
the end — as you go, because the reasoning is the part that gets lost.

```markdown
## <date> — <short title>

**What I changed:** files and a one-line description.

**Why:** the problem you were solving. If it was a judgement call, say what
the alternatives were and why you rejected them.

**How I checked it:** what you ran or clicked, and what you saw.

**Anything I am unsure about:** things the owner should look at, or that you
would do differently with more time.
```

Two rules for the log:

- **Record decisions you made that could reasonably have gone the other way.**
  "Renamed the button" needs one line. "Merged the four gray groups into two
  because a patient cannot act on the distinction" needs the reasoning, because
  the owner may disagree and will need to know what you traded away.
- **Record what you tried that did not work.** A dead end you document saves
  the next person from walking down it.

If you change anything under `backend/app/pipeline/`, include the output of
the two commands from section 4 in that entry.

---

## 7. Deploying

Frontend and backend deploy separately, and you may not need the backend at
all.

**Frontend** — Amplify manual deploy, no Git provider needed:

```bash
cd frontend && npm run build
```

Zip the **contents** of `frontend/dist`, so `index.html` sits at the root of
the archive. Zipping the folder puts everything under `/dist/` and the site
returns 404 for every path — this has already happened once. Then in the
Amplify console: the app → `prod` → **Deploy updates** → upload the zip.

The app reads its own URL for `?fixture=`, so add a rewrite rule under **App
settings → Rewrites and redirects** if it is not already there:
source `/<*>`, target `/index.html`, type `404 (Rewrite)`.

**Backend** — `docs/AWS_STEPS.md` section 10 has the exact commands. Two
traps that have each cost an hour:

- **`--build-dir` is not optional** on `sam build`. Without it, build and
  deploy read different directories, and you ship the previous build while
  CloudFormation reports complete success.
- **`File with same data already exists ... skipping upload`** in the deploy
  output means your Python did **not** ship. After editing backend code that
  line is a failure, not an optimisation.

**A green CloudFormation stack does not mean it deployed what you built.**
Verify with the probes in section 10.4.

---

## 8. Known limits — check here before "fixing" something

`docs/LIMITS.md` has these in full, with the measurements behind them.

- **Uploads cap at 4 MB**, not 10. API Gateway base64-encodes the body into a
  6 MB Lambda event. Above roughly 4.5 MB the gateway returns 413 *without
  CORS headers*, so the browser cannot read it and shows a bare "Network
  error". A better fix is downscaling in the browser before upload, or a
  presigned S3 upload. Neither is built.
- **No multilingual support.** A vision model can read Devanagari, but the
  matcher normalises to Latin and compares against English NPPA data, so the
  name resolves to nothing. Needs transliteration between reading and
  matching. Currently out of scope and stated as such.
- **Currency is assumed to be rupees** and nothing checks it. A Singapore
  bill rendered S$ as ₹.
- **Retail prices are deliberately not used as ceilings.** They bind one
  company's product, span 13 years of notifications with no way to tell which
  are still current, and only 21% of their compositions parse cleanly.
- **The two readings are paired by content** (name similarity + amount), not
  by row position. Position pairing broke whenever the readers disagreed on
  how many rows a bill had.

---

## 9. Where the rest of the context is

- **`docs/DECISIONS.md`** — every ruling that must not be re-litigated, with
  the measurement behind it. If you are about to make a non-obvious change,
  read it first; there is a fair chance the question has already been settled
  with evidence.
- **`docs/LIMITS.md`** — what the tool cannot do and why.
- **`docs/ARCHITECTURE.md`** — how the pipeline fits together.
- **`docs/AWS_STEPS.md`** — every console step and command, with the failures.
- **`eval/`** — the correctness suites. `run_eval.py` is the gate;
  `adversarial_audit.py` attacks it; the `*_probe.py` scripts answer specific
  questions by measurement.

**One habit worth copying from this codebase: measure before you conclude.**
The notes were confidently wrong three times in one day about what was broken,
and each time a five-minute script settled it. If you find yourself about to
act on something a document asserts, check whether it is still true first.
