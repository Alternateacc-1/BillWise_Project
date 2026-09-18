# Open questions

Things we do not know yet and must not guess. Each one names who resolves it
and when. Nothing here blocks Phase 0-3, which run entirely offline.

---

## Q1. Can ap-south-1 reach a vision-capable Claude model? (Phase 4, BLOCKING)

**Status:** open. Confirm at the Phase 4 AWS checkpoint.

**The decision already made:** keep the ENTIRE stack in `ap-south-1` (Mumbai)
and reach Claude through a **global cross-region inference profile**, with the
exact profile ID copied from the Bedrock console into `.env` as
`BEDROCK_INFERENCE_PROFILE_ID`. It is never hand-typed and never guessed.

**The fallback, also already decided:** if ap-south-1 cannot reach a
vision-capable Claude profile, move the **whole stack** to `us-east-1`. We do
not split regions. A split stack means cross-region data transfer charges,
two sets of CloudWatch logs, two places for an IAM policy to be wrong, and a
latency path nobody will debug at 2am three days before submission.

**Why this is open:** Bedrock model availability differs by region and
requires per-region model access to be enabled in the console. We have not
touched an AWS account yet, so we do not know what this one can reach.

**How to resolve (at the AWS checkpoint):**
1. Bedrock console > Model access, in ap-south-1. Confirm a vision-capable
   Claude model shows as access granted.
2. Bedrock console > Inference and assessment > Cross-region inference. Copy
   the global profile ID verbatim.
3. Paste into `.env`. Run the reader smoke test in `docs/AWS_STEPS.md`.
4. If step 1 or 2 fails, change `AWS_REGION` to `us-east-1` everywhere --
   `.env`, `infra/template.yaml`, and the deploy commands -- and redeploy.
   Record which branch was taken in `NOTES.md`.

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
