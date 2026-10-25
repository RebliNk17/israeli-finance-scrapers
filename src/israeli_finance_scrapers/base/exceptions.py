"""Custom exceptions for Israeli finance scrapers."""

from __future__ import annotations

from enum import StrEnum


class ScraperErrorType(StrEnum):
    INIT_ERROR = "INIT_ERROR"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INVALID_OTP = "INVALID_OTP"
    OTP_CANCELED = "OTP_CANCELED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    CHANGE_PASSWORD = "CHANGE_PASSWORD"
    ACCOUNT_BLOCKED = "ACCOUNT_BLOCKED"
    NETWORK_ERROR = "NETWORK_ERROR"
    PARSING_ERROR = "PARSING_ERROR"
    GENERAL_ERROR = "GENERAL_ERROR"


class FinanceScraperError(Exception):
    """Base exception for scraping failures."""

    def __init__(
        self,
        message: str,
        error_type: ScraperErrorType = ScraperErrorType.GENERAL_ERROR,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_type = error_type


class InvalidCredentialsError(FinanceScraperError):
    def __init__(self, message: str = "Invalid username or password") -> None:
        super().__init__(message, error_type=ScraperErrorType.INVALID_CREDENTIALS)


class InvalidOtpError(FinanceScraperError):
    def __init__(self, message: str = "Invalid or expired OTP code") -> None:
        super().__init__(message, error_type=ScraperErrorType.INVALID_OTP)


class OtpCanceledError(FinanceScraperError):
    def __init__(self, message: str = "OTP verification canceled by user") -> None:
        super().__init__(message, error_type=ScraperErrorType.OTP_CANCELED)


class TokenExpiredError(FinanceScraperError):
    def __init__(self, message: str = "Long term session token expired") -> None:
        super().__init__(message, error_type=ScraperErrorType.TOKEN_EXPIRED)


class AccountBlockedError(FinanceScraperError):
    def __init__(self, message: str = "Account temporarily locked or blocked") -> None:
        super().__init__(message, error_type=ScraperErrorType.ACCOUNT_BLOCKED)
