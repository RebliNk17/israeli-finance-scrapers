"""Unit tests for shared utilities."""

from __future__ import annotations

import pytest

from israeli_finance_scrapers.utils import currency_from_amount_text, normalize_currency


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "ILS"),
        ("", "ILS"),
        ("₪", "ILS"),
        ('ש"ח', "ILS"),
        ("NIS", "ILS"),
        ("$", "USD"),
        ("€", "EUR"),
        ("£", "GBP"),
        ("¥", "JPY"),
        ("JPY", "JPY"),
        (" jpy ", "JPY"),
        ("THB", "THB"),
        (376, "ILS"),
        (840, "USD"),
        (392, "JPY"),
        ("392", "JPY"),
        (999, "ILS"),  # unknown numeric code: the default, never a guessed currency
        ("???", "ILS"),
    ],
)
def test_normalize_currency(value, expected) -> None:
    assert normalize_currency(value) == expected


def test_normalize_currency_default() -> None:
    assert normalize_currency(None, default=None) is None
    assert normalize_currency(999, default=None) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("¥10,000", "JPY"),
        ("₪195.00", "ILS"),
        ("$12.00", "USD"),
        ("12.50 EUR", "EUR"),
        ("10000", None),
        (10000.0, None),
        (None, None),
    ],
)
def test_currency_from_amount_text(text, expected) -> None:
    assert currency_from_amount_text(text) == expected
