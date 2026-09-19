"""Ceiling matching. Pure Python, no AWS variant, fully unit-tested.

Loads data/reference/reference_prices.csv and answers one question: for this
bill line, what is the applicable published ceiling -- if any?

Three rules govern everything here, all of them established against the real
NPPA data in Phase 0/0b and each protected by a regression test:

  1. EXACT strength, and exact pack size. The special-feature file prices
     MEROPENEM 500 MG above MEROPENEM 1000 MG, and Ringer Lactate's 100 ml
     pack is dearer per ml than its 500 ml pack. Fuzzy matching on either
     dimension silently corrupts verdicts.

  2. TWO TIERS, gated on the whole product match. Exact spelling first;
     synonym-expanded only if tier 1 finds nothing. "Highest applicable" is
     resolved strictly within the winning tier.

  3. UNKNOWN RESOLVES IN THE HOSPITAL'S FAVOUR. A bill rarely states whether
     a tablet is plain, dispersible or modified release. When the modifier is
     unknown we widen to every modifier variant and take the HIGHEST ceiling,
     exactly as the dual-interpretation rule does for pack size.
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from ..models import CeilingMatch
from .salt_synonyms import canonicalise_salt_set, normalise_salt_set

REPO_ROOT = Path(__file__).resolve().parents[3]
def _reference_path(name: str) -> Path:
    """Locate a reference file in the repo OR in the Lambda bundle.

    Repo layout:   <root>/data/reference/<name>
    Lambda bundle: <task root>/reference_data/<name>, staged there by
                   scripts/stage_lambda.py because CodeUri is backend/ and
                   nothing outside it is deployed.
    """
    import os

    override = os.getenv("REFERENCE_DIR")
    if override:
        return Path(override) / name
    bundled = Path(__file__).resolve().parents[2] / "reference_data" / name
    if bundled.exists():
        return bundled
    return REPO_ROOT / "data" / "reference" / name


REFERENCE_CSV = _reference_path("reference_prices.csv")

CEILING_SOURCES = ("ceiling", "special_feature")


class ReferenceRow:
    """A row of reference_prices.csv, typed just enough to be safe."""

    __slots__ = (
        "ref_id", "source", "formulation_raw", "salt_components", "dosage_form",
        "form_modifier", "strength_raw", "strength_mg", "strength_kind",
        "unit_basis", "unit_qty", "price_checkable", "price_ex_gst",
        "so_number", "so_date", "manufacturer", "marketing_company",
        "retrieved_on", "status", "quarantine_reason", "unit_basis_raw",
    )

    def __init__(self, row: dict[str, str]) -> None:
        self.ref_id = row["ref_id"]
        self.source = row["source"]
        self.formulation_raw = row["formulation_raw"]
        self.salt_components = json.loads(row["salt_components"])
        self.dosage_form = row["dosage_form"]
        self.form_modifier = row["form_modifier"]
        self.strength_raw = row["strength_raw"]
        self.strength_mg = json.loads(row["strength_mg"])
        self.strength_kind = row["strength_kind"]
        self.unit_basis = row["unit_basis"]
        self.unit_qty = Decimal(row["unit_qty"])
        self.price_checkable = row["price_checkable"] == "true"
        self.price_ex_gst = Decimal(row["price_ex_gst"]) if row["price_ex_gst"] else None
        self.so_number = row["so_number"]
        self.so_date = row["so_date"]
        self.manufacturer = row["manufacturer"]
        self.marketing_company = row["marketing_company"]
        self.retrieved_on = row["retrieved_on"]
        self.status = row["status"]
        self.quarantine_reason = row["quarantine_reason"]
        self.unit_basis_raw = row["unit_basis_raw"]

    @property
    def per_base_unit(self) -> Decimal:
        return self.price_ex_gst / self.unit_qty


@lru_cache(maxsize=1)
def load_reference(path: str | None = None) -> tuple[ReferenceRow, ...]:
    target = Path(path) if path else REFERENCE_CSV
    if not target.exists():
        raise FileNotFoundError(
            f"{target} is missing. Run: python scripts/prepare_reference.py"
        )
    with target.open(encoding="utf-8", newline="") as fh:
        return tuple(ReferenceRow(r) for r in csv.DictReader(fh))


def reference_retrieved_on() -> str:
    rows = load_reference()
    return rows[0].retrieved_on if rows else ""


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

def _eligible(rows: Iterable[ReferenceRow]) -> list[ReferenceRow]:
    return [
        r for r in rows
        if r.source in CEILING_SOURCES
        and r.status == "usable"
        and r.price_checkable
        and r.price_ex_gst is not None
    ]


def _candidates(
    rows: Iterable[ReferenceRow],
    salt_key,
    wanted_salts,
    dosage_form: str,
    strength_mg: list[float],
    strength_kind: str,
    unit_basis: str,
    unit_qty: Decimal,
    form_modifier: str | None,
) -> list[ReferenceRow]:
    wanted_mg = sorted(strength_mg)
    out = []
    for r in _eligible(rows):
        if salt_key(r.salt_components) != wanted_salts:
            continue
        if r.dosage_form != dosage_form:
            continue
        if r.unit_basis != unit_basis or r.unit_qty != unit_qty:
            continue
        if r.strength_kind != strength_kind or sorted(r.strength_mg) != wanted_mg:
            continue
        # form_modifier None means UNKNOWN -- do not filter on it at all.
        if form_modifier is not None and r.form_modifier != form_modifier:
            continue
        out.append(r)
    return out


def select_ceiling(
    salt_components: list[str],
    dosage_form: str,
    strength_mg: list[float],
    strength_kind: str,
    unit_basis: str,
    ceiling_row_unit_qty: Decimal,
    form_modifier: str | None = None,
    rows: Iterable[ReferenceRow] | None = None,
) -> CeilingMatch | None:
    """The applicable ceiling, or None.

    `ceiling_row_unit_qty` IS THE CEILING ROW'S OWN UNIT QUANTITY -- the "1"
    in "Rs 0.93 per 1 tablet", or the "500" in "Rs 66.50 per 500 ml bag". It
    is a property of the NPPA REFERENCE DATA.

    IT IS NOT A PACK COUNT. Passing a pack size here searches for a ceiling
    priced per-ten-tablets, which does not exist, and the item silently loses
    its ceiling and goes gray. It was called `unit_qty` until 2026-09-19, and
    audit.py was one field-assignment away from doing exactly that to every
    packed tablet the moment Class C read the PACK column. Renamed so the
    mistake cannot be made by accident; a test pins the meaning.

    `form_modifier` distinguishes three cases, and the distinction matters:
      ""    -- the bill says this is a PLAIN tablet. Match plain only.
      "dt"  -- the bill states a modifier. Match that modifier only.
      None  -- UNKNOWN, which is most bills. Widen to every modifier variant
               and take the highest ceiling, so an under-determined reading
               always resolves in the hospital's favour.

    Tier gating is unchanged: if any exact-spelling row satisfies the
    criteria, the synonym tier is never consulted.
    """
    pool = list(rows) if rows is not None else list(load_reference())

    for salt_key, tier in ((normalise_salt_set, "exact"), (canonicalise_salt_set, "synonym")):
        wanted = salt_key(salt_components)
        found = _candidates(
            pool, salt_key, wanted, dosage_form, strength_mg, strength_kind,
            unit_basis, ceiling_row_unit_qty, form_modifier,
        )
        if not found:
            continue
        best = max(found, key=lambda r: r.per_base_unit)
        # Only report the modifier as "unknown" when it actually MATTERED --
        # i.e. the widened search had more than one modifier to choose
        # between. Saying it on every flag is noise, and on a stent, where no
        # release modifier exists at all, it is simply misleading.
        widened = form_modifier is None and len({r.form_modifier for r in found}) > 1
        return CeilingMatch(
            ref_id=best.ref_id,
            source=best.source,
            tier=tier,
            formulation_raw=best.formulation_raw,
            strength_raw=best.strength_raw,
            unit_basis=best.unit_basis,
            unit_qty=best.unit_qty,
            price_ex_gst=best.price_ex_gst,
            per_base_unit=best.per_base_unit,
            so_number=best.so_number,
            so_date=best.so_date,
            form_modifier=best.form_modifier,
            modifier_was_unknown=widened,
        )
    return None


def retail_references(
    salt_components: list[str],
    dosage_form: str,
    strength_mg: list[float],
    strength_kind: str,
    rows: Iterable[ReferenceRow] | None = None,
) -> list[ReferenceRow]:
    """Non-scheduled retail rows for the same composition. R7 context only.

    These are per-company approved prices, not ceilings binding anyone else,
    so they can never produce a red flag.
    """
    pool = list(rows) if rows is not None else list(load_reference())
    wanted = canonicalise_salt_set(salt_components)
    wanted_mg = sorted(strength_mg)
    return [
        r for r in pool
        if r.source == "retail_new_drug"
        and r.status == "usable"
        and r.price_checkable
        and r.price_ex_gst is not None
        and canonicalise_salt_set(r.salt_components) == wanted
        and r.dosage_form == dosage_form
        and r.strength_kind == strength_kind
        and sorted(r.strength_mg) == wanted_mg
    ]
