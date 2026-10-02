"""Naira-specific number-to-words conversion for cash receipt PDFs.

Renders an amount (e.g. Decimal("1590500.00")) as the spelled-out words a
physical cash receipt carries — "ONE MILLION FIVE HUNDRED AND NINETY
THOUSAND FIVE HUNDRED NAIRA ONLY" — matching the "Being payment of..." /
amount-in-words line on the paper form. Derived at render time; never
stored (amounts already live on `payment_record.amount_ngn`).
"""

from decimal import ROUND_HALF_UP, Decimal

_ONES = (
    "",
    "ONE",
    "TWO",
    "THREE",
    "FOUR",
    "FIVE",
    "SIX",
    "SEVEN",
    "EIGHT",
    "NINE",
    "TEN",
    "ELEVEN",
    "TWELVE",
    "THIRTEEN",
    "FOURTEEN",
    "FIFTEEN",
    "SIXTEEN",
    "SEVENTEEN",
    "EIGHTEEN",
    "NINETEEN",
)
_TENS = (
    "",
    "",
    "TWENTY",
    "THIRTY",
    "FORTY",
    "FIFTY",
    "SIXTY",
    "SEVENTY",
    "EIGHTY",
    "NINETY",
)
_SCALES = (
    (1_000_000_000, "BILLION"),
    (1_000_000, "MILLION"),
    (1_000, "THOUSAND"),
)


def _under_thousand_to_words(n: int) -> str:
    """Spell out an integer in [0, 999]."""
    if n == 0:
        return ""
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens_word = _TENS[n // 10]
        remainder = n % 10
        return f"{tens_word}-{_ONES[remainder]}" if remainder else tens_word
    hundreds_word = f"{_ONES[n // 100]} HUNDRED"
    remainder = n % 100
    return f"{hundreds_word} AND {_under_thousand_to_words(remainder)}" if remainder else hundreds_word


def _integer_to_words(n: int) -> str:
    """Spell out a non-negative integer using standard short-scale groupings."""
    if n == 0:
        return "ZERO"

    parts: list[str] = []
    remaining = n
    for scale_value, scale_name in _SCALES:
        if remaining >= scale_value:
            count, remaining = divmod(remaining, scale_value)
            parts.append(f"{_under_thousand_to_words(count)} {scale_name}")
    if remaining:
        parts.append(_under_thousand_to_words(remaining))
    return " ".join(parts)


def naira_amount_to_words(amount_ngn: Decimal | str | float) -> str:
    """Render an NGN amount as receipt-style words, e.g. "ONE MILLION FIVE
    HUNDRED AND NINETY THOUSAND FIVE HUNDRED NAIRA ONLY".

    Kobo (the fractional part) is rounded to the nearest whole Naira for the
    words line — the numeric amount printed alongside it retains full
    precision; only the spelled-out words are rounded, matching how the
    paper receipts are filled in by hand.
    """
    value = Decimal(str(amount_ngn)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    naira = abs(int(value))
    words = _integer_to_words(naira)
    return f"{words} NAIRA ONLY"
