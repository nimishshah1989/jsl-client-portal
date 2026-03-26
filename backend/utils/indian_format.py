"""Indian number formatting utilities for INR currency and percentages."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# Thresholds for short-form formatting
_CRORE = Decimal("10000000")   # 1,00,00,000
_LAKH = Decimal("100000")      # 1,00,000


def _indian_grouping(integer_part: str) -> str:
    """
    Apply Indian numbering system grouping to an integer string.
    First group of 3 digits from right, then groups of 2.
    Example: 12345678 -> 1,23,45,678
    """
    if len(integer_part) <= 3:
        return integer_part

    # Last 3 digits
    last_three = integer_part[-3:]
    remaining = integer_part[:-3]

    # Group remaining in pairs from right
    groups: list[str] = []
    while len(remaining) > 2:
        groups.append(remaining[-2:])
        remaining = remaining[:-2]
    if remaining:
        groups.append(remaining)

    groups.reverse()
    return ",".join(groups) + "," + last_three


def format_inr(amount: Decimal) -> str:
    """
    Format a Decimal amount as Indian Rupees with full precision.

    Examples:
        Decimal("123456")    -> "₹1,23,456"
        Decimal("12345678")  -> "₹1,23,45,678"
        Decimal("-50000.50") -> "-₹50,000.50"
        Decimal("999.99")    -> "₹999.99"
    """
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))

    # Handle negative
    negative = amount < 0
    abs_amount = abs(amount)

    # Round to 2 decimal places
    rounded = abs_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    int_part, _, dec_part = str(rounded).partition(".")

    formatted_int = _indian_grouping(int_part)

    if dec_part and dec_part != "00":
        result = f"₹{formatted_int}.{dec_part}"
    else:
        result = f"₹{formatted_int}"

    return f"-{result}" if negative else result


def format_inr_short(amount: Decimal) -> str:
    """
    Format a Decimal amount as abbreviated Indian Rupees.

    Examples:
        Decimal("6745000000") -> "₹674.50 Cr"
        Decimal("4850000")    -> "₹48.50L"
        Decimal("99999")      -> "₹99,999"
        Decimal("-25000000")  -> "-₹2.50 Cr"
    """
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))

    negative = amount < 0
    abs_amount = abs(amount)
    prefix = "-" if negative else ""

    if abs_amount >= _CRORE:
        crores = abs_amount / _CRORE
        rounded = crores.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{prefix}₹{rounded} Cr"

    if abs_amount >= _LAKH:
        lakhs = abs_amount / _LAKH
        rounded = lakhs.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{prefix}₹{rounded}L"

    return f"{prefix}{format_inr(abs_amount)}"


def format_pct(value: Decimal | float) -> str:
    """
    Format a percentage value with explicit +/- prefix.

    Examples:
        35.64   -> "+35.64%"
        -12.07  -> "-12.07%"
        0.0     -> "0.00%"
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value))

    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if rounded > 0:
        return f"+{rounded}%"
    if rounded < 0:
        return f"{rounded}%"
    return "0.00%"
