"""Shared parsing and normalization utilities across pension providers."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_PAREN_SUFFIX_RE = re.compile(r"\s*\(([^()]+)\)\s*$")
_DIGITS_ONLY_RE = re.compile(r"\D+")


def split_policy_id(raw_policy_id: str) -> tuple[str, str | None]:
    """Split a display policy ID like ``'001-234-567890 (01234567)'`` into
    ``(normalized_policy_id, internal_account_id)``.

    HaPhoenix and several other Israeli providers display a parenthesized internal
    account number whose zero-padding can change over time. Stripping the parenthesized
    suffix produces a stable ``policy_id`` while preserving ``internal_account_id``.
    """
    text = (raw_policy_id or "").strip()
    match = _PAREN_SUFFIX_RE.search(text)
    if not match:
        return text, None
    base = text[: match.start()].strip()
    internal = match.group(1).strip()
    return (base or text), (internal or None)


def policy_id_key(raw_policy_id: str) -> str:
    """Return a reformat-insensitive key for deduplicating deposit identifiers."""
    base, _ = split_policy_id(raw_policy_id)
    return base.replace(" ", "")


def normalize_israeli_id(id_number: str) -> str:
    """Zero-pad an Israeli ID number to 9 digits."""
    digits = _DIGITS_ONLY_RE.sub("", str(id_number or ""))
    if not digits:
        raise ValueError("ID number must contain digits")
    return digits.zfill(9)


def normalize_israeli_phone(phone: str) -> str:
    """Normalize an Israeli mobile number to local 10-digit ``05XXXXXXXX`` format."""
    digits = _DIGITS_ONLY_RE.sub("", str(phone or ""))
    if digits.startswith("972") and len(digits) == 12:
        digits = "0" + digits[3:]
    elif len(digits) == 9 and digits.startswith("5"):
        digits = "0" + digits
    return digits


def extract_number(val: Any, default: float | None = 0.0) -> float | None:
    """Extract a float from a plain number, percentage string, or ``{'value': x}`` dict."""
    if val is None or val == "":
        return default
    if isinstance(val, dict):
        if "percentageData" in val and isinstance(val["percentageData"], dict):
            raw = val["percentageData"].get("value")
        else:
            raw = val.get("value")
    else:
        raw = val
    if raw is None or raw == "":
        return default
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        cleaned = (
            raw.replace("%", "")
            .replace("₪", "")
            .replace('ש"ח', "")
            .replace("ש''ח", "")
            .replace("שח", "")
            .replace(",", "")
            .strip()
        )
        if not cleaned:
            return default
        try:
            return float(cleaned)
        except ValueError:
            m = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
            if m:
                return float(m.group(0))
            return default
    return default


def parse_il_date(value: str | None) -> str | None:
    """Parse common Israeli provider date formats into ISO ``YYYY-MM-DD``.

    Supports:
    - ``YYYY-MM-DD`` or ISO timestamps ``YYYY-MM-DDTHH:MM:SS...``
    - ``DD.MM.YYYY`` (e.g. ``20.10.2026``)
    - ``DD.MM.YY`` (e.g. ``06.09.26``)
    - ``DD/MM/YYYY``
    - ``MM.YYYY`` or ``MM/YYYY`` -> ``YYYY-MM-01``
    - Embedded date inside Hebrew text (e.g. ``החל מ31.01.2031``)
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.startswith("0001-"):
        return None

    # ISO timestamp or date
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]

    # Exact DD.MM.YYYY or DD/MM/YYYY
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d.%m.%y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # MM.YYYY or MM/YYYY (used in monthly accumulation graphs)
    m_month = re.match(r"^(\d{2})[./](\d{4})$", text)
    if m_month:
        month, year = m_month.groups()
        return f"{year}-{month}-01"

    # Embedded DD.MM.YYYY or DD/MM/YYYY in Hebrew text
    m_embedded = re.search(r"(\d{2})[./](\d{2})[./](\d{4})", text)
    if m_embedded:
        day, month, year = m_embedded.groups()
        return f"{year}-{month}-{day}"

    return None


def parse_salary_month(value: str | None) -> str | None:
    """Normalize a salary month like ``'08/2026'`` or ``'2026-08'`` to ``'YYYY-MM'``."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    m = re.match(r"^(\d{2})[./-](\d{4})$", text)
    if m:
        month, year = m.groups()
        return f"{year}-{month}"
    m_iso = re.match(r"^(\d{4})-(\d{2})", text)
    if m_iso:
        year, month = m_iso.groups()
        return f"{year}-{month}"
    return None


# Currency symbols and local spellings the card APIs send instead of an ISO 4217 code.
_CURRENCY_BY_SYMBOL = {
    "₪": "ILS",
    'ש"ח': "ILS",
    "ש״ח": "ILS",
    "שח": "ILS",
    "NIS": "ILS",
    "$": "USD",
    "US$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "JP¥": "JPY",
    "CN¥": "CNY",
    "₩": "KRW",
    "₹": "INR",
    "₺": "TRY",
    "₽": "RUB",
    "฿": "THB",
    "₫": "VND",
    "zł": "PLN",
    "Kč": "CZK",
    "Fr.": "CHF",
}

# ISO 4217 numeric codes (Max sends PaymentCurrency as a number).
_CURRENCY_BY_NUMERIC = {
    36: "AUD", 124: "CAD", 156: "CNY", 203: "CZK", 208: "DKK", 344: "HKD", 348: "HUF",
    352: "ISK", 356: "INR", 360: "IDR", 376: "ILS", 392: "JPY", 400: "JOD", 410: "KRW",
    458: "MYR", 484: "MXN", 554: "NZD", 578: "NOK", 608: "PHP", 643: "RUB", 702: "SGD",
    704: "VND", 710: "ZAR", 752: "SEK", 756: "CHF", 764: "THB", 784: "AED", 818: "EGP",
    826: "GBP", 840: "USD", 941: "RSD", 946: "RON", 949: "TRY", 975: "BGN", 978: "EUR",
    981: "GEL", 985: "PLN", 986: "BRL",
}  # fmt: skip


def normalize_currency(value: Any, default: str | None = "ILS") -> str | None:
    """Return the ISO 4217 code for a currency symbol, alphabetic code or numeric code.

    Empty values give ``default``. An unrecognised symbol or number also gives ``default``
    rather than being reported as a currency it might not be; an unrecognised three-letter
    code is returned as is (upper-cased).
    """
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _CURRENCY_BY_NUMERIC.get(int(value), default)
    text = str(value).strip()
    if not text:
        return default
    if text.isdigit():
        return _CURRENCY_BY_NUMERIC.get(int(text), default)
    if text in _CURRENCY_BY_SYMBOL:
        return _CURRENCY_BY_SYMBOL[text]
    if re.fullmatch(r"[A-Za-z]{3}", text):
        return text.upper()
    return default


def currency_from_amount_text(text: Any) -> str | None:
    """Return the currency marked on an amount string such as ``'¥10,000'`` or ``'12.5 USD'``."""
    if not isinstance(text, str):
        return None
    marker = re.sub(r"[\d.,\s+\-]", "", text)
    return normalize_currency(marker, default=None) if marker else None
