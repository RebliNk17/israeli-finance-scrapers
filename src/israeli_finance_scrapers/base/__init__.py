"""Base classes and exceptions for Israeli finance scrapers."""

from israeli_finance_scrapers.base.base_scraper import (
    OTP_CANCEL_SENTINEL,
    BaseScraper,
    ScraperOptions,
)
from israeli_finance_scrapers.base.exceptions import (
    AccountBlockedError,
    FinanceScraperError,
    InvalidCredentialsError,
    InvalidOtpError,
    OtpCanceledError,
    ScraperErrorType,
    TokenExpiredError,
)

__all__ = [
    "OTP_CANCEL_SENTINEL",
    "AccountBlockedError",
    "BaseScraper",
    "FinanceScraperError",
    "InvalidCredentialsError",
    "InvalidOtpError",
    "OtpCanceledError",
    "ScraperErrorType",
    "ScraperOptions",
    "TokenExpiredError",
]
