# AWS steps

Everything that touches an AWS account. **Claude never runs any of this** —
it writes the steps, prints `AWS CHECKPOINT: run docs/AWS_STEPS.md section N`,
and stops. You run it and paste the output back.

Written for someone who has never used AWS. Every step says what it does, what
it costs, and how to check it worked.

> **Console menus move.** Where a path like *Billing → Budgets* no longer
> matches what you see, use the search bar at the top of the console and
> search the service name. The concepts below do not change even when the
> menus do.

---

# Section 0 — Billing guardrails

**Do this before creating a single resource.** Not at the end, not "once it
works". A runaway loop should page you at $5, not surface at $80.

**Cost of this section: $0.** Budgets and billing alerts are free.

**Time: about 10 minutes.**

---

## 0.1 Turn on billing alerts

Without this, CloudWatch cannot see billing metrics at all.

1. Sign in as the **root user or an admin**. Billing settings are not visible
   to a restricted IAM user unless access has been delegated.
2. Top-right account menu → **Billing and Cost Management**.
3. Left sidebar → **Billing preferences**.
4. Under **Alert preferences**, tick **Receive AWS Free Tier alerts** and
   **Receive CloudWatch billing alerts**.
5. Put your real email in the free-tier alert box.
6. **Save preferences.**

**Verify:** reload the page. Both boxes are still ticked.

> **Gotcha:** billing metrics only exist in **us-east-1**, no matter where
> your stack runs. Ours happens to run there too, so for us they line up —
> but do not learn the wrong lesson from that coincidence. If this stack ever
> moves to another Region, billing metrics **stay** in us-east-1, and a
> CloudWatch console pointed anywhere else will show nothing and look broken.
>
> This is fixed in AWS and is not a setting you control.

---

## 0.2 The $10 budget with alerts at 50% and 100%

This is the working alarm — it should fire in normal use if something is off.

1. **Billing and Cost Management** → left sidebar → **Budgets**.
2. **Create budget**.
3. Choose **Customize (advanced)** → budget type **Cost budget** → **Next**.
4. Fill in:
   - **Budget name:** `billsahi-10-usd`
   - **Period:** Monthly
   - **Budget renewal type:** Recurring budget
   - **Start month:** the current month
   - **Budgeting method:** Fixed
   - **Enter your budgeted amount:** `10`
5. **Next**, then **Add an alert threshold**:
   - **Threshold:** `50` **% of budgeted amount**
   - **Trigger:** Actual
   - **Email recipients:** your email
6. **Add an alert threshold** again:
   - **Threshold:** `100` **% of budgeted amount**
   - **Trigger:** Actual
   - **Email recipients:** your email
7. **Next** → skip attaching any action → **Create budget**.

**Verify:** the Budgets list shows `billsahi-10-usd`, budgeted $10, with
**2 alerts**. Current spend will read $0 or close to it.

---

## 0.3 The $25 tripwire

The $10 budget tells you to look. This one means something is actually wrong.

Repeat 0.2 exactly, with:

- **Budget name:** `billsahi-25-usd-tripwire`
- **Budgeted amount:** `25`
- **One** alert threshold: `100`% of budgeted amount, **Actual**, your email

**Verify:** Budgets list now shows two budgets.

---

## 0.4 Confirm the alert emails arrive

An alarm you never receive is not an alarm.

AWS does not send a test email for budgets. Do this instead:

1. Create a third, throwaway budget named `billsahi-alarm-test` with a
   budgeted amount of **`0.01`** and one alert at **1%**, **Actual**.
2. If your account has any spend at all, the alert fires within ~24 hours.
   Budgets evaluate roughly three times a day, so **this is not instant.**
3. Once the email arrives, **delete `billsahi-alarm-test`.**

If nothing has arrived after a day, check your spam folder, then confirm the
email address on the budget is one you actually read.

> **Do not skip the deletion.** A budget at $0.01 will email you forever.

---

## 0.5 Note the free-tier trap

Free-tier allowances depend on **account age**, not on this project:

| Allowance | Lasts |
|---|---|
| Lambda 1M requests + 400k GB-s/month | forever |
| API Gateway 1M requests/month | 12 months from account creation |
| Amplify build minutes and hosting | 12 months |
| Textract AnalyzeExpense 100 pages/month | 3 months |

**If the account is older than 12 months, assume no free tier and add a few
dollars to the estimate.** It does not change the conclusion — the total is
still well under $100 — but it changes what "normal" looks like on the
budget page, and you should know which world you are in before an alert
makes you panic.

**Write down here which one applies, once you know:**

```
Account created:        ____________________
Free tier still active: yes / no
```

---

## Section 0 checklist

- [ ] Billing alerts enabled (0.1)
- [ ] `billsahi-10-usd` exists with alerts at 50% and 100% (0.2)
- [ ] `billsahi-25-usd-tripwire` exists with an alert at 100% (0.3)
- [ ] A test alert email was received, and the test budget was deleted (0.4)
- [ ] Account age and free-tier status recorded (0.5)

Only after every box is ticked should any resource be created.

---

## Why there are no CLI commands in this section

The console is the right tool here: these are one-time, low-frequency setup
steps, and doing them by hand means you have seen the billing pages before
the day you urgently need to read them.

The `aws budgets` CLI can do all of the above, but writing those commands
would mean guessing at JSON parameter shapes, and this project does not guess
at AWS API shapes. If you want them scripted later, look them up in the AWS
Budgets API reference and add them here once verified.

---

# Section 1 — Bedrock model access  (START THIS FIRST)

**This is the long pole and it is not under our control.**

**Cost: $0.** Enabling access costs nothing; you pay per token when you call it.

**Time: 10 minutes, then possibly a wait.**

> **Rewritten 2026-09-19 against the console as it actually is.** The old
> version described a "Model access" page that the current console does not
> have in that place, and it completely missed the step that actually blocks
> everything. If what you see disagrees with what is written here, trust your
> screen and tell me.

---

