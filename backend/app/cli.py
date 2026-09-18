"""Offline CLI. Runs the whole pipeline against a fixture and prints a report.

    python -m app.cli audit eval/fixtures/bill_01.json

No network, no AWS, no cost.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

from .models import BillInput, GrayReason, Severity
from .money import format_inr
from .pipeline.audit import audit
from .pipeline.explain import explain_all
from .pipeline.match import reference_retrieved_on
from .pipeline.normalize import normalize_bill
from .pipeline.verify import verify_bill

# --------------------------------------------------------------------------
# Colour. Disabled when piped, and when NO_COLOR is set.
# --------------------------------------------------------------------------

_ENABLED = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _ENABLED else text


RED = lambda s: _c("31;1", s)      # noqa: E731
AMBER = lambda s: _c("33;1", s)    # noqa: E731
GREEN = lambda s: _c("32;1", s)    # noqa: E731
GRAY = lambda s: _c("90", s)       # noqa: E731
BOLD = lambda s: _c("1", s)        # noqa: E731
DIM = lambda s: _c("2", s)         # noqa: E731

_SEVERITY_STYLE = {
    Severity.RED: (RED, "RED "),
    Severity.AMBER: (AMBER, "AMBER"),
    Severity.GREEN: (GREEN, "GREEN"),
    Severity.GRAY: (GRAY, "GRAY "),
}

WIDTH = 78


def _rule() -> str:
    return DIM("-" * WIDTH)


def _wrap(text: str, indent: int = 8, width: int = WIDTH) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width - indent:
            lines.append(" " * indent + current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(" " * indent + current)
    return lines


def run_audit(fixture_path: Path, as_json: bool = False) -> int:
    bill = BillInput.model_validate_json(fixture_path.read_text(encoding="utf-8"))

    items, stats = verify_bill(bill)
    normalized = normalize_bill(items)
    flags = explain_all(audit(items, normalized, stats))

    retrieved_on = reference_retrieved_on()

    if as_json:
        print(json.dumps({
            "bill_id": bill.bill_id,
            "stats": stats.model_dump(mode="json"),
            "flags": [f.model_dump(mode="json") for f in flags],
        }, indent=2))
        return 0

    by_index: dict[int, list] = {}
    for flag in flags:
        by_index.setdefault(flag.item_index, []).append(flag)

    print()
    print(BOLD(f"  BillSahi report  -  {bill.bill_id}"))
    print(f"  {bill.hospital_name}")
    print(f"  Bill date {bill.bill_date}")
    print()

    # --- reading quality -------------------------------------------------
    recon = stats.reconciliation.value
    recon_text = {
        "reconciled": GREEN("reconciled"),
        "mismatch": AMBER("mismatch"),
        "no_total_found": GRAY("no total found"),
    }[recon]
    print(BOLD("  Reading"))
    print(f"    {stats.auto_high}/{stats.total_items} lines verified at high confidence"
          f"   |   {stats.still_unverified} unverified")
    if stats.printed_grand_total is not None:
        print(f"    Line totals Rs {stats.sum_of_line_totals}  vs  printed Rs "
              f"{stats.printed_grand_total}   ->  {recon_text}")
    else:
        print(f"    Bill total: {recon_text}")
    print()

    # --- bill-level flags ------------------------------------------------
    for flag in by_index.get(-1, []):
        style, label = _SEVERITY_STYLE[flag.severity]
        print(f"  {style('[' + label + ']')} {BOLD('Whole bill')}")
        for line in _wrap(flag.explanation, indent=8):
            print(line)
        print()

    # --- per-item --------------------------------------------------------
    print(BOLD("  Items"))
    print(_rule())
    counts = {Severity.RED: 0, Severity.AMBER: 0, Severity.GREEN: 0, Severity.GRAY: 0}
    no_ceiling = could_not_verify = 0

    for item in items:
        item_flags = by_index.get(item.index, [])
        severity = Severity.GRAY
        for candidate in (Severity.RED, Severity.AMBER, Severity.GREEN, Severity.GRAY):
            if any(f.severity is candidate for f in item_flags):
                severity = candidate
                break
        counts[severity] += 1

        # Count the gray REASON only for items that actually ended up gray.
        # An item can carry an R9 gray alongside an amber R3 duplicate flag;
        # it is bucketed amber, so counting its reason here would make the
        # breakdown add up to more than the gray total.
        if severity is Severity.GRAY:
            for flag in item_flags:
                if flag.gray_reason is GrayReason.NO_PUBLIC_CEILING:
                    no_ceiling += 1
                elif flag.gray_reason is GrayReason.COULD_NOT_VERIFY:
                    could_not_verify += 1

        style, label = _SEVERITY_STYLE[severity]
        # "Rs ", not the rupee sign: this prints to a Windows console whose
        # default codec raises UnicodeEncodeError on U+20B9. The UI and the
        # letter, which are UTF-8 end to end, use the real symbol.
        total = (
            format_inr(item.line_total, symbol="Rs ")
            if item.line_total is not None else "Rs ?"
        )
        name = item.name if len(item.name) <= 44 else item.name[:41] + "..."
        print(f"  {style('[' + label + ']')} {item.index:>2}. {name:<44} {total:>12}")

        for flag in sorted(item_flags, key=lambda f: f.rule_id):
            if flag.severity is Severity.GREEN:
                continue
            tag = DIM(f"({flag.rule_id})")
            for n, line in enumerate(_wrap(flag.explanation, indent=8)):
                print(f"{line} {tag}" if n == 0 else line)
        if any(f.severity is Severity.GREEN for f in item_flags):
            print(DIM("        Within the published ceiling. (R5)"))
    print(_rule())

    # --- summary ---------------------------------------------------------
    print()
    print(BOLD("  Summary"))
    print(f"    {RED(str(counts[Severity.RED]) + ' may be above the listed ceiling')}"
          f"   {AMBER(str(counts[Severity.AMBER]) + ' may need clarification')}"
          f"   {GREEN(str(counts[Severity.GREEN]) + ' within ceiling')}"
          f"   {GRAY(str(counts[Severity.GRAY]) + ' not compared')}")
    print()
    print(GRAY(f"    Of the {counts[Severity.GRAY]} not compared:"))
    print(GRAY(f"      {no_ceiling} have no public price ceiling "
               "(room, nursing, consumables, lab) - checked for arithmetic and duplication only"))
    print(GRAY(f"      {could_not_verify} could not be confidently identified"))

    affected = sum((f.amount_affected for f in flags), Decimal("0"))
    print()
    print("    Total amount affected across all points raised: "
          + format_inr(affected, symbol="Rs "))
    print()
    print(DIM(f"    Prices as per NPPA data retrieved {retrieved_on}."))
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    audit_cmd = sub.add_parser("audit", help="audit a bill fixture")
    audit_cmd.add_argument("fixture", type=Path)
    audit_cmd.add_argument("--json", action="store_true", help="machine-readable output")

    args = parser.parse_args(argv)
    if args.command == "audit":
        if not args.fixture.exists():
            print(f"No such fixture: {args.fixture}", file=sys.stderr)
            return 2
        return run_audit(args.fixture, as_json=args.json)
    return 2


if __name__ == "__main__":
    sys.exit(main())
