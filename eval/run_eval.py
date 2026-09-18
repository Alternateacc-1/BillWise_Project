"""Score the engine against the ground truth.

    python eval/run_eval.py

Reports, per the acceptance criteria:

    caught / missed        did we find what we planted?
    FALSE REDS             must be ZERO. This is the hard gate.
    0-25% amber band       reported separately, so the size of the band the
                           GST and excess thresholds create stays visible
                           rather than buried in the amber total.
    gray split             no_public_ceiling vs could_not_verify, because
                           they mean opposite things.

Exits non-zero on any false red or any missed finding, so CI and a human
get the same answer.

OFFLINE ONLY. PROVIDER is pinned to "local" before the pipeline is imported:
the eval is the thing most likely to be run in a loop, so it must never be
able to reach a paid API. See docs/ARCHITECTURE.md, cost controls.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

# Pin the provider BEFORE importing anything that reads config.
os.environ["PROVIDER"] = "local"

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import config  # noqa: E402
from app.models import BillInput, GrayReason, Severity  # noqa: E402
from app.pipeline.audit import audit  # noqa: E402
from app.pipeline.normalize import normalize_bill  # noqa: E402
from app.pipeline.verify import verify_bill  # noqa: E402

FIXTURES = REPO_ROOT / "eval" / "fixtures"
GROUND_TRUTH = REPO_ROOT / "eval" / "ground_truth"

_ENABLED = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _ENABLED else text


def ok(s): return _c("32;1", s)
def bad(s): return _c("31;1", s)
def warn(s): return _c("33;1", s)
def dim(s): return _c("2", s)
def bold(s): return _c("1", s)


def run_one(bill_id: str) -> dict:
    fixture = FIXTURES / f"{bill_id}.json"
    truth = json.loads((GROUND_TRUTH / f"{bill_id}.json").read_text(encoding="utf-8"))

    bill = BillInput.model_validate_json(fixture.read_text(encoding="utf-8"))
    items, stats = verify_bill(bill)
    flags = audit(items, normalize_bill(items), stats)

    # A finding is (item_index, rule_id, severity). Gray reason is checked
    # separately so a right-verdict-wrong-reason case is reported honestly
    # rather than silently passing.
    produced = {(f.item_index, f.rule_id, f.severity.value) for f in flags}
    gray_reasons = {
        f.item_index: (f.gray_reason.value if f.gray_reason else None)
        for f in flags if f.rule_id == "R9"
    }

    caught, missed, wrong_reason = [], [], []
    for entry in truth["expected"]:
        key = (entry["item_index"], entry["rule_id"], entry["severity"])
        if key in produced:
            caught.append(entry)
            wanted = entry.get("gray_reason")
            if wanted and gray_reasons.get(entry["item_index"]) != wanted:
                wrong_reason.append({
                    **entry, "actual_reason": gray_reasons.get(entry["item_index"]),
                })
        else:
            missed.append(entry)

    allowed_red = set(truth["allowed_red_item_indexes"])
    false_reds = [
        {
            "item_index": f.item_index,
            "rule_id": f.rule_id,
            "item_name": next(
                (i.name for i in items if i.index == f.item_index), "(whole bill)"
            ),
            "amount_affected": str(f.amount_affected),
        }
        for f in flags
        if f.severity is Severity.RED and f.item_index not in allowed_red
    ]

    # The 0-25% band: an R5 amber that was blocked from red ONLY because the
    # excess did not clear RED_EXCESS_FRACTION.
    amber_band = []
    for f in flags:
        if f.rule_id != "R5" or f.severity is not Severity.AMBER:
            continue
        interpretations = f.evidence.get("interpretations", [])
        if not interpretations:
            continue
        excess = min(Decimal(i["excess_over_ceiling_pct"]) for i in interpretations)
        if Decimal("0") < excess <= config.RED_EXCESS_FRACTION * 100:
            amber_band.append({
                "item_index": f.item_index,
                "item_name": next(
                    (i.name for i in items if i.index == f.item_index), "?"
                ),
                "excess_pct": str(excess),
            })

    no_ceiling = sum(
        1 for f in flags if f.gray_reason is GrayReason.NO_PUBLIC_CEILING
    )
    could_not_verify = sum(
        1 for f in flags if f.gray_reason is GrayReason.COULD_NOT_VERIFY
    )

    return {
        "bill_id": bill_id,
        "description": truth.get("description", ""),
        "lines": len(items),
        "expected": len(truth["expected"]),
        "caught": caught,
        "missed": missed,
        "wrong_gray_reason": wrong_reason,
        "false_reds": false_reds,
        "amber_band": amber_band,
        "no_public_ceiling": no_ceiling,
        "could_not_verify": could_not_verify,
        "auto_high": stats.auto_high,
        "still_unverified": stats.still_unverified,
        "reconciliation": stats.reconciliation.value,
    }


def main() -> int:
    bill_ids = sorted(p.stem for p in GROUND_TRUTH.glob("bill_*.json"))
    if not bill_ids:
        print("No ground truth found. Run: python scripts/make_demo_bills.py",
              file=sys.stderr)
        return 2

    results = [run_one(b) for b in bill_ids]

    print()
    print("=" * 74)
    print(bold("  BillSahi evaluation"))
    print("=" * 74)
    print(f"  PROVIDER={config.PROVIDER}   GST={config.GST_PERCENT}%   "
          f"red needs >={config.RED_EXCESS_FRACTION * 100}% excess, "
          f">=Rs {config.RED_MIN_AMOUNT_AFFECTED}, <={config.RED_MAX_RATIO}x")
    print()
    print(f"  {'bill':<10}{'lines':>6}{'caught':>8}{'missed':>8}"
          f"{'false red':>11}{'read ok':>9}  {'reconcile':<14}")
    print(dim("  " + "-" * 70))

    for r in results:
        caught = f"{len(r['caught'])}/{r['expected']}"
        missed = str(len(r["missed"]))
        false_red = str(len(r["false_reds"]))
        reading = f"{r['auto_high']}/{r['lines']}"
        line = (f"  {r['bill_id']:<10}{r['lines']:>6}{caught:>8}{missed:>8}"
                f"{false_red:>11}{reading:>9}  {r['reconciliation']:<14}")
        print(bad(line) if r["false_reds"] or r["missed"] else line)

    total_expected = sum(r["expected"] for r in results)
    total_caught = sum(len(r["caught"]) for r in results)
    total_missed = sum(len(r["missed"]) for r in results)
    total_false = sum(len(r["false_reds"]) for r in results)
    total_band = sum(len(r["amber_band"]) for r in results)
    total_no_ceiling = sum(r["no_public_ceiling"] for r in results)
    total_cnv = sum(r["could_not_verify"] for r in results)
    total_wrong_reason = sum(len(r["wrong_gray_reason"]) for r in results)

    print(dim("  " + "-" * 70))
    print()
    print(bold("  Results"))
    print(f"    caught                  {total_caught}/{total_expected}")
    print(f"    missed                  {total_missed}")

    verdict = ok("0  PASS") if total_false == 0 else bad(f"{total_false}  FAIL")
    print(f"    FALSE REDS              {verdict}")
    print()

    print(bold("  The 0-25% amber band"))
    print(dim("    Items above the ceiling but below the red margin. Reported"))
    print(dim("    separately so the size of the band stays visible."))
    print(f"    in band                 {total_band}")
    for r in results:
        for entry in r["amber_band"]:
            print(f"      {r['bill_id']} line {entry['item_index']:>2}  "
                  f"{entry['item_name'][:40]:<40} +{entry['excess_pct']}%")
    print()

    print(bold("  Why items were not compared"))
    print(f"    no_public_ceiling       {total_no_ceiling}"
          + dim("   (room, nursing, consumables, lab - a feature, not a gap)"))
    print(f"    could_not_verify        {total_cnv}"
          + dim("   (unreadable, unresolved or ambiguous)"))
    if total_wrong_reason:
        print(warn(f"    wrong gray reason       {total_wrong_reason}"))
        for r in results:
            for entry in r["wrong_gray_reason"]:
                print(warn(f"      {r['bill_id']} line {entry['item_index']}: "
                           f"expected {entry['gray_reason']}, "
                           f"got {entry['actual_reason']}"))
    print()

    if total_missed:
        print(bad("  Missed findings"))
        for r in results:
            for entry in r["missed"]:
                print(bad(f"    {r['bill_id']} line {entry['item_index']:>2}  "
                          f"{entry['rule_id']} {entry['severity']:<6} "
                          f"{entry['item_name'][:36]}"))
                if entry.get("why"):
                    print(dim(f"        {entry['why']}"))
        print()

    if total_false:
        print(bad("  FALSE REDS -- these are the failures that matter"))
        for r in results:
            for entry in r["false_reds"]:
                print(bad(f"    {r['bill_id']} line {entry['item_index']:>2}  "
                          f"{entry['rule_id']}  {entry['item_name'][:40]}  "
                          f"Rs {entry['amount_affected']}"))
        print()

    passed = total_false == 0 and total_missed == 0 and total_wrong_reason == 0
    print("=" * 74)
    print(ok("  PASS") if passed else bad("  FAIL"))
    print("=" * 74)
    print()
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
