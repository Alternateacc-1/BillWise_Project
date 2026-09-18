"""Configuration and audit thresholds.

Created in Phase 0 so the approved threshold decisions are recorded in code
before the rules that consume them exist. Read docs/ARCHITECTURE.md for the
longer argument; the short version is in the comments below.

Nothing here reads a secret. AWS credentials come from the environment's own
credential chain (SSO locally, an IAM role on Lambda) and never from a file
in this repo.
"""

from __future__ import annotations

import os
from decimal import Decimal

# --------------------------------------------------------------------------
# Provider switch
# --------------------------------------------------------------------------

#: "local" runs fully offline: fixtures instead of Textract/Bedrock, SQLite
#: instead of DynamoDB, a local directory instead of S3. Zero network, zero
#: cost. "aws" enables the real adapters.
PROVIDER = os.getenv("PROVIDER", "local").strip().lower()

if PROVIDER not in ("local", "aws"):
    raise ValueError(f"PROVIDER must be 'local' or 'aws', got {PROVIDER!r}")

#: THE region. Every boto3 client in aws_clients.py is built with this and
#: nothing else, so there is exactly one place to change it.
#:
#: Two variable names, in priority order, and the order matters:
#:   AWS_REGION_NAME -- what infra/template.yaml sets on Lambda. It cannot use
#:                      AWS_REGION, because that is a RESERVED Lambda env var
#:                      and CloudFormation rejects a template that sets it.
#:   AWS_REGION      -- what .env sets locally, and what the Lambda runtime
#:                      sets for itself automatically.
#:
#: Reading only AWS_REGION used to work on Lambda purely by accident: the
#: runtime populates it, so the template's AWS_REGION_NAME was dead config
#: that nothing read. That happened to be correct and was not robust.
#:
#: us-east-1 (N. Virginia). FINAL, after a round trip through ap-south-1.
#:
#: The original target was Mumbai, to sit near the Indian users this tool is
#: for. Two facts settled it the other way, both verified on AWS model cards:
#:   1. Claude Sonnet 4.6 supports NO geo profile from ap-south-1 -- only the
#:      GLOBAL profile, which routes to 33 Regions worldwide. From us-east-1
#:      the US geo profile is available: 3 Regions, and AWS guarantees a
#:      geo-tied destination list never changes.
#:   2. Textract AnalyzeExpense runs at 5 TPS in us-east-1, 1 TPS in Mumbai.
#: So us-east-1 gives BETTER data containment than Mumbai would have for this
#: model. The cost is latency to Indian users -- a real trade, stated plainly
#: in docs/ARCHITECTURE.md.
#:
#: THE DETOUR IS WORTH REMEMBERING. This moved to us-east-1, back to Mumbai,
#: and back again in one day. The first move was triggered by "Bedrock has no
#: Claude in Mumbai", which was WRONG: the real blocker was the Anthropic
#: USE-CASE-DETAILS form, which gates every Anthropic model ACCOUNT-WIDE.
#: "The model is not offered in this Region" and "this account may not call
#: the model anywhere yet" look IDENTICAL in the console. Check the
#: account-level gate before concluding anything about a Region.
AWS_REGION = (
    os.getenv("AWS_REGION_NAME")
    or os.getenv("AWS_REGION")
    or "us-east-1"
).strip()

#: Cross-region inference profile ID for Claude, copied verbatim from the
#: Bedrock console. Empty in local mode. Never hand-typed or guessed -- see
#: docs/OPEN_QUESTIONS.md Q1.
BEDROCK_INFERENCE_PROFILE_ID = os.getenv("BEDROCK_INFERENCE_PROFILE_ID", "").strip()

S3_BUCKET = os.getenv("S3_BUCKET", "").strip()
DDB_TABLE = os.getenv("DDB_TABLE", "").strip()

#: The deployed frontend's origin, added to the CORS allowlist in AWS mode.
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "").strip()


