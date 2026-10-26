"""Base async scraper for all Israeli financial institutions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from israeli_finance_scrapers.base.exceptions import (
    FinanceScraperError,
    InvalidCredentialsError,
    InvalidOtpError,
    OtpCanceledError,
    ScraperErrorType,
)
from israeli_finance_scrapers.models.bank import Account
from israeli_finance_scrapers.models.pension import FundPolicy, InsuredProfile, PortfolioSummary
from israeli_finance_scrapers.models.result import ScrapingResult

OTP_CANCEL_SENTINEL = "cancel"


@dataclass
class ScraperOptions:
    """Runtime options for scraper execution."""

    start_date: str | None = None  # YYYY-MM-DD
    timeout: float = 30.0
    proxy: str | None = None
    combine_installments: bool = False
    include_balance_history: bool = True
    include_policy_details: bool = True
    otp_code_resolver: Callable[[], Awaitable[str]] | None = None


class BaseScraper(ABC):
    """Abstract base class for pure HTTP async Israeli finance scrapers."""

    provider_name: str = "unknown"

    def __init__(
        self,
        credentials: dict[str, Any],
        options: ScraperOptions | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.credentials = dict(credentials)
        self.options = options or ScraperOptions()
        self._external_client = client is not None
        self.client: httpx.AsyncClient | None = client
        self.on_progress: Callable[[str], None] | None = None
        self.on_otp_request: Callable[[], Awaitable[str]] | None = None
        self.refreshed_long_term_token: str | None = None

        self.accounts: list[Account] = []
        self.funds: list[FundPolicy] = []
        self.portfolio_summary: PortfolioSummary | None = None
        self.insured: InsuredProfile | None = None
        self._login_error_detail: str | None = None

    def _fail_login(self, reason: Any, detail: str | Exception) -> None:
        self._login_error_detail = str(detail)
        reason_str = str(reason).lower()
        detail_str = str(detail).lower()
        if "otp" in reason_str or "otp" in detail_str:
            raise InvalidOtpError(str(detail))
        raise InvalidCredentialsError(str(detail))

    def _emit_progress(self, stage: str) -> None:
        if self.on_progress is not None:
            self.on_progress(stage)

    async def _resolve_otp_code(self) -> str:
        """Resolve an SMS/Email OTP code from credentials, options, or on_otp_request."""
        import inspect

        raw_code = self.credentials.get("otpCode")
        if raw_code:
            code = str(raw_code).strip()
        else:
            resolver = (
                self.on_otp_request
                or self.options.otp_code_resolver
                or self.credentials.get("otpCodeRetriever")
            )
            if resolver is None or not callable(resolver):
                raise FinanceScraperError(
                    f"{self.provider_name} requires an OTP code, but no OTP resolver was provided"
                )
            res = resolver()
            if inspect.isawaitable(res):
                res = await res
            code = str(res or "").strip()

        if not code or code == OTP_CANCEL_SENTINEL:
            raise OtpCanceledError()
        return code

    async def initialize(self) -> None:
        """Create the async HTTP client if one was not injected."""
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.options.timeout),
                follow_redirects=True,
                proxy=self.options.proxy,
            )

    async def terminate(self) -> None:
        """Close the HTTP client unless it was injected externally."""
        if self.client is not None and not self._external_client:
            await self.client.aclose()
            self.client = None

    @abstractmethod
    async def login(self) -> None:
        """Authenticate against the provider."""

    @abstractmethod
    async def fetch_data(self) -> None:
        """Fetch all accounts, transactions, or pension policies."""

    async def scrape(self) -> ScrapingResult:
        """Execute the full initialize -> login -> fetch_data -> terminate lifecycle."""
        self._emit_progress("initializing")
        try:
            await self.initialize()
        except Exception as exc:  # noqa: BLE001
            return ScrapingResult(
                success=False,
                provider=self.provider_name,
                error_type=ScraperErrorType.INIT_ERROR.value,
                error_message=f"{type(exc).__name__}: {exc}",
            )

        try:
            self._emit_progress("logging_in")
            await self.login()
            self._emit_progress("login_success")

            self._emit_progress("fetching_data")
            result_data = await self.fetch_data()
            if isinstance(result_data, list) and result_data:
                if isinstance(result_data[0], FundPolicy):
                    self.funds = result_data
                elif isinstance(result_data[0], Account):
                    self.accounts = result_data
            self._emit_progress("completed")

            return ScrapingResult(
                success=True,
                provider=self.provider_name,
                accounts=self.accounts,
                funds=self.funds,
                portfolio_summary=self.portfolio_summary,
                insured=self.insured,
                long_term_token=self.refreshed_long_term_token,
            )
        except OtpCanceledError:
            return ScrapingResult(
                success=False,
                provider=self.provider_name,
                error_type=ScraperErrorType.OTP_CANCELED.value,
                error_message="OTP verification was canceled",
            )
        except FinanceScraperError as exc:
            return ScrapingResult(
                success=False,
                provider=self.provider_name,
                error_type=exc.error_type.value,
                error_message=exc.message,
            )
        except httpx.HTTPError as exc:
            return ScrapingResult(
                success=False,
                provider=self.provider_name,
                error_type=ScraperErrorType.NETWORK_ERROR.value,
                error_message=f"HTTP Error: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return ScrapingResult(
                success=False,
                provider=self.provider_name,
                error_type=ScraperErrorType.GENERAL_ERROR.value,
                error_message=f"{type(exc).__name__}: {exc}",
            )
        finally:
            self._emit_progress("terminating")
            await self.terminate()
