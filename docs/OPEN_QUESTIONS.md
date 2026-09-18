# Open questions

Things we do not know yet and must not guess. Each one names who resolves it
and when. Nothing here blocks Phase 0-3, which run entirely offline.

---

## Q1. Which Region, and which inference profile? (Phase 4)

**Status: RESOLVED, 2026-09-19.** Final: **`us-east-1`**, Claude via the **US
geo** profile `us.anthropic.claude-sonnet-4-6`.

**The Region went us-east-1 -> ap-south-1 -> us-east-1 across two days.** Both
reversals taught something worth keeping.

### Lesson 1: an account-level gate looks exactly like a Region limitation

The first move was triggered by "Bedrock offers no Claude in ap-south-1". That
was **wrong**. The real blocker was the Anthropic **use-case-details form** — a
one-time submission that gates every Anthropic model **account-wide, in every
Region**.

> "The model is not offered in this Region" and "this account may not call the
> model anywhere yet" are **indistinguishable** from inside the console.

Check the account-level gate before drawing any conclusion about a Region.

### Lesson 2: the privacy-preferring Region is not the intuitive one

Having fixed the gate, Mumbai worked, and the stack moved back — the tool is
for Indian patients, so an Indian Region seemed obviously right. Then the
model card settled it the other way:

| | from `ap-south-1` | from `us-east-1` |
|---|---|---|
| Sonnet 4.6 In-Region | no | no |
| Sonnet 4.6 **Geo** | **no** | **yes** (`us.`) |
| Sonnet 4.6 Global | yes | yes |
| Destinations available | **33 Regions** (global only) | **3 Regions** (us-east-1, us-east-2, us-west-2) |
| Textract AnalyzeExpense | 1 TPS | 5 TPS |

**Choosing India would have meant choosing worldwide routing for a medical
document.** N. Virginia keeps a patient's bill in three known Regions instead
of thirty-three. The privacy argument and the "sit near your users" argument
point in opposite directions here, and privacy won.

**What it costs:** latency to Indian users is worse than an Indian Region
would give. That is a consequence of model availability, not a preference, and
`ARCHITECTURE.md` says so plainly.

**Still worth revisiting** if Anthropic later offers a geo profile from
`ap-south-1` — that would make Mumbai strictly better on both axes.

---

## Q1a. Is `bedrock:InvokeModel` correctly scoped? (Phase 4)

**Status: RESOLVED, 2026-09-19.** Previously `Resource: "*"`.

The intuitive tightening — grant the inference profile ARN and nothing else —
**is wrong and fails at the first call.** From the AWS documentation,
"Prerequisites for inference profiles":

> "When you specify an inference profile in the Resource field in the first
> statement, you must also specify the foundation model in each Region
> associated with it."

The profile is a routing target; the foundation model is what is actually
invoked. Both resource types are required in the same statement.

Because the profile is **geo-tied**, its destination list is fixed and
documented, so the policy pins the profile ID **and** the three
Region-scoped foundation-model ARNs. **This is the data-residency control** —
no statement permits invoking the model outside those Regions.

On the global profile this would have been impossible: 33 destinations that
change over time, so the foundation-model ARNs would have to stay wildcarded.
**The choice of profile is therefore a security decision, not just a routing
one** — it determines whether least privilege is achievable at all.

Action is `bedrock:InvokeModel*`, not `bedrock:InvokeModel`: the reader uses
the **Converse** API, which authorises against `bedrock:InvokeModel`.

---

## Q2. Which GST slab applies to a given medicine? (Phase 1, non-blocking)

**Status:** resolved by assumption; revisit before any real-world use.

Indian medicines sit at either 5% or 12% GST depending on the formulation,
and a bill line usually does not say which. We assume **12%** because a higher
assumed tax yields a higher permitted price and therefore fewer red flags --
the error lands on the side of silence. Rationale in `backend/app/config.py`.

This is fine for a demo. It is NOT fine for a product that tells a patient
their hospital overcharged them. A real version needs the per-formulation
slab, which is not in any file we currently hold.

---

## Q3. Pack size on the bill line (Phase 1, non-blocking)

Bills write "Augmentin 625, Qty 1, Rs 223". One strip or one tablet? The
audit computes BOTH interpretations and only raises red when both exceed the
threshold; if only one does, it downgrades to amber and says the pack size is
unclear. Tracked here because it is the largest remaining false-positive
source after the threshold work.

---

## Q4. NPPA revision cadence (Phase 5, non-blocking)

Our lists were retrieved 2026-09-18 and carry SO numbers dated 25-Mar-2026.
NPPA revises ceilings on individual SOs through the year and applies an annual
WPI revision. We show the retrieval date next to every verdict and have no
refresh mechanism. Out of scope for the hackathon; name it in the demo video
as known future work rather than letting a judge find it.