## 1.1 Submit Anthropic use case details  ← THE REAL GATE

**Do this first. Nothing else in this section works until it clears.**

Anthropic requires first-time customers to submit use case details before
invoking any of their models. It is **once per account** and applies to
**every Anthropic model in every Region**.

**This is the single most misleading step in the whole deployment**, because
an account that has not submitted it looks exactly like a Region where Claude
is not offered. That mistaken reading cost us a full stack migration to
us-east-1 and back. Remember the distinction:

> "The model is not offered in this Region" and "this account may not call
> the model anywhere yet" look **identical** from inside the console.

1. Bedrock console → **Model catalog** → open any Anthropic model.
2. A yellow banner appears: *"Anthropic requires first-time customers to
   submit use case details before invoking a model."* → **Submit use case
   details**.
3. Fill it honestly. It is shared with Anthropic.
   - **Company name / website** — a real URL. It validates the format, so it
     needs the `https://` prefix.
   - **Industry** — Other → Student, if that is what you are.
   - **Intended users** — External (this is for patients, not staff).
   - **Describe your use cases** — **max 500 characters**, and it counts
     strictly. Text that works, at 483 characters:

```
Helps Indian patients understand hospital and pharmacy bills. It reads an uploaded bill image and matches each medicine against the NPPA's published DPCO ceiling prices (public government data), then shows which line items sit above the published ceiling, with the citation and the arithmetic. It also drafts a polite letter asking the hospital to clarify those charges. All verdicts come from deterministic code; the model only reads the document. Hackathon project, non-commercial.
```

   Two things deliberately **not** claimed there, because both would be
   false: that the tool detects fraud or overcharging (we never prove a price
   is wrong, only that it is above a published ceiling), and that the model
   decides anything (it reads; deterministic code decides).

**Verify:** the yellow banner is gone from the model page.

---

## 1.2 Confirm a vision-capable Claude in us-east-1

1. Region selector, top right → **US East (N. Virginia) us-east-1**.
2. Bedrock → **Model catalog** → find a **Claude Sonnet** model.
3. Check it takes **image input**. On a model card this shows as an icon row
   reading `T 🖼 → T`, or on the model's detail page as an **Input Modalities**
   table with **Image** ticked.

**Vision is not optional** — the reader sends a photograph of a bill. A
text-only model cannot do this job at all.

**Verify and write down:**

```
Model chosen        : ____________________
Image input         : yes / no
```

---

## 1.3 Copy the US geo inference profile ID

We reach Claude through the **US geo cross-region inference profile**, not a
bare model ID and **not the global profile**.

1. Bedrock → left sidebar → **Infer → Inference profiles**.
2. Find the row for your model with the **`us.`** prefix.
3. **Copy it with the button. Do not retype it.**

For Claude Sonnet 4.6 the ID is:

```
us.anthropic.claude-sonnet-4-6
```

The short form is correct — this model generation has no date or version
suffix, unlike older ones such as
`us.anthropic.claude-sonnet-4-20250514-v1:0`.

**Paste it into `.env` as `BEDROCK_INFERENCE_PROFILE_ID`.**

### Why the US profile and not Global

Both work from `us-east-1`. The difference is where a patient's bill can go.

| | `us.` geo | `global.` |
|---|---|---|
| Destinations from us-east-1 | **3**: us-east-1, us-east-2, us-west-2 | **33**, across Americas, EMEA and Asia Pacific |
| List changes over time? | **Never** (AWS guarantees it for geo-tied profiles) | Yes, as AWS adds Regions |
| Can you state where data went? | Yes | No |

Because the geo list is fixed, `infra/template.yaml` pins those three Regions
in the IAM policy. **That policy is the data-residency control** — nothing else
in the system stops a bill leaving them. On the global profile this is
impossible: the destination list changes, so the foundation-model ARNs would
have to stay wildcarded.

This matters more here than in most projects. What we send Bedrock is a
photograph of a real medical bill, carrying a patient's name, registration
number and a drug list that implies a diagnosis.

> **On the region choice generally.** The original target was `ap-south-1`
> (Mumbai), to sit near the Indian users this tool is for. Two facts decided
> against it, both from AWS model cards rather than assumption:
>
> 1. **Claude Sonnet 4.6 supports no geo profile from `ap-south-1`** — only
>    the global one. So Mumbai would have meant 33 destination Regions, while
>    N. Virginia means 3. The privacy-preferring choice is the US Region, which
>    is not the intuitive answer.
> 2. **Textract `AnalyzeExpense` runs at 5 TPS in `us-east-1`, 1 TPS in
>    Mumbai.**
>
> The cost is real: latency to Indian users is worse than the design wants.
> That is stated plainly in `docs/ARCHITECTURE.md` rather than glossed over.

---

## 1.4 Test it in the playground before deploying anything

**Do not skip this.** Every reading-quality number this project has describes
fixtures we wrote ourselves. This is the first time a model sees a real bill
image, it costs about two cents, and nothing is deployed yet.

1. Bedrock → **Playground** (or **Open in playground** from the model page).
2. Attach `eval/demo_bills/bill_02.jpg` — the mild scan.
3. Ask: *"List every line item on this bill with its quantity, rate and
   amount, and the printed total. Do not guess any value you cannot read."*
4. Repeat with `eval/demo_bills/bill_05.jpg` — the fax-grade scan.
5. Repeat with `eval/demo_bills/bill_06.pdf` — the retail layout with MRP and
   PACK columns and no unit-price column.

Ground truth for all three is in Section 2.2, generated from the fixtures.

**Record what actually came back:**

```
bill_02.jpg (mild)   : ____ of 7 lines correct   total found: yes / no
bill_05.jpg (heavy)  : ____ of 3 lines correct   total found: yes / no
bill_06.pdf (retail) : ____ of 6 lines correct
                       MRP column read?  yes / no
                       PACK column read? yes / no
                       subtotal/discount/net split? yes / no
```

**What each outcome changes:**

