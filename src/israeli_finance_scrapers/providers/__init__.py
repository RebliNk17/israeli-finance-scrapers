"""Provider registry and factory for Israeli finance scrapers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from israeli_finance_scrapers.base.base_scraper import BaseScraper, ScraperOptions
from israeli_finance_scrapers.providers.banks.onezero import OneZeroScraper
from israeli_finance_scrapers.providers.banks.pepper import PepperScraper
from israeli_finance_scrapers.providers.cards.isracard_amex import (
    AmexScraper,
    IsracardScraper,
)
from israeli_finance_scrapers.providers.cards.max import MaxScraper
from israeli_finance_scrapers.providers.cards.visa_cal import VisaCalScraper
from israeli_finance_scrapers.providers.pensions.haphoenix import HaPhoenixScraper
from israeli_finance_scrapers.providers.pensions.migdal import (
    MigdalScraper,
    encrypt_migdal_pin_token,
)


@dataclass(frozen=True)
class ProviderMetadata:
    key: str
    category: str  # "bank" | "credit_card" | "pension"
    display_name: str
    hebrew_name: str
    login_fields: tuple[str, ...]
    supports_otp: bool = False
    supports_long_term_token: bool = True


PROVIDERS: dict[str, ProviderMetadata] = {
    "onezero": ProviderMetadata(
        key="onezero",
        category="bank",
        display_name="One Zero",
        hebrew_name="וואן זירו",
        login_fields=("email", "password", "phoneNumber"),
        supports_otp=True,
        supports_long_term_token=True,
    ),
    "pepper": ProviderMetadata(
        key="pepper",
        category="bank",
        display_name="Pepper",
        hebrew_name="פפר",
        login_fields=("phoneNumber", "password"),
        supports_otp=True,
        supports_long_term_token=True,
    ),
    "visa_cal": ProviderMetadata(
        key="visa_cal",
        category="credit_card",
        display_name="Visa Cal",
        hebrew_name="ויזה כאל",
        login_fields=("username", "password"),
        supports_otp=False,
        supports_long_term_token=True,
    ),
    "max": ProviderMetadata(
        key="max",
        category="credit_card",
        display_name="Max",
        hebrew_name="מקס",
        login_fields=("username", "password"),
        supports_otp=True,
        supports_long_term_token=True,
    ),
    "isracard": ProviderMetadata(
        key="isracard",
        category="credit_card",
        display_name="Isracard",
        hebrew_name="ישראכרט",
        login_fields=("id", "card6Digits", "password"),
        supports_otp=False,
        supports_long_term_token=False,
    ),
    "amex": ProviderMetadata(
        key="amex",
        category="credit_card",
        display_name="American Express",
        hebrew_name="אמריקן אקספרס",
        login_fields=("id", "card6Digits", "password"),
        supports_otp=False,
        supports_long_term_token=False,
    ),
    "haphoenix": ProviderMetadata(
        key="haphoenix",
        category="pension",
        display_name="HaPhoenix",
        hebrew_name="הפניקס",
        login_fields=("id", "phoneNumber"),
        supports_otp=True,
        supports_long_term_token=True,
    ),
    "migdal": ProviderMetadata(
        key="migdal",
        category="pension",
        display_name="Migdal",
        hebrew_name="מגדל",
        login_fields=("id", "phoneNumber"),
        supports_otp=True,
        supports_long_term_token=True,
    ),
}

_ALIASES: dict[str, str] = {
    "onezero": "onezero",
    "one_zero": "onezero",
    "pepper": "pepper",
    "visa_cal": "visa_cal",
    "visacal": "visa_cal",
    "visa cal": "visa_cal",
    "cal": "visa_cal",
    "max": "max",
    "leumicard": "max",
    "isracard": "isracard",
    "amex": "amex",
    "americanexpress": "amex",
    "haphoenix": "haphoenix",
    "hafenix": "haphoenix",
    "phoenix": "haphoenix",
    "fnx": "haphoenix",
    "migdal": "migdal",
}


def create_scraper(
    provider: str,
    credentials: dict[str, Any],
    options: ScraperOptions | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> BaseScraper:
    """Create a scraper instance for the given provider key."""
    canonical = _ALIASES.get((provider or "").strip().lower())
    if canonical == "onezero":
        return OneZeroScraper(credentials, options, client=client)
    if canonical == "pepper":
        return PepperScraper(credentials, options, client=client)
    if canonical == "visa_cal":
        return VisaCalScraper(credentials, options, client=client)
    if canonical == "max":
        return MaxScraper(credentials, options, client=client)
    if canonical == "isracard":
        return IsracardScraper(credentials, options, client=client)
    if canonical == "amex":
        return AmexScraper(credentials, options, client=client)
    if canonical == "haphoenix":
        return HaPhoenixScraper(credentials, options, client=client)
    if canonical == "migdal":
        return MigdalScraper(credentials, options, client=client)

    supported = sorted(PROVIDERS)
    raise ValueError(f"Unknown finance provider: {provider!r}. Supported: {supported}")


__all__ = [
    "PROVIDERS",
    "AmexScraper",
    "HaPhoenixScraper",
    "IsracardScraper",
    "MaxScraper",
    "MigdalScraper",
    "OneZeroScraper",
    "PepperScraper",
    "ProviderMetadata",
    "VisaCalScraper",
    "create_scraper",
    "encrypt_migdal_pin_token",
]