# --------------------------------------------------------------------------
# Audit thresholds
#
# These four numbers are the entire defence against false red flags, which is
# our one hard correctness requirement. Every one of them errs toward SILENCE:
# when in doubt we say less, not more. Changing any of them without rerunning
# eval/run_eval.py is how this project starts accusing innocent hospitals.
# --------------------------------------------------------------------------

#: GST rate assumed when converting an ex-tax ceiling into the maximum price
#: a patient could legitimately be charged.
#:
#: WHY 12 AND NOT 5: medicines in India attract either 5% or 12% GST
#: depending on the formulation, and we usually cannot tell which from a bill
#: line. The ceiling is exclusive of tax, so a HIGHER assumed GST produces a
#: HIGHER permitted price and therefore FEWER red flags. Assuming 12% means we
#: stay silent in the ambiguous band instead of flagging a compliant seller.
#:
#: Verify the current rates before any public launch -- GST slabs move.
GST_PERCENT = Decimal(os.getenv("GST_PERCENT", "12"))

#: How far above the GST-inclusive ceiling a price must sit before it can be
#: red rather than amber.
#:
#: WHY 25%: measured against real data. Augmentin 625 Duo, the most widely
#: sold amoxicillin-clavulanate brand in India, lists at Rs 223.42 for a strip
#: of 10 = Rs 22.34/tablet against a ceiling of Rs 18.74. That is ~6% above
#: the 12%-GST-inclusive cap. A naive "any excess is red" rule flags a GSK
#: blockbuster on day one. Anything inside 25% is far more likely to be a
#: stale price, a pack-size ambiguity or a tax-slab difference than an
#: overcharge, so it is reported as amber with the arithmetic shown.
RED_EXCESS_FRACTION = Decimal(os.getenv("RED_EXCESS_FRACTION", "0.25"))

#: Minimum rupee impact before a price difference can be red.
#:
#: WHY 50: a few rupees on a strip of paracetamol is not worth a patient
#: raising with a hospital, and rounding on small denominations produces a
#: long tail of technically-true, practically-useless flags.
RED_MIN_AMOUNT_AFFECTED = Decimal(os.getenv("RED_MIN_AMOUNT_AFFECTED", "50"))

#: Maximum plausible ratio of billed price to ceiling before we assume OUR
#: reading is wrong rather than the bill.
#:
#: WHY 50x: a real overcharge is a small multiple -- a stent billed at
#: Rs 1,50,000 against a Rs 39,186 ceiling is 3.8x. A ratio of 100x almost
#: always means we read a strip price as a per-tablet price, or missed a
#: decimal point. Above this the item goes gray, not red.
RED_MAX_RATIO = Decimal(os.getenv("RED_MAX_RATIO", "50"))

#: Rounding tolerance on arithmetic rules (R1, R2), in rupees.
ARITHMETIC_TOLERANCE = Decimal("1")

#: Date the NPPA price lists in data/raw/ were retrieved. Displayed next to
#: every verdict. Must match prepare_reference.RETRIEVED_ON.
REFERENCE_RETRIEVED_ON = os.getenv("REFERENCE_RETRIEVED_ON", "2026-09-18").strip()


def gst_multiplier() -> Decimal:
    """Ceiling -> maximum legitimate price, e.g. Decimal('1.12')."""
    return Decimal(1) + GST_PERCENT / Decimal(100)


def red_threshold(ceiling_ex_gst: Decimal) -> Decimal:
    """The per-unit price above which an item may be flagged red.

    ceiling -> ceiling x (1 + GST) x (1 + RED_EXCESS_FRACTION)
    """
    return ceiling_ex_gst * gst_multiplier() * (Decimal(1) + RED_EXCESS_FRACTION)


def amber_threshold(ceiling_ex_gst: Decimal) -> Decimal:
    """The per-unit price above which an item enters the 0-25% amber band."""
    return ceiling_ex_gst * gst_multiplier()
