# Open questions

Things we do not know yet and must not guess. Each one names who resolves it
and when. Nothing here blocks Phase 0-3, which run entirely offline.

---

## Q1. Can ap-south-1 reach a vision-capable Claude model? (Phase 4)

**Status: RESOLVED, 2026-09-19. The answer was NO.**

Bedrock offered no Claude model to this account in `ap-south-1` (Mumbai).

**Branch taken: the whole stack moved to `us-east-1`.** This was the fallback
already agreed before the checkpoint, precisely so the decision did not have
to be made under time pressure with a console open. We did not split regions,
and the reasons for that have not changed: a split stack means cross-region
data transfer charges, two sets of CloudWatch logs, two places for an IAM
policy to be wrong, and a latency path nobody will debug at 2am three days
before submission.

**What actually had to change.** Less than expected, because the region was
already a single variable in the code:

  - `backend/app/config.py` -- the default, and a real bug found on the way:
    it read only `AWS_REGION`, while `infra/template.yaml` sets
    `AWS_REGION_NAME`. That worked on Lambda ONLY because the Lambda runtime
    populates `AWS_REGION` itself, so the template's variable was dead config.
    It now reads `AWS_REGION_NAME` first and falls back to `AWS_REGION`.
    `AWS_REGION` cannot be set in the template -- it is a RESERVED Lambda
    environment variable and CloudFormation rejects it.
  - `infra/template.yaml` -- no hardcoded Region at all. It uses
    `!Ref AWS::Region`, so the Region follows `sam deploy`. Nothing to change
    except the IAM scoping below.
  - `.env.example`, `docs/AWS_STEPS.md`, `docs/ARCHITECTURE.md`, `NOTES.md`.

Every boto3 client is built in `aws_clients.py` from `config.AWS_REGION` and
nothing else, so there remains exactly one place to change the Region.

**Consequence worth noting for the write-up:** the demo runs in N. Virginia,
not Mumbai, so latency to an Indian user is worse than the architecture
intends. That is a deployment constraint of this account, not a design
choice, and it should be said plainly rather than quietly.

---

## Q1a. Is `bedrock:InvokeModel` correctly scoped? (Phase 4)

**Status: RESOLVED, 2026-09-19.** Previously `Resource: "*"`.

The intuitive tightening -- grant the inference profile ARN and nothing else --
**is wrong and fails closed at the first call.** From the AWS documentation,
"Prerequisites for inference profiles":

> "When you specify an inference profile in the Resource field in the first
> statement, you must also specify the foundation model in each Region
> associated with it."

The profile is a routing target; the foundation model is what is actually
invoked. Both resource types are required in the same statement.

The policy now pins the profile to the exact ID supplied at deploy time and
leaves the foundation models wildcarded, because the set of Regions a
cross-region profile fans out to is not knowable from inside the template, and
a global profile also routes through the empty-Region ARN form
(`arn:aws:bedrock:::foundation-model/...`).

**Still open, deliberately:** tightening the foundation-model ARNs to the
specific Regions the profile uses. Do that AFTER the first successful call,
when the set is known from CloudTrail, not before -- guessing it is how you
get an AccessDeniedException that looks like a model-access problem.

Also note the action is `bedrock:InvokeModel*`, not `bedrock:InvokeModel`:
the reader uses the **Converse** API, which authorises against
`bedrock:InvokeModel`.

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
