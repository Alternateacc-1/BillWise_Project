"""A6 -- SYNONYM-TIER CROSSING. Enumerate, then attack.

D4 accepts a measured asymmetry: a line reading "Aspirin 75mg" gates against
Rs 0.36 (the dispersible row, the only EXACT-spelling match) rather than
Rs 0.39 (the plain row, spelled ACETYLSALICYLIC ACID and reachable only
through the synonym tier, which never runs once tier 1 matches). That was
accepted because the impact stayed inside the 25% red margin.

THIS SCRIPT TESTS WHETHER THAT HOLDS GENERALLY OR ONLY FOR ASPIRIN.

The dangerous direction is specific. Tier 1 wins whenever it matches at all,
so the risk is a group whose tier-1 ceiling is LOWER than its tier-2 ceiling:
the line is then measured against a stricter allowance than the one that
really governs it, and a compliant price can be flagged.

Part 1 enumerates every salt+form+strength+unit group where the two spelling
tiers hold different ceilings, with both prices and the gap.
Part 2 attacks every gap wider than the 25% red margin.

Run:  python eval/cross_tier_audit.py
"""

from __future__ import annotations

import pathlib
import sys
from collections import defaultdict
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from app import config  # noqa: E402
from app.pipeline.match import load_reference  # noqa: E402
from app.pipeline.salt_synonyms import (  # noqa: E402
    canonicalise_salt_set,
    normalise_salt_set,
)

CEILING_SOURCES = ("ceiling", "special_feature")


def _salts(row) -> list[str]:
    raw = getattr(row, "salt_components", None) or []
    return list(raw)


def enumerate_cross_tier_gaps():
    """Every group where exact-spelling and synonym tiers disagree on price."""
    rows = [r for r in load_reference()
            if r.source in CEILING_SOURCES and r.price_checkable]

    # Group by what a QUERY would match on, canonicalised: this is the set of
    # rows the synonym tier can reach.
    canonical: dict[tuple, list] = defaultdict(list)
    for r in rows:
        salts = _salts(r)
        if not salts:
            continue
        key = (
            tuple(canonicalise_salt_set(salts)),
            r.dosage_form,
            tuple(sorted(r.strength_mg or [])),
            r.strength_kind,
            r.unit_basis,
            str(r.unit_qty),
        )
        canonical[key].append(r)

    gaps = []
    for key, group in canonical.items():
        # Within one canonical group, split by EXACT spelling. More than one
        # distinct exact key means the two tiers can see different rows.
        by_exact: dict[tuple, list] = defaultdict(list)
        for r in group:
            by_exact[tuple(normalise_salt_set(_salts(r)))].append(r)
        if len(by_exact) < 2:
            continue

        tier2_best = max(group, key=lambda r: r.per_base_unit)
        for exact_key, exact_rows in by_exact.items():
            tier1_best = max(exact_rows, key=lambda r: r.per_base_unit)
            if tier1_best.per_base_unit == tier2_best.per_base_unit:
                continue
            lower, higher = tier1_best.per_base_unit, tier2_best.per_base_unit
            gap_pct = (higher - lower) / lower * 100 if lower else Decimal("0")
            gaps.append({
                "spelling": " + ".join(exact_key),
                "form": key[1],
                "strength": key[2],
                "unit": f"{key[5]} {key[4]}",
                "tier1": lower,
                "tier1_ref": tier1_best.ref_id,
                "tier1_mod": tier1_best.form_modifier or "(plain)",
                "tier2": higher,
                "tier2_ref": tier2_best.ref_id,
                "tier2_mod": tier2_best.form_modifier or "(plain)",
                "gap_pct": gap_pct,
            })
    return sorted(gaps, key=lambda g: -g["gap_pct"])


# --------------------------------------------------------------------------
# Part 2 -- attack the collisions, with the pack gate STUBBED.
#
# The previous A6 attempt never reached the pricing path: pack_size_unknown
# blocked it first, so the run proved nothing about tier crossing. Setting
# pack_count=1 from "bill_text" makes the pack CERTAIN and collapses the two
# interpretations into one, so the ceiling comparison actually executes.
# --------------------------------------------------------------------------

from app.models import (  # noqa: E402
    ItemCategory, MatchType, NormalizedItem, ReadingConfidence, ReadingStats,
    Reconciliation, Severity, VerifiedItem,
)
from app.pipeline.audit import audit  # noqa: E402


def _priced(index, name, salts, strength, form, total, modifier=None):
    """A line whose pack size is CERTAIN, so the gate cannot hide the result."""
    item = VerifiedItem(index=index, name=name, quantity=Decimal("1"),
                        line_total=Decimal(total),
                        confidence=ReadingConfidence.HIGH)
    norm = NormalizedItem(
        index=index, category=ItemCategory.DRUG, match_type=MatchType.EXACT,
        salt_components=salts, strength_mg=[Decimal(s) for s in strength],
        strength_kind="mg", dosage_form=form, unit_basis=form,
        form_modifier=modifier,
        pack_count=Decimal("1"), pack_count_source="bill_text",
    )
    return item, norm