- **Mild reads well, heavy fails.** Expected best case. Nothing changes.
- **Mild reads badly too.** The crop-and-re-read pass becomes load-bearing
  rather than a nicety, and Bedrock may need to be the primary reader with
  Textract as the second opinion rather than the other way round.
- **bill_06 returns MRP and PACK.** Class C becomes nearly free, and the
  honest verdict on a real retail bill goes from six grays to six greens.

Whatever the numbers are, they are the numbers. They replace the fixture
figures in the video. See NOTES.md, "Which numbers are ours to claim".

---

## 1.5 Report back

- the model you enabled, and that image input is supported
- the `us.` inference profile ID
- the Region you did it in
- the playground results from 1.4

**If 1.1 does not clear, say so immediately** — it blocks Sections 2 and 3
entirely, and it is not something waiting will fix.

---

# Section 2 — Run Textract on the two degraded scans  (START IN PARALLEL)

**Why this is its own step, before any deployment:** every reading-quality
number we have comes from hand-written fixtures, not OCR. We do not know how
real Textract behaves on a real scan, and that is the single biggest unknown
left in the project. It is also the thing the demo video depends on. Find out
now, not after the stack is up.

**Cost: about $0.05.** Five AnalyzeExpense pages at roughly $0.01 each. The
first 100 pages/month are free for the first 3 months if the account is new.

**Time: 10 minutes.**

---

## 2.1 Upload the two scans in the console

No code, no SDK, no deployment. The console does this by hand.

1. Region selector → **us-east-1** (same region as Section 1).
2. Search **Textract** → open it.
3. Left sidebar → **Analyze Document** → choose **Expense analysis** (this is
   AnalyzeExpense, the API our reader uses — NOT plain text detection).
4. Upload, one at a time:
   - `eval/demo_bills/bill_02.jpg` — the **mild** scan. A phone photo: slight
     rotation, a soft shadow, reduced contrast. **This one should mostly
     work.**
   - `eval/demo_bills/bill_05.jpg` — the **heavy** scan. Fax-grade. **This one
     may return almost nothing, and that is a legitimate result.**
   - `eval/demo_bills/bill_06.pdf` — the **retail pharmacy layout**: MRP,
     PACK, QTY, TOTAL and **no unit-price column**, with a Discount and Round
     Off in the totals block. Added 2026-09-18 after probing a real bill of
     this shape. It is a clean generated PDF, so this is not a reading-quality
     test — it asks a different question: **does AnalyzeExpense return the
     MRP and PACK columns as usable fields, and does it report the subtotal,
     the discount and the net separately or collapse them into one total?**
     Those two answers decide how much of Class B and Class C we get for free.
     Record the raw field names it gives back, verbatim.

---

## 2.2 Record what actually came back

For **each** of the two files, write down:

```
FILE: bill_02.jpg  (mild)
  line items detected      : ____ of 7
  quantities correct       : ____
  amounts correct          : ____
  a grand total was found  : yes / no
  lowest per-field confidence seen : ____

FILE: bill_06.pdf  (retail layout, clean PDF)
  line items detected      : ____ of 6
  MRP column returned      : yes / no   (field name: ____________)
  PACK column returned     : yes / no   (field name: ____________)
  totals returned          : subtotal ____  discount ____  net ____
                             (or a single total: ____)

FILE: bill_05.jpg  (heavy)
  line items detected      : ____ of 3
  quantities correct       : ____
  amounts correct          : ____
  a grand total was found  : yes / no
  lowest per-field confidence seen : ____
```

Ground truth to check against — both bills, in full:

**bill_02** (7 lines, printed total Rs 409.00)

| # | Item | Qty | Rate | Amount |
|---|---|---|---|---|
| 1 | Paracetamol 650mg Tablet | 15 | 2.00 | 30.00 |
| 2 | Amoxicillin 500mg Capsule | 10 | 7.40 | 74.00 |
| 3 | Paracetamol 500mg Tablet | 20 | 1.10 | 22.00 |
| 4 | Acimol 500mg Tablet | 2 | 11.50 | 23.00 |
| 5 | Pantoprazole 40mg Tablet | 10 | 8.50 | 85.00 |
| 6 | Cotton Roll 100gm | 1 | 85.00 | 85.00 |
| 7 | Micropore Tape | 2 | 45.00 | 90.00 |

**bill_05** (3 lines, printed total Rs 190.80)

| # | Item | Qty | Rate | Amount |
|---|---|---|---|---|
| 1 | Paracetamol 500mg Tablet | 10 | 0.88 | 8.80 |
| 2 | Surgical Gloves Pair | 5 | 22.00 | 110.00 |
| 3 | Amox1cill1n 5OOmg Cap | 10 | 7.20 | 72.00 |

> These two tables are GENERATED from `eval/fixtures/`. If you edit
> them by hand they will drift from the bills you are actually
> uploading, and you will record the wrong reading accuracy. The
> previous version of this table claimed bill_02 had 6 lines totalling
> Rs 1,032.50; it has 7 lines totalling Rs 409.00, and the line it
> omitted is the only item in the amber band.

---|---|---|---|---|
| 1 | Paracetamol 650mg Tablet | 15 | 2.00 | 30.00 |
| 2 | Amoxicillin 500mg Capsule | 10 | 7.40 | 74.00 |
| 3 | Paracetamol 500mg Tablet | 20 | 1.10 | 22.00 |
| 4 | Pantoprazole 40mg Tablet | 10 | 8.50 | 85.00 |
| 5 | Cotton Roll 100gm | 1 | 85.00 | 85.00 |
| 6 | Micropore Tape | 2 | 45.00 | 90.00 |

**bill_05** (3 lines)
| # | Item | Qty | Rate | Amount |
|---|---|---|---|---|
| 1 | Paracetamol 500mg Tablet | 10 | 0.88 | 8.80 |
| 2 | Surgical Gloves Pair | 5 | 22.00 | 110.00 |
| 3 | Amox1cill1n 5OOmg Cap | 10 | 7.20 | 72.00 |

