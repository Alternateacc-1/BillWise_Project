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
> your stack runs. Ours runs in ap-south-1. If you go looking for a billing
> metric in the CloudWatch console, switch the region selector to N. Virginia
> or you will find nothing and assume it is broken.

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

**This is the long pole and it is not under our control.** Enabling a model in
Bedrock is a console request that can be granted in minutes or can sit. Nothing
else in Phase 4 is blocked by it, so start it and walk away while the rest gets
written.

**Cost: $0.** Enabling access costs nothing; you pay per token when you call it.

**Time: 5 minutes of clicking, then an unknown wait.**

---

## 1.1 Enable a vision-capable Claude model in ap-south-1

1. Sign in. Set the region selector, top right, to **Asia Pacific (Mumbai)
   ap-south-1**. Get this wrong and you will enable a model in the wrong
   region and wonder why the code cannot see it.
2. Search for **Bedrock** → open it.
3. Left sidebar, near the bottom → **Model access**.
4. **Modify model access** (or **Enable specific models**).
5. Tick a **vision-capable Claude** model. Vision is required — the reader
   sends an image of a bill. A text-only model cannot do this job.
6. Submit. Some models are granted instantly; some show **In progress**.

**Verify:** the model's status reads **Access granted**. Screenshot it.

> **If no vision-capable Claude is offered in ap-south-1 at all**, stop and
> tell me. That is the trigger for moving the WHOLE stack to us-east-1, which
> is a decision already made (OPEN_QUESTIONS.md Q1) — we never split regions.

---

## 1.2 Copy the cross-region inference profile ID

We call Claude through a **global cross-region inference profile**, not a bare
model id — it is what lets ap-south-1 serve a request from wherever capacity
exists.

1. Bedrock → left sidebar → **Inference and assessment** → **Cross-region
   inference**.
2. Find the profile for the model you enabled.
3. **Copy the Inference profile ID verbatim.** Select it and copy — do not
   retype it, and do not reconstruct it from a docs page. It is long and
   getting one character wrong produces an unhelpful error.

**Paste it here, and into `.env`:**

```
BEDROCK_INFERENCE_PROFILE_ID=________________________________________
```

**Verify:** `.env` contains the line, and `.env` is NOT in git (it is
gitignored; `git status` should not mention it).

---

## 1.3 Report back

Paste me:

- the model you enabled and its status
- the inference profile ID
- the region you did it in

**If 1.1 or 1.2 could not be completed, say so immediately** — that changes
the region for the whole stack and I would rather rewrite the template now
than after it is deployed.

---

# Section 2 — Run Textract on the two degraded scans  (START IN PARALLEL)

**Why this is its own step, before any deployment:** every reading-quality
number we have comes from hand-written fixtures, not OCR. We do not know how
real Textract behaves on a real scan, and that is the single biggest unknown
left in the project. It is also the thing the demo video depends on. Find out
now, not after the stack is up.

**Cost: about $0.04.** Four AnalyzeExpense pages at roughly $0.01 each. The
first 100 pages/month are free for the first 3 months if the account is new.

**Time: 10 minutes.**

---

## 2.1 Upload the two scans in the console

No code, no SDK, no deployment. The console does this by hand.

1. Region selector → **ap-south-1** (same region as Section 1).
2. Search **Textract** → open it.
3. Left sidebar → **Analyze Document** → choose **Expense analysis** (this is
   AnalyzeExpense, the API our reader uses — NOT plain text detection).
4. Upload, one at a time:
   - `eval/demo_bills/bill_02.jpg` — the **mild** scan. A phone photo: slight
     rotation, a soft shadow, reduced contrast. **This one should mostly
     work.**
   - `eval/demo_bills/bill_05.jpg` — the **heavy** scan. Fax-grade. **This one
     may return almost nothing, and that is a legitimate result.**

---

## 2.2 Record what actually came back

For **each** of the two files, write down:

```
FILE: bill_02.jpg  (mild)
  line items detected      : ____ of 6
  quantities correct       : ____
  amounts correct          : ____
  a grand total was found  : yes / no
  lowest per-field confidence seen : ____

FILE: bill_05.jpg  (heavy)
  line items detected      : ____ of 3
  quantities correct       : ____
  amounts correct          : ____
  a grand total was found  : yes / no
  lowest per-field confidence seen : ____
```

Ground truth to check against — both bills, in full:

**bill_02** (6 lines, total ₹1,032.50)
| # | Item | Qty | Rate | Amount |
|---|---|---|---|---|
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

# Section 3 onwards — deployment

Being written now. Sections 1 and 2 do not depend on it and should already be
running.