def _run(label, why, pairs, total):
    items = [p[0] for p in pairs]
    norms = [p[1] for p in pairs]
    stats = ReadingStats(
        total_items=len(items), auto_high=len(items), rescued_by_reread=0,
        still_unverified=0, reconciliation=Reconciliation.RECONCILED,
        sum_of_line_totals=sum(i.line_total for i in items),
        printed_grand_total=Decimal(total),
    )
    flags = audit(items, norms, stats)
    reds = [f for f in flags if f.severity is Severity.RED]
    print()
    print(f"  {label}")
    print(f"     {why}")
    print(f"     -> {'*** FALSE RED ***' if reds else 'no red'}")
    for f in flags:
        extra = f.gray_detail.value if f.gray_detail else ""
        print(f"        {f.rule_id} {f.severity.value:<6} item {f.item_index:>2} "
              f"amt {str(f.amount_affected):>8} {extra}")
    return len(reds)


def attack() -> int:
    print()
    print("=" * 78)
    print("A6 PART 2 -- attacks, pack gate stubbed so pricing actually runs")
    print("=" * 78)
    false_reds = 0

    # A6a: the aspirin collision itself. The line is priced AT the plain-tablet
    # ceiling (0.39 ex-GST => 0.4368 incl), but "ASPIRIN" matches tier 1, which
    # holds only the DISPERSIBLE row at 0.36. Compliant against the ceiling
    # that really governs it; measured against a stricter one.
    false_reds += _run(
        "A6a aspirin: compliant against the PLAIN row, gated on the DT row",
        "0.39 ex-GST = 0.4368 incl. Tier-1 allowance is 0.36*1.12 = 0.4032.",
        [_priced(1, "Aspirin 75mg Tablet", ["ASPIRIN"], [75], "tablet", "0.4368")],
        "0.4368")

    # A6b: the same line at the tier-1 RED threshold, to locate the boundary.
    false_reds += _run(
        "A6b aspirin: priced just under the tier-1 red threshold",
        "0.36 * 1.12 * 1.25 = 0.504 -- anything above this would be red",
        [_priced(1, "Aspirin 75mg Tablet", ["ASPIRIN"], [75], "tablet", "0.5039")],
        "0.5039")

    # A6c: two lines resolving to the SAME ceiling row. Does one poison the
    # other, and does duplicate detection fire on distinct products?
    false_reds += _run(
        "A6c two lines resolving to the same ceiling row",
        "same salt/form/strength, both compliant, different names",
        [_priced(1, "Aspirin 75mg Tablet", ["ASPIRIN"], [75], "tablet", "0.40"),
         _priced(2, "ASA 75mg Tablet", ["ASPIRIN"], [75], "tablet", "0.40")],
        "0.80")

    # A6d: a release modifier on the BILL that the matched row does not carry.
    # D5 says form_modifier is product identity; a mismatch must not silently
    # borrow the plain row's (different) ceiling.
    false_reds += _run(
        "A6d form_modifier on the bill, absent from the matched row",
        "bill says SR; the published rows are plain and dispersible only",
        [_priced(1, "Aspirin 75mg Tablet SR", ["ASPIRIN"], [75], "tablet",
                 "0.4368", modifier="sustained_release")],
        "0.4368")

    print()
    print("=" * 78)
    print(f"  FALSE REDS IN PART 2: {false_reds}")
    print("=" * 78)
    return false_reds


def main() -> int:
    margin = config.RED_EXCESS_FRACTION * 100

    print("=" * 78)
    print("A6 PART 1 -- every cross-tier ceiling disagreement in the 915 rows")
    print("=" * 78)
    gaps = enumerate_cross_tier_gaps()

    if not gaps:
        print("\n  NONE. The two spelling tiers never hold different ceilings")
        print("  for the same salt+form+strength+unit group.")
    for g in gaps:
        flag = "  <-- EXCEEDS THE RED MARGIN" if g["gap_pct"] > margin else ""
        print(f"\n  {g['spelling']}  |  {g['form']} {g['strength']} per {g['unit']}")
        print(f"     tier 1 (exact spelling) : {g['tier1']:.4f}  "
              f"{g['tier1_mod']}  [{g['tier1_ref']}]")
        print(f"     tier 2 (synonym-widened): {g['tier2']:.4f}  "
              f"{g['tier2_mod']}  [{g['tier2_ref']}]")
        print(f"     GAP                     : {g['gap_pct']:.1f}%{flag}")

    over = [g for g in gaps if g["gap_pct"] > margin]
    print()
    print("=" * 78)
    print(f"  groups where the tiers disagree : {len(gaps)}")
    print(f"  red margin                      : {margin:.0f}%")
    print(f"  gaps EXCEEDING the margin       : {len(over)}")
    if gaps and not over:
        widest = max(g["gap_pct"] for g in gaps)
        print(f"  widest gap measured             : {widest:.1f}%")
        print()
        print("  => D4's asymmetry is BOUNDED, not merely accepted. No")
        print("     cross-tier disagreement in the published list is wide")
        print("     enough to change a verdict on its own.")
    print("=" * 78)

    attack()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
