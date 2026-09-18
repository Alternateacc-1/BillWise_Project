# Open questions

Things we do not know yet and must not guess. Each one names who resolves it
and when. Nothing here blocks Phase 0-3, which run entirely offline.

---

## Q1. Can ap-south-1 reach a vision-capable Claude model? (Phase 4)

**Status: RESOLVED, 2026-09-19. The answer is YES — after one wrong turn.**

**What happened.** The Bedrock console in ap-south-1 appeared to offer no
Claude model, so the whole stack was migrated to `us-east-1`, per the fallback
agreed in advance. Hours later the real cause surfaced: the **Anthropic
use-case-details form**, a one-time submission that gates every Anthropic
model **account-wide, in every Region**. With it submitted, Mumbai works. The
stack moved back.

**The lesson, which is worth more than the outcome:**

> "The model is not offered in this Region" and "this account may not call the
> model anywhere yet" are **indistinguishable** from inside the console.

Check the account-level gate before drawing any conclusion about a Region.
The round trip cost a few hours and two commits; concluding the same thing on
Sunday would have cost the deployment.

**Final configuration:**

  - Whole stack in `ap-south-1`. Textract, including AnalyzeExpense, is
    available there (verified against the AWS endpoints table), so nothing
    forces a split. **We never split Regions.**
  - Claude via the **APAC geo** profile
    `apac.anthropic.claude-sonnet-4-20250514-v1:0`.
  - From `ap-south-1` the model card shows **In-Region: no, Geo: yes,
    Global: no** — geo is the only option, and also the right one.
  - Image input supported; Converse supported.

**Why geo beats global here, beyond it being the only choice.** Destinations
from ap-south-1 are eight Asia-Pacific Regions: Tokyo, Seoul, Osaka, Mumbai,
Hyderabad, Singapore, Sydney, Melbourne. The global profile routes to every
commercial Region worldwide, and AWS notes that prompts and outputs may be
stored in opt-in Regions for abuse detection. What we send Bedrock is a
photograph of a real medical bill — a patient's name, registration number, and
a drug list that implies a diagnosis. Keeping that inside Asia-Pacific is not
a nicety.

**Still open:** Sonnet 4 is a **legacy** model with EOL **2026-10-14**, under a
month after submission. Fine for this project; check whether Sonnet 4.5 or 4.6
offers an APAC profile from Mumbai before anyone builds on this.

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

Because the profile is **geo-tied**, the destination list is fixed and
documented, so the policy now pins the profile ID **and** all eight
Asia-Pacific Regions explicitly. **This is the data-residency control** — no
statement permits invoking the model outside APAC.

Had we stayed on the global profile this would not have been possible: its
destinations are all commercial Regions and they change over time, so the
foundation-model ARNs would have had to stay wildcarded.

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
