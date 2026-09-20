"""Configuration and audit thresholds.

The threshold rationale lives in the comments below; the longer argument is
in docs/ARCHITECTURE.md.

Nothing here reads a secret. AWS credentials come from the environment's own
credential chain (SSO locally, an IAM role on Lambda), never from a file in
this repo.
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

# The region. Every boto3 client in aws_clients.py is built from this and
# nothing else, so there is one place to change it.
#
# Two names, in priority order. infra/template.yaml must set
# AWS_REGION_NAME, because AWS_REGION is a RESERVED Lambda variable and
# CloudFormation rejects a template that sets it. Locally, .env may set
# either; on Lambda the runtime populates AWS_REGION itself.
#
# us-east-1, and the choice is about data residency rather than latency.
# From here the US geo inference profile routes to 3 Regions and AWS
# guarantees that list never changes, so infra/template.yaml can pin all
# three in IAM. The global profile routes to 33 and its list can change,
# which for a document that is somebody's medical bill is the wrong trade.
# The cost is latency for Indian users; see docs/ARCHITECTURE.md.
AWS_REGION = (
    os.getenv("AWS_REGION_NAME")
    or os.getenv("AWS_REGION")
    or "us-east-1"
).strip()

# Cross-region inference profile ID, copied verbatim from the Bedrock
# console. Empty in local mode. Never hand-typed -- a guessed ID fails at
# the first call.
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

# GST assumed when turning an ex-tax ceiling into the maximum a patient
# could legitimately be charged.
#
# Medicines attract 5% or 12% and a bill rarely says which. A HIGHER assumed
# GST gives a HIGHER permitted price and therefore FEWER flags, so 12% keeps
# us silent in the ambiguous band rather than flagging a compliant seller.
# Verify the rate before any public launch; GST slabs move.
GST_PERCENT = Decimal(os.getenv("GST_PERCENT", "12"))

# How far above the GST-inclusive ceiling a price must sit to be red rather
# than amber.
#
# 25%, measured against real data: Augmentin 625 Duo, the best-selling
# amoxicillin-clavulanate in India, lists about 6% above its cap. A rule of
# "any excess is red" flags a blockbuster on day one. Inside 25% is far more
# likely a stale price, a pack-size ambiguity or a tax-slab difference, so it
# is amber with the arithmetic shown.
RED_EXCESS_FRACTION = Decimal(os.getenv("RED_EXCESS_FRACTION", "0.25"))

# Minimum rupee impact before a price difference can be red. A few rupees on
# a strip of paracetamol is not worth raising with a hospital, and rounding
# on small denominations produces a long tail of useless flags.
RED_MIN_AMOUNT_AFFECTED = Decimal(os.getenv("RED_MIN_AMOUNT_AFFECTED", "50"))

# Above this ratio of billed price to ceiling, assume OUR READING is wrong
# rather than the bill. A real overcharge is a small multiple -- a stent at
# 3.8x the ceiling is real, 100x is a lost decimal point. The item goes gray.
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
