"""What EXACTLY stands between bill_06 and a priced answer, line by line.

Written because the fix queue has twice been prioritised from a stale note.
`items_read` and `auto_high` say the reading is fine; the report says 0 of 6
compared. This prints the layer each line dies at, by name, so the next fix is
chosen from a measurement rather than from a recollection.

Run:  python eval/bill_06_gap.py
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from app.models import BillInput  # noqa: E402
from app.pipeline.audit import audit  # noqa: E402
from app.pipeline.audit import ceiling_row_unit_qty_for, _unit_basis_for  # noqa: E402
from app.pipeline.match import select_ceiling  # noqa: E402
from app.pipeline.normalize import normalize_bill  # noqa: E402
from app.pipeline.verify import verify_bill  # noqa: E402

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "eval/fixtures/bill_06.json"


def _ceiling_for(norm):
    """Same call the auditor makes, so this measures the real path."""
    return select_ceiling(
        salt_components=norm.salt_components,
        dosage_form=norm.dosage_form,
        strength_mg=norm.strength_mg,
        strength_kind=norm.strength_kind,
        unit_basis=norm.unit_basis or _unit_basis_for(norm),
        ceiling_row_unit_qty=ceiling_row_unit_qty_for(norm),
        form_modifier=norm.form_modifier,
    )


def main() -> int:
    bill = BillInput.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    verified, stats = verify_bill(bill)
    normalized = normalize_bill(verified)
    flags = audit(verified, normalized, stats)
    by_index = {n.index: n for n in normalized}

    print("=" * 78)
    print("bill_06 -- where each line stops, measured")
    print("=" * 78)
    print(f"\n  reconciliation : {stats.reconciliation.value}")
    print(f"  auto_high      : {stats.auto_high} of {stats.total_items}")

    stage_counts: dict[str, int] = {}
    for item in verified:
        norm = by_index.get(item.index)
        line_flags = [f for f in flags if f.item_index == item.index]

        # Walk the layers in the order the pipeline does and name the first
        # one that fails. That is the fix that would move this line.
        if not item.is_high:
            stage = "READING (Class A territory)"
        elif norm is None or norm.match_type is None:
            stage = "IDENTITY -- name did not resolve"
        elif not norm.salt_components:
            stage = "IDENTITY -- resolved but no salts"
        elif _ceiling_for(norm) is None:
            stage = "CEILING -- identified, no published ceiling row"
        elif item.unit_price is None and not norm.pack_count:
            stage = "PER-UNIT PRICE -- no unit price and no pack size (R6)"
        else:
            stage = "PRICED"
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

        print(f"\n  {item.index}. {item.name}")
        print(f"     confidence  : {item.confidence.value}")
        print(f"     qty/unit/tot: {item.quantity} / {item.unit_price} / {item.line_total}")
        print(f"     match_type  : {getattr(norm, 'match_type', None)}")
        print(f"     salts       : {getattr(norm, 'salt_components', None)}")
        print(f"     pack_count  : {getattr(norm, 'pack_count', None)}"
              f" ({getattr(norm, 'pack_count_source', None)})")
        print(f"     STOPS AT    : {stage}")
        for f in line_flags:
            detail = f.gray_detail.value if f.gray_detail else ""
            reason = f.gray_reason.value if f.gray_reason else ""
            print(f"     flag        : {f.rule_id} {f.severity.value} {reason} {detail}")

    print("\n" + "=" * 78)
    print("  WHERE THE SIX LINES STOP")
    for stage, n in sorted(stage_counts.items(), key=lambda kv: -kv[1]):
        print(f"     {n}  {stage}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