---

## 2.3 What the answer changes

- **Mild scan reads well, heavy scan fails.** The expected, best case. The
  video shows both: a real photo working, and the system saying plainly that
  it could not read the bad one. Nothing changes in the plan.
- **Both read well.** Even better. We may need a worse scan to demonstrate the
  re-read pass at all.
- **Mild scan reads badly too.** This is the one that changes things, and I
  need to know today. It would mean the crop-and-re-read pass is load-bearing
  rather than a nicety, and possibly that the Bedrock vision reader should be
  primary with Textract as the second opinion rather than the other way round.

**Whatever the numbers are, they are the numbers.** These replace the fixture
figures in the video. Do not round them up, and if only one scan was tested
say so — a missing claim is fine, an unmeasured one is not. See NOTES.md,
"Which numbers are ours to claim".

---

# Section 3 — Deploy the backend

**Do Sections 0-2 first.** This section assumes the budget alarms exist and
that you know whether Bedrock is available in us-east-1.

**Cost: pennies.** Lambda, API Gateway and DynamoDB are all within free tier
at demo volume. S3 holds a few MB for one day.

**Time: 20 minutes, most of it waiting for CloudFormation.**

---

## 3.1 Install the tools (once)

```bash
winget install --id Amazon.AWSCLI --exact
```

```bash
winget install --id Amazon.SAM-CLI --exact
```

Close and reopen the terminal, then check both:

```bash
aws --version && sam --version
```

---

## 3.2 Sign in

**Two ways, depending on how you sign in to the console.** Your console shows
an IAM user (`..._IAM` next to the account name), so it is almost certainly
path B.

> **Whichever you use: the credentials stay on your machine, in
> `~/.aws/credentials`. Never paste an access key, secret key or session token
> into a chat, a commit, a screenshot or an issue.** If one is ever exposed,
> deactivate it in the IAM console immediately — exposure is not recoverable
> by deleting the message.

### Path A — IAM Identity Center (SSO)

If your organisation set up Identity Center, or you sign in via a start URL
like `https://d-xxxx.awsapps.com/start`:

```bash
aws configure sso
```

Short-lived credentials, refreshed by `aws sso login`. Preferred when
available, because nothing long-lived lands on disk.

### Path B — IAM user access key

If you sign in with a username and password directly to the console:

1. Console → your name, top right → **Security credentials**.
2. **Access keys** → **Create access key** → choose **Command Line Interface
   (CLI)** → acknowledge → **Create**.
3. **Download the .csv or copy both values now.** The secret is shown once and
   never again.
4. In your terminal:

```bash
aws configure
```

   Answer: Access Key ID, Secret Access Key, default region `us-east-1`,
   default output `json`.

> **This creates a long-lived credential**, which is the security cost of this
> path. Two things reduce it, and both are worth doing:
> - **Delete the access key when the hackathon is over.** IAM → your user →
>   Security credentials → Actions → Delete. It takes ten seconds.
> - **Do not create a second key "just in case".** Unused keys are the ones
>   that leak, because nobody notices they still work.

### Verify, either path

```bash
aws sts get-caller-identity
```

```bash
aws configure get region
```

**Verify:** the account number matches the one in your console, and the region
reads `us-east-1`.

The region **must** match where you enabled the model in Section 1. Getting
this wrong deploys into a region with no model access, and it fails later as
an `AccessDeniedException` from Bedrock that looks like an IAM problem — you
will go hunting through policies for a bug that is not there.

---

## 3.3 Stage the reference data

**Do not skip this.** The SAM template's `CodeUri` is `backend/`, so anything
outside that folder is not deployed. Without this step the Lambda starts fine
and then fails on the first bill, in production, which is the worst place to
find out.

```bash
python scripts/stage_lambda.py
```

**Verify:** it prints `staged reference_prices.csv  3.26 MB`.

It deliberately does **not** stage `brand_index.csv` (36 MB). The engine
handles its absence by falling back to generic-name resolution — branded
names like "Augmentin" will go gray until Phase 4 loads the index into
DynamoDB. That is a coverage reduction, not a failure.

---

## 3.4 Build and deploy

> **READ THIS BEFORE RUNNING `sam build`.**
>
> You are building on **Windows** for an **x86_64 Linux** Lambda. A plain
> `sam build` installs wheels for the machine it runs on, so it would bundle
> **Windows** wheels into a Linux function. That deploys fine and then fails
> at import time with an ELF error on the first request — the worst way to
> find out, because everything looks successful until it doesn't.
>
> Only two packages actually matter: **pydantic-core** and **rapidfuzz**.
> Everything else in `backend/requirements.txt` is pure Python and portable.
>
> Pick path A if Docker Desktop is installed and running. Otherwise path B,
> which is verified to work and needs no Docker at all.

### Check first

```bash
docker info
```

Prints a block of server info → **path A**. Errors or hangs → **path B**.

> **Checked 2026-09-19 on this machine: Docker is installed and running
> (server 29.5.2), so PATH A applies.** Path B is kept below because it is
> verified and costs nothing to leave in — if Docker Desktop is not running
> when you get here, start it rather than switching paths.

---

### Path A — Docker Desktop is running

```bash
sam build --use-container --template infra/template.yaml
```

`--use-container` builds inside an ARM Amazon Linux image that matches the
Lambda runtime, so the native wheels are correct by construction. It is
slower and pulls a ~1 GB image the first time.

---

### Path B — no Docker

Download Linux wheels explicitly, then let SAM package the result. **Verified
on 2026-09-19**: this resolves completely, with no Windows or macOS wheels in
the output.

```bash
rm -rf .aws-sam/deps && mkdir -p .aws-sam/deps
```

```bash
./venv/Scripts/python.exe -m pip download -r backend/requirements.txt --dest .aws-sam/deps --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 --implementation cp --python-version 3.12 --only-binary=:all:
```

