"""Contracts. Everything the pipeline passes around is defined here.

Money is Decimal everywhere. Never float -- a bill is arithmetic the user
will check by hand, and 0.1 + 0.2 != 0.3 is not a defensible answer.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    RED = "red"
    AMBER = "amber"
    GREEN = "green"
    GRAY = "gray"


class GrayReason(str, Enum):
    """Why an item has no price verdict. These mean OPPOSITE things.

    NO_PUBLIC_CEILING -- we checked, and no published ceiling exists for this
    kind of charge. Room rent, nursing, consumables, lab tests, procedure
    fees. There is nothing to compare against and never was. This is a
    FEATURE: it tells the user the system knows the limits of its own
    authority, and it must be worded that way in the interface.

    COULD_NOT_VERIFY -- something went wrong on OUR side. The line was
    unreadable, the name did not resolve, the match was ambiguous, or the
    pack size was unknown. A published ceiling may well exist; we just cannot
    responsibly say which one applies.
    """

    NO_PUBLIC_CEILING = "no_public_ceiling"
    COULD_NOT_VERIFY = "could_not_verify"


class GrayDetail(str, Enum):
    """Why COULD_NOT_VERIFY applied. These are NOT the same failure.

    COULD_NOT_READ     -- the two readers disagreed, or the arithmetic did not
                          hold, or a value was outside sane bounds. We do not
                          trust our own reading of the line.

    COULD_NOT_IDENTIFY -- we read the line perfectly well, but could not work
                          out which medicine it is, so there is no ceiling to
                          compare against.

    PACK_SIZE_UNKNOWN  -- we read it and identified it, but the bill does not
                          say whether "Qty 10" means ten tablets or ten
                          strips, and the price is such that the answer
                          decides the verdict. See the correctness argument in
                          docs/ARCHITECTURE.md: when the price is under the
                          allowance we can still say green, because it holds
                          whatever the pack size is. When it is over, nothing
                          can be concluded at all.

    Conflating them produced a real bug: the summary counted one thing and the
    cards said another.
    """

    COULD_NOT_READ = "could_not_read"
    COULD_NOT_IDENTIFY = "could_not_identify"
    PACK_SIZE_UNKNOWN = "pack_size_unknown"


class ReadingConfidence(str, Enum):
    HIGH = "high"
    UNVERIFIED = "unverified_reading"


class ItemCategory(str, Enum):
    """What kind of line this is. Decides which gray reason applies."""

    DRUG = "drug"
    CONSUMABLE = "consumable"
    SERVICE = "service"
    UNKNOWN = "unknown"


#: Categories for which no public price ceiling exists, by definition.
NO_CEILING_CATEGORIES = {ItemCategory.CONSUMABLE, ItemCategory.SERVICE}


class MatchType(str, Enum):
    EXACT = "exact"
    PROBABLE = "probable"
    AMBIGUOUS = "ambiguous"
    NONE = "none"


# --------------------------------------------------------------------------
# Reader output
# --------------------------------------------------------------------------

class ReaderItem(BaseModel):
    """One line as a single reader saw it. Values may be None -- a reader
    that cannot read a number must say so rather than guess."""

    model_config = ConfigDict(extra="forbid")

    index: int
    name: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    discount: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    line_total: Decimal | None = None
    confidence: Decimal | None = Field(default=None, description="0-100")
    page: int = 1


class ReaderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    items: list[ReaderItem] = Field(default_factory=list)
    printed_grand_total: Decimal | None = None


class BillInput(BaseModel):
    """A bill as read. In local mode this is a fixture on disk."""

    model_config = ConfigDict(extra="forbid")

    bill_id: str
    hospital_name: str = ""
    bill_date: str = ""
    reader_a: ReaderOutput
    reader_b: ReaderOutput | None = None
    user_stated_mrp: dict[int, Decimal] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

class VerifiedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    name: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    discount: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    line_total: Decimal | None = None
    page: int = 1
    confidence: ReadingConfidence = ReadingConfidence.UNVERIFIED
    #: Machine-readable notes on why the reading is or is not trusted.
    reasons: list[str] = Field(default_factory=list)

    @property
    def is_high(self) -> bool:
        return self.confidence is ReadingConfidence.HIGH


class Reconciliation(str, Enum):
    RECONCILED = "reconciled"
    #: The printed total is HIGHER than the lines add up to. The bill asks for
    #: more than it itemises, which is the only direction worth a question.
    MISMATCH = "mismatch"
    #: The printed total is LOWER than the lines add up to. The patient is
    #: charged LESS than the itemisation justifies -- almost always a discount
    #: or round-off we did not read. Not a harm, and not a finding.
    BELOW_LINE_SUM = "below_line_sum"
    NO_TOTAL_FOUND = "no_total_found"


class ReadingStats(BaseModel):
    """Quoted in the demo video, so it is recorded per bill."""

    model_config = ConfigDict(extra="forbid")

    total_items: int = 0
    auto_high: int = 0
    rescued_by_reread: int = 0
    still_unverified: int = 0
    reconciliation: Reconciliation = Reconciliation.NO_TOTAL_FOUND
    sum_of_line_totals: Decimal | None = None
    printed_grand_total: Decimal | None = None


# --------------------------------------------------------------------------
# Normalisation and matching
# --------------------------------------------------------------------------

class NormalizedItem(BaseModel):
    """What we believe a bill line actually is."""

    model_config = ConfigDict(extra="forbid")

    index: int
    category: ItemCategory = ItemCategory.UNKNOWN
    match_type: MatchType = MatchType.NONE
    salt_components: list[str] = Field(default_factory=list)
    strength_mg: list[float] = Field(default_factory=list)
    strength_kind: str = "none"
    dosage_form: str = ""
    #: None means UNKNOWN, which is not the same as "" (explicitly plain).
    form_modifier: str | None = None
    pack_count: Decimal | None = None
    pack_unit: str = ""
    #: The base unit a ceiling for this item would be quoted in.
    unit_basis: str = ""
    #: Where pack_count came from. "bill_text" means the bill stated it
    #: explicitly ("Injection 500 ml") and it is CERTAIN. "brand_index" means
    #: we inferred it from the pack label and the quantity is AMBIGUOUS --
    #: "Qty 1" could be one tablet or one strip -- which is what triggers the
    #: dual-interpretation rule in R5.
    pack_count_source: str = ""
    matched_brand: str = ""
    notes: list[str] = Field(default_factory=list)

    @property
    def eligible_for_red(self) -> bool:
        """Only an exact resolution may ever produce a red flag."""
        return self.match_type is MatchType.EXACT


class CeilingMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref_id: str
    source: str
    tier: str                      # exact | synonym
    formulation_raw: str
    strength_raw: str
    unit_basis: str
    unit_qty: Decimal
    price_ex_gst: Decimal
    per_base_unit: Decimal
    so_number: str
    so_date: str
    form_modifier: str
    #: True when the bill did not state a release modifier and we widened the
    #: candidate set, taking the highest ceiling.
    modifier_was_unknown: bool = False


# --------------------------------------------------------------------------
# Flags and the report
# --------------------------------------------------------------------------

class Flag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: Severity
    item_index: int
    amount_affected: Decimal = Decimal("0")
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggested_question: str = ""
    explanation: str = ""
    gray_reason: GrayReason | None = None
    gray_detail: GrayDetail | None = None


class BillReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bill_id: str
    hospital_name: str = ""
    bill_date: str = ""
    items: list[VerifiedItem] = Field(default_factory=list)
    normalized: list[NormalizedItem] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    stats: ReadingStats = Field(default_factory=ReadingStats)
    reference_retrieved_on: str = ""

    def flags_for(self, item_index: int) -> list[Flag]:
        return [f for f in self.flags if f.item_index == item_index]

    def severity_of(self, item_index: int) -> Severity:
        """Worst severity wins, but gray never outranks a real verdict."""
        order = [Severity.RED, Severity.AMBER, Severity.GREEN, Severity.GRAY]
        found = {f.severity for f in self.flags_for(item_index)}
        for severity in order:
            if severity in found:
                return severity
        return Severity.GRAY
