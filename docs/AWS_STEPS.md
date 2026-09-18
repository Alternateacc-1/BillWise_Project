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

# Section 1 onwards — deployment

Written in Phase 4. Nothing below Section 0 exists yet.