**The two `--platform` flags are both required and this is not belt-and-braces.**
`pydantic-core` publishes `manylinux2014_x86_64`; `rapidfuzz` publishes
`manylinux_2_28_x86_64`. Either flag alone fails on the other package, with a
misleading "Could not find a version that satisfies the requirement" that
looks like a bad pin rather than a tag mismatch:

```
ERROR: Could not find a version that satisfies the requirement rapidfuzz==3.14.6
       (from versions: 2.15.2, ... 3.13.0)
```

That message is lying about the versions available. 3.14.6 exists; it just
does not ship a `manylinux2014` wheel.

**Verify before going further** — 21 wheels, and exactly two of them native:

```bash
ls .aws-sam/deps | grep -v "py3-none-any"
```

```
pydantic_core-2.46.5-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
rapidfuzz-3.14.6-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
```

If you see `win_amd64` or `macosx` anywhere in that listing, **stop** — the
platform flags did not take effect and the bundle is wrong.

Then install them into the build directory and build without touching the
network again:

```bash
./venv/Scripts/python.exe -m pip install -r backend/requirements.txt --target .aws-sam/build/ApiFunction --no-index --find-links .aws-sam/deps --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 --implementation cp --python-version 3.12 --only-binary=:all: --upgrade
```

```bash
cp -r backend/app backend/reference_data .aws-sam/build/ApiFunction/
```

```bash
sam deploy --guided --stack-name billsahi --template-file .aws-sam/build/template.yaml
```

> If path B gives you trouble, the honest fallback is to install Docker
> Desktop and use path A. Do not "fix" it by switching `Architectures` — the same tag mismatch exists there (verified), so it costs a
> rebuild and changes nothing.

---

### The deploy prompts (both paths)

```bash
sam deploy --guided --stack-name billsahi
```

Answer the prompts:

| Prompt | Answer |
|---|---|
| Stack Name | `billsahi` |
| AWS Region | `us-east-1` (must match 3.2) |
| Parameter BedrockInferenceProfileId | paste from Section 1.2, or leave blank |
| Parameter FrontendOrigin | leave blank for now — Section 4 fills it in |
| Parameter ReservedConcurrency | `5` |
| Confirm changes before deploy | `y` |
| Allow SAM CLI IAM role creation | `y` |
| Disable rollback | `N` |
| Save arguments to samconfig.toml | `y` |

`FrontendOrigin` blank is expected and safe: the template omits the whole
`CorsConfiguration` until Section 4 supplies a real origin, rather than
deploying an empty-string origin. The app enforces CORS itself either way.

**Verify:** the Outputs table prints `ApiUrl`. Copy it.

```
ApiUrl = ____________________________________________
```

---

### Troubleshooting the first deploy

Six things went wrong on the first real deploy (2026-09-19). **None was a bug
in this project** -- all six were the environment. Recorded because every one
of them looks like something else.

| Symptom | Actual cause |
|---|---|
| `sam build` hangs on `Fetching ... image......` | NOT a download. The image was already local; SAM was contacting ECR to check freshness. `docker images` first, then `--skip-pull-image`. |
| Build container exits silently, no error, no output | **Disk full.** C: had 0.02 GB free. Also caused Docker's daemon to throw 500s intermittently, which looked like Docker being unstable. **Check free space before anything else** -- it presents as five unrelated faults. |
| `aws` "not found" after winget says it installed | A process gets the PATH that existed when it STARTED. A terminal spawned by a long-running app inherits that app's stale PATH, so reopening the terminal does NOT help. Fixed permanently by the self-healing shell profiles. |
| `[WinError 5] Access is denied` under `.aws-sam/build` | **OneDrive.** It holds file handles open while syncing; SAM wipes the build dir every run. Fixed by building outside OneDrive -- `build_dir` in `samconfig.toml`. |
| `ReservedConcurrentExecutions ... below its minimum value of [10]` | A new account's TOTAL Lambda concurrency is often 10, and AWS requires 10 to stay unreserved. Reserving anything is refused. `ReservedConcurrency=0` omits the property. |
| `Stack ... is in ROLLBACK_COMPLETE state and can not be updated` | A stack that fails on FIRST create can only be deleted, never updated. It is an empty shell -- the rollback already destroyed every resource. |

**Deleting a `ROLLBACK_COMPLETE` stack is safe** because it holds nothing:

```bash
aws cloudformation delete-stack --stack-name billsahi --region us-east-1
```

```bash
aws cloudformation wait stack-delete-complete --stack-name billsahi --region us-east-1
```

> **Keep the instinct that `delete-stack` is dangerous.** On a stack that has
> ever SUCCEEDED it would take the real S3 bucket and DynamoDB table with it.
> `DeletionPolicy: Delete` on the upload bucket is deliberate for a hackathon
> and would be wrong for anything holding real data.

---

## 3.5 Smoke-test the API before touching the frontend

```bash
curl https://YOUR-API-URL/health
```

**Expect:** `{"status":"ok","provider":"aws", ...}`.

If `provider` says `local`, the environment variable did not apply — check
the template deployed cleanly.

Now the real test, with a bill:

```bash
curl -X POST -F "file=@eval/demo_bills/bill_02.jpg" https://YOUR-API-URL/bills
```

**Expect:** JSON with a `bill_id` and `items_read` greater than 0.

**This is the first time Textract has ever run in this project.** Whatever
`items_read` says is the real number. Record it:

```
items_read on bill_02.jpg (mild scan):  ____ of 7
items_read on bill_05.jpg (heavy scan): ____ of 3
```

Then fetch the report:

```bash
curl https://YOUR-API-URL/bills/THE-BILL-ID
```

**If something fails,** get the logs:

```bash
sam logs --stack-name billsahi --tail
```

---

## 3.6 Report back before going further

Paste me:
- the `ApiUrl`
- the `/health` response
- `items_read` for both scans
- any error from `sam logs`

**Do not deploy the frontend until the API smoke test passes.** A broken API
behind a working UI is harder to debug than no UI at all.

---

# Section 4 — Deploy the frontend

