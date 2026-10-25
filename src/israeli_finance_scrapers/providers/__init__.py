"""Provider registry and factory for Israeli finance scrapers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from israeli_finance_scrapers.base.base_scraper import BaseScraper, ScraperOptions
from israeli_finance_scrapers.providers.banks.onezero import OneZeroScraper
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
    "visa_cal": ProviderMetadata(
        key="visa_cal",
        category="credit_card",
        display_name="Visa Cal",
        hebrew_name="ויזה כאל",
        login_fields=("username", "password"),
        supports_otp=False,
        supports_long_term_token=True,
    ),
    "onezero": ProviderMetadata(
        key="onezero",
        category="bank",
        display_name="One Zero",
        hebrew_name="וואן זירו",
        login_fields=("phoneNumber",),
        supports_otp=True,
        supports_long_term_token=True,
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
    "visa_cal": "visa_cal",
    "visacal": "visa_cal",
    "cal": "visa_cal",
    "onezero": "onezero",
    "one_zero": "onezero",
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
    """Create a scraper instance for the given provider key.

    Parameters
    ----------
    provider : str
        Provider identifier (e.g. "visa_cal", "onezero", "haphoenix", "migdal").
    credentials : dict
        Credentials dictionary corresponding to provider login_fields.
    options : ScraperOptions, optional
        Execution options (timeout, proxy, date filters).
    client : httpx.AsyncClient, optional
        Pre-configured async HTTP client.
    """
    canonical = _ALIASES.get((provider or "").strip().lower())
    if canonical == "visa_cal":
        return VisaCalScraper(credentials, options, client=client)
    if canonical == "onezero":
        return OneZeroScraper(credentials, options, client=client)
    if canonical == "haphoenix":
        return HaPhoenixScraper(credentials, options, client=client)
    if canonical == "migdal":
        return MigdalScraper(credentials, options, client=client)

    supported = sorted(PROVIDERS)
    raise ValueError(f"Unknown finance provider: {provider!r}. Supported: {supported}")


__all__ = [
    "PROVIDERS",
    "HaPhoenixScraper",
    "MigdalScraper",
    "OneZeroScraper",
    "ProviderMetadata",
    "VisaCalScraper",
    "create_scraper",
    "encrypt_migdal_pin_token",
]
