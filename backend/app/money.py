"""Rupee formatting. Indian digit grouping, not Western.

12,94,761 -- not 12,947,61 and not 12,947,610. The last three digits group
together, then every two after that. Getting this wrong on an Indian bill is
the kind of detail that tells a user the tool was not built for them.

Evidence dictionaries always keep RAW decimal strings. Formatting is a
presentation concern and never enters the data that rules reason about.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

RUPEE = "\u20b9"


def group_indian(digits: str) -> str:
    """"1234567" -> "12,34,567"."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join([*parts, tail])


def format_inr(value: Decimal | str | int | float, symbol: str = RUPEE) -> str:
    """Format as Indian currency: Rs 12,947.61.

    `symbol` is a parameter because the CLI prints to a Windows console where
    the rupee sign raises UnicodeEncodeError under the default codec. The UI
    and the letter use the real symbol; the CLI passes "Rs ".
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)

    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    whole, _, fraction = f"{amount:.2f}".partition(".")
    return f"{sign}{symbol}{group_indian(whole)}.{fraction}"