Written once Section 3 reports a working API, because the frontend needs the
`ApiUrl` and the API needs the Amplify origin for CORS. Chicken and egg, so
it is done in that order: deploy API, deploy UI, then update the API's
`FrontendOrigin` parameter and redeploy.

---

# Section 9 — Cost control, and what to do before sleeping

Written 2026-09-19 when the deadline was one day out and the stack had to
survive the night. **Read the first paragraph before doing anything: the
instinct to tear it all down is probably wrong here.**

## 9.0 What this stack actually costs while nobody uses it

**Effectively nothing.** Every resource is either pay-per-request or already
capped, and this is by construction rather than luck — check `template.yaml`
and you will find:

| Resource | Idle cost | Why |
|---|---|---|
| Lambda | **$0** | Billed per invocation-ms. No invocations, no bill. |
| HTTP API | **$0** | Billed per request. |
| DynamoDB | **$0** | `BillingMode: PAY_PER_REQUEST` — no provisioned capacity to pay for. Records carry a 1-day TTL. |
| S3 uploads | **~$0** | `ExpirationInDays: 1`. A few MB for under a day is a fraction of a cent. |
| CloudWatch Logs | **~$0** | `RetentionInDays: 7`. Kilobytes. |
| Bedrock / Textract | **$0** | Billed per call only. Nothing calls them while you sleep. |

There is no hourly resource in this stack. No NAT gateway, no VPC endpoint,
no provisioned concurrency, no RDS, no EC2 — those are the things that bill
you for existing, and none of them is here.

**So: you can close the laptop. Idle, this stack does not move the bill.**

## 9.1 The real exposure, which is not idling

**The API is PUBLIC and UNAUTHENTICATED, and it has no throttle.**

    https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com

Anyone who finds that URL can POST a bill to it, and every upload spends real
money: Textract AnalyzeExpense is charged per page, plus Lambda time and a
Bedrock call. That is the ONLY path from here to a $5 surprise, and it has
nothing to do with whether you are asleep.

The risk is low — the URL is unlisted, and API Gateway hostnames are not
enumerable in practice — but it is the one that is real, so it gets the
mitigation rather than the idle cost that does not exist.

## 9.2 Do this — a hard $5 budget alert (3 minutes, console, free)

This is the ONE thing worth doing before bed. It does not stop spend, it tells
you the moment it starts, which is what you actually need overnight.

1. Sign in, then open **Billing and Cost Management → Budgets**:
   https://us-east-1.console.aws.amazon.com/costmanagement/home#/budgets
2. **Create budget** → **Customize (advanced)** → Budget type: **Cost budget**.
3. Period **Monthly**, Budget renewal **Recurring**.
4. Budgeted amount: **5.00** USD. Name it `billsahi-hard-cap`.
5. **Add an alert threshold** — and add all three, because the first one is
   the only one that arrives early enough to act on:
   - **50%** of budgeted amount (**$2.50**) — actual
   - **80%** (**$4.00**) — actual
   - **100%** (**$5.00**) — **forecasted**, not actual
6. Email: your own address. Confirm the subscription email if prompted.

Budgets themselves are free (the first two are). Alerts can lag actual spend
by several hours — that is an AWS property, not a setting — which is exactly
why the 50% threshold matters more than the 100% one.

## 9.3 Optional — throttle the API so abuse cannot run away

Only if 9.2 does not let you sleep. This caps the blast radius rather than
detecting it after the fact.

Console: **API Gateway → APIs → the `billsahi` HTTP API → Stages → `$default`
→ Default route throttling → Edit**

    Rate  (requests/second) : 2
    Burst (requests)        : 5

Generous for a demo and a judge clicking through; useless to anyone trying to
run up a bill. **Set it back to something higher before filming** if you plan
to click quickly through several bills.

## 9.4 If you want certainty instead — delete the stack

**RECOMMENDED AGAINST TONIGHT, and here is the honest reason.** This costs
nothing to keep and a great deal to rebuild: the first deploy hit SIX separate
environment failures (see "Troubleshooting the first deploy"), and a redeploy
under deadline pressure with no sleep is where this project would actually get
hurt. Deleting also CHANGES THE API URL, so anything already pointing at it
breaks.

Keep it. But if you want the certainty anyway, the command is:

```bash
sam delete --stack-name billsahi --region us-east-1
```

It asks twice before doing anything. It empties and removes the upload bucket,
the table, the function, the API and the log group. Everything needed to bring
it back is in git — `template.yaml` plus Section 3 — but budget an hour, not
ten minutes.

**What `sam delete` does NOT remove:** the `aws-sam-cli-managed-default-*`
artifacts bucket SAM created for build uploads. It holds a few tens of MB of
deployment zips and costs well under a cent a month. Leave it; it is reused by
the next deploy.

## 9.5 What does NOT need shutting down

- **The local dev servers** (`:8000` FastAPI, `:5173` Vite). They run on your
  machine and cost nothing. Close the terminals if you like.
- **Bedrock model access.** Granted access is not a subscription and is not
  billed. It bills per call, and right now it is not even succeeding
  (`INVALID_PAYMENT_INSTRUMENT`).
- **The Docker containers** left over from the SAM build. Local, free — though
  reclaiming the disk is worth it for other reasons.


---

# Section 10 — Amplify, FrontendOrigin, and the redeploy

One pass. The CORS parameter rides along with the code changes, so this is a
single `sam deploy`, not two.

**Amplify does NOT need a GitHub repo.** Amplify Hosting has a git mode and a
manual mode; manual takes a zip of the built folder and is the fast path when
there is no remote. Use git mode later if you want deploy-on-push.

## 10.0 Why a redeploy at all — measured, not assumed

`FrontendOrigin` alone would NOT need a rebuild: it is a CloudFormation
parameter, and a parameter change is `sam deploy` on its own. The rebuild is
for the Python, which is stale. Probed 2026-09-20 against the live stack:

