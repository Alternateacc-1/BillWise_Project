"""Diagnose why the Bedrock second reader is not firing on PDFs.

READS ONLY. Makes exactly one Bedrock call with a PDF and one with a JPEG,
using your local credentials and the profile in .env, and prints the real
exception instead of swallowing it.

WHY THIS EXISTS: read_with_bedrock() catches every exception and returns None,
because a missing second reader must cost confidence rather than break the
request. That is right for production and useless for diagnosis -- on the
deployed stack a PDF comes back `only_one_reader_ran` with no clue why.

Cost: about 2 calls' worth of tokens, a couple of cents at most.

Run:  python scripts/probe_bedrock_pdf.py
"""

from __future__ import annotations

import os
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))


def _load_env() -> None:
    """Minimal .env reader. No dependency, no overwriting of real env vars."""
    env = REPO_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    _load_env()
    import boto3

    region = os.environ.get("AWS_REGION", "us-east-1")
    profile_id = os.environ.get("BEDROCK_INFERENCE_PROFILE_ID", "")
    if not profile_id:
        print("  BEDROCK_INFERENCE_PROFILE_ID is not set in .env")
        return 1

    print(f"  region  : {region}")
    print(f"  profile : {profile_id}")

    client = boto3.client("bedrock-runtime", region_name=region)
    prompt = "Reply with the single word OK."

    cases = [
        ("PDF  (document block)", "bill_06.pdf",
         lambda b: {"document": {"format": "pdf", "name": "bill",
                                 "source": {"bytes": b}}}),
        ("JPEG (image block)", "bill_02.jpg",
         lambda b: {"image": {"format": "jpeg", "source": {"bytes": b}}}),
    ]

    for label, filename, block in cases:
        path = REPO_ROOT / "eval" / "demo_bills" / filename
        print()
        print(f"  --- {label}: {filename} ---")
        if not path.exists():
            print(f"      missing: {path}")
            continue
        try:
            response = client.converse(
                modelId=profile_id,
                messages=[{"role": "user",
                           "content": [block(path.read_bytes()),
                                       {"text": prompt}]}],
                inferenceConfig={"maxTokens": 64, "temperature": 0},
            )
            text = response["output"]["message"]["content"][0]["text"]
            usage = response.get("usage", {})
            print(f"      OK  reply={text.strip()[:40]!r}  "
                  f"tokens in/out={usage.get('inputTokens')}/"
                  f"{usage.get('outputTokens')}")
        except Exception as exc:  # noqa: BLE001 - printing the cause IS the point
            print(f"      FAILED  {type(exc).__name__}")
            print(f"      {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