| Probe | Live result | Why it matters |
|---|---|---|
| `POST /feedback` | **404** | the new landing page has a feedback form that calls it |
| `GET /health` → `reader` | *"...verifying both"* | false; Bedrock is down and no cross-check runs |
| directional R1 (Class F) | not deployed | landed after the last deploy |
| Textract confidence scoping | not deployed | the fix that stops a discarded field deciding a verdict |

NOT stale, and worth knowing before you plan around it: **the reduced brand
index IS already deployed.** The live stack returns PANTOCID DSR as
`no_public_ceiling`, which only resolves if the index is in the bundle.

## 10.1 There is an ordering trap

Amplify assigns the `*.amplifyapp.com` domain, but the API refuses that origin
until `FrontendOrigin` is set — and the domain does not exist until Amplify
has deployed. So Amplify goes FIRST, with a frontend that cannot reach the API
yet, and the deploy in 10.3 is what brings it to life.

Do not try to guess the domain in advance.

## 10.2 Build the frontend and deploy it to Amplify

```bash
cd frontend && npm run build
```

That reads `.env.production`, so the bundle points at the deployed API. Then:

1. Open **AWS Amplify**: https://us-east-1.console.aws.amazon.com/amplify/
2. **Create new app** → **Deploy without Git provider**
3. App name `billwise`, environment name `prod`
4. Upload **a zip of the CONTENTS of `frontend/dist`**, so `index.html` sits
   at the ROOT of the archive.
   **THIS STEP USED TO SAY "drag the dist FOLDER" AND THAT IS WRONG** -- it
   was written before the first real deploy and corrected on 2026-09-20 after
   it failed. Uploading the folder (or a zip OF the folder) puts everything
   under `/dist/` and every asset path 404s, so the site loads a blank page.
   Section 11 has the command that builds the archive correctly.
5. **Save and deploy**, then copy the domain it prints. It looks like
   `https://prod.d1a2b3c4d5e6f7.amplifyapp.com`

**Single-page routing:** this app reads its own URL for `?fixture=`, so a
deep link must still serve `index.html`. In **App settings → Rewrites and
redirects**, add:

    Source:  /<*>
    Target:  /index.html
    Type:    404 (Rewrite)

Without it a refresh on any path returns Amplify's 404 page.

## 10.3 Stage, build and deploy the backend WITH the origin

**Use the venv interpreter, not a bare `python`.** The system Python has no
pydantic and this dies with ModuleNotFoundError halfway through, after it has
already copied the reference data -- which looks like partial success.

```bash
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe scripts/stage_lambda.py
```

**STAGING MUST COME BEFORE THE BUILD.** It writes into `backend/`, and the
build copies `backend/`. Run it afterwards and the build ships whatever was
staged last time.

Then, from the repo root:

```bash
sam build --use-container --template infra/template.yaml --build-dir C:/Users/you/billsahi-build
```

**`--build-dir` IS NOT OPTIONAL, AND OMITTING IT DEPLOYS THE WRONG CODE
SILENTLY.** `samconfig.toml` sets `build_dir`, but on 2026-09-20 a plain
`sam build` ignored it and wrote to `.aws-samuild` instead, while
`sam deploy` went on reading `template_file` from samconfig -- the OTHER
directory, holding a build from the day before.

The deploy SUCCEEDED. CloudFormation reported UPDATE_COMPLETE. The parameter
change went through, so CORS was fixed and it all looked right. The code was
the previous build.

**The tell is one line in the deploy output:**

    File with same data already exists at billsahi/<hash>, skipping upload

If the code changed, that hash must change. Seeing "skipping upload" after
editing Python means the artifact is identical to a previous one -- which
means it is not yours. Do not read it as a helpful optimisation.

Verify with the probes in 10.4 rather than the CloudFormation status. A green
stack says the DEPLOY worked, not that it deployed what you built.

```bash
sam deploy --stack-name billsahi --region us-east-1 --capabilities CAPABILITY_IAM --parameter-overrides BedrockInferenceProfileId="us.anthropic.claude-sonnet-4-6" FrontendOrigin="https://PASTE-YOUR-AMPLIFY-DOMAIN" ReservedConcurrency="0"
```

**Replace `PASTE-YOUR-AMPLIFY-DOMAIN` with the real domain**, with `https://`
and no trailing slash. A trailing slash does not match a browser's `Origin`
header and the preflight will still fail.

**`samconfig.toml` caches `FrontendOrigin=""` from the first deploy.** Passing
`--parameter-overrides` on the command line beats it for this run, but a later
bare `sam deploy` will silently go back to the blank value and break CORS
again. Update the `parameter_overrides` line in `samconfig.toml` once the
domain is known.

The stack name stays `billsahi` even though the product is BillWise. Renaming
it does not rename a stack — it creates a second one on a new URL and orphans
this one.

## 10.4 Prove it, from the Amplify origin

```bash
curl -s -o /dev/null -D - -X OPTIONS "https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com/bills/sample" -H "Origin: https://PASTE-YOUR-AMPLIFY-DOMAIN" -H "Access-Control-Request-Method: POST" | grep -i access-control-allow-origin
```

It must echo your Amplify domain. No header means CORS is still refusing it —
check for a trailing slash, and that the deploy actually changed the parameter.

```bash
curl -s -X POST "https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com/feedback" -H "Content-Type: application/json" -d "{\"message\":\"deploy check\"}"
```

`{"ok":true}` means the new code is live. A 404 means the build did not ship.

```bash
curl -s https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com/health
```

`reader` must no longer say "verifying both". While Bedrock is down it should
describe a CONFIGURED second reader, not a performed one.

Then open the Amplify URL and run **Try a sample bill**. If the report renders,
the whole path is live: browser → Amplify → API Gateway → Lambda → the engine.

## 10.5 What will still be true afterwards

**THIS SECTION USED TO SAY BEDROCK WAS DOWN AND ONLY ONE READER RAN. That was
true while the Marketplace offer was expired and is NO LONGER TRUE.** Since
2026-09-20 the second reader is `us.amazon.nova-2-lite-v1:0` and both readers
run on every upload, measured on the deployed stack. Do not plan a demo around
the old limitation.

What IS still true: reading quality depends on the image. A clean PDF reads
well; a degraded phone photograph makes the two readers disagree, and a
disagreement is deliberately resolved as gray rather than a guess. Uploads are
capped at **4 MB**, not the 10 the UI once claimed.

---

# Section 11 — Redeploying ONLY the frontend (Amplify)

Use this when the frontend changed and the backend did not. It touches no
CloudFormation and costs nothing beyond Amplify's hosting, which is already
running. **The backend does NOT need redeploying for a frontend-only change.**

Written 2026-09-20 for the contributor's redesign. The build is already made and
verified; step 11.1 only needs re-running if you change frontend code again.

## 11.1 Build, and package it the way Amplify actually wants

```bash
cd frontend && npm run build
```

That reads `.env.production`, so the bundle points at the deployed API with
mocks off. Then, from the REPO ROOT, build the archive:

```bash
python -c "import zipfile,os; root='frontend/dist'; z=zipfile.ZipFile('billwise-frontend.zip','w',zipfile.ZIP_DEFLATED); [z.write(os.path.join(d,f), os.path.relpath(os.path.join(d,f),root).replace(os.sep,'/')) for d,_,fs in os.walk(root) for f in fs]; z.close(); print('\n'.join(zipfile.ZipFile('billwise-frontend.zip').namelist()))"
```

**`index.html` MUST appear at the top level of that listing**, with `assets/`
and `fonts/` beside it. If you see `dist/index.html`, the site will 404 on
every path.

**Do NOT build this archive with PowerShell's `Compress-Archive`.** On Windows
PowerShell 5.1 it writes entry names with BACKSLASH separators, which the zip
spec does not allow. Some unzippers then treat `assets\index-abc.js` as a
single file named that, sitting at the root — so `index.html` asks for
`/assets/index-abc.js`, gets a 404, and the page renders blank with no error
that points at the cause. The Python command above writes forward slashes.

## 11.2 Upload it

1. Open **AWS Amplify**: https://us-east-1.console.aws.amazon.com/amplify/
2. Choose the existing **billwise** app → the **prod** environment
3. **Deploy updates**
4. Upload `billwise-frontend.zip` from the repo root
5. Wait for the deployment to go green

**You do NOT delete the previous deployment first.** "Deploy updates" replaces
what is served. There is no need to recreate the app, and recreating it would
change the domain — which would break CORS, because the API allows exactly one
origin and that origin is pinned in `samconfig.toml`.

## 11.3 Verify, and do not trust a green tick

Open https://prod.YOUR-AMPLIFY-APP-ID.amplifyapp.com and check all four:

1. **The page renders with content**, not a blank cream background. A blank
   page with a 404 on `/assets/...` in the browser's network tab is the
   backslash-zip problem from 11.1.
2. **Hard-refresh** (Ctrl+Shift+R). Amplify serves the old bundle from cache
   otherwise, and you will "verify" the previous deploy.
3. **Run "Try a sample bill"** and confirm a report renders. That proves the
   whole path: browser → Amplify → API Gateway → Lambda → engine.
4. **Confirm there is NO "GitHub" link** in the footer and no "View the
   source" button. Those are hidden while `REPO_URL` is empty. If they appear,
   an older bundle is being served.

If the sample works but a real upload fails with a bare "Network error", that
is the 4 MB ceiling, not a deploy problem. See `docs/LIMITS.md`.

---

## 11.4 Deploying from the CLI instead of the console

Same manual deploy, driven by `aws amplify` rather than drag-and-drop. Added
2026-09-20 when the owner asked for commands.

**The app id is in the domain.** `prod.YOUR-AMPLIFY-APP-ID.amplifyapp.com` is
`<branch>.<app-id>.amplifyapp.com`, so:

    APP_ID      YOUR-AMPLIFY-APP-ID
    BRANCH      prod
    REGION      us-east-1

**Three calls, and the middle one is a plain HTTP PUT, not an AWS call.**
`create-deployment` hands back a presigned S3 URL; you upload the zip to it
with `curl`; then `start-deployment` tells Amplify to publish what you
uploaded. Nothing is live until the third call.

```bash
aws amplify create-deployment --app-id YOUR-AMPLIFY-APP-ID --branch-name prod --region us-east-1
```

That prints `jobId` and `zipUploadUrl`. Both are needed below, and the URL is
short-lived — do the upload straight away.

```bash
curl -T billwise-frontend.zip "PASTE_THE_zipUploadUrl_HERE"
```

`curl -T` sends a PUT, which is what the presigned URL is signed for. A silent
success is normal; a 403 usually means the URL expired, so re-run
`create-deployment`.

```bash
aws amplify start-deployment --app-id YOUR-AMPLIFY-APP-ID --branch-name prod --job-id PASTE_THE_jobId_HERE --region us-east-1
```

Then poll until `status` is `SUCCEED`:

```bash
aws amplify get-job --app-id YOUR-AMPLIFY-APP-ID --branch-name prod --job-id PASTE_THE_jobId_HERE --region us-east-1 --query "job.summary.status"
```

**If a flag name differs on your CLI version**, ask it rather than guessing:
`aws amplify create-deployment help`. This file does not guess at AWS API
shapes, and these four were written from the documented Amplify manual-deploy
flow rather than from a run on this machine — the console path in 11.2 is the
one that has actually been exercised here.

**Verify with the bundle name, not the job status.** A green job only means
the upload published; it does not prove the zip held the build you meant:

```bash
curl -s https://prod.YOUR-AMPLIFY-APP-ID.amplifyapp.com | grep -oE "index-[A-Za-z0-9_-]+\.(js|css)"
```

Compare that against `grep -oE "index-[A-Za-z0-9_-]+\.(js|css)" frontend/dist/index.html`.
If they differ, the old bundle is still being served.
