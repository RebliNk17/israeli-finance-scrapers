"""Pure HTTP browserless scraper for One Zero Digital Bank (https://www.onezerbank.com).

Uses OneZero's identity server with Cloudflare mTLS client certificate for
device authentication and OTP token minting, and the GraphQL API for fetching
accounts and transaction movements.
"""

from __future__ import annotations

import logging
import os
import re
import ssl
import tempfile
from typing import Any

import httpx

from israeli_finance_scrapers.base.base_scraper import BaseScraper, ScraperOptions
from israeli_finance_scrapers.base.exceptions import (
    FinanceScraperError,
    InvalidCredentialsError,
    InvalidOtpError,
    OtpCanceledError,
)
from israeli_finance_scrapers.models.bank import (
    Account,
    AccountType,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from israeli_finance_scrapers.providers.banks.onezero_certs import (
    ONEZERO_MTLS_CERT,
    ONEZERO_MTLS_KEY,
)

logger = logging.getLogger(__name__)

IDENTITY_SERVER_URL = "https://identity.tfd-bank.com/v1"
GRAPHQL_API_URL = "https://mobile.tfd-bank.com/mobile-graph/graphql"
HEBREW_WORDS_REGEX = re.compile(r"[\u0590-\u05FF][\u0590-\u05FF\"'\-_ /\\]*[\u0590-\u05FF]")

GET_PORTFOLIOS = """query GetPortfolios {
  portfolios {
    __typename
    accountId
    accountType
    closingDate
    currency
    openingDate
    status
    subType
  }
}
"""

GET_MOVEMENTS = """query GetMovements(
  $portfolioId: String!
  $accountId: String!
  $pagination: PaginationInput!
  $language: BffLanguage!
) {
  movements(
    portfolioId: $portfolioId
    accountId: $accountId
    pagination: $pagination
    language: $language
  ) {
    __typename
    movements {
      __typename
      movementId
      movementTimestamp
      valueDate
      movementAmount
      movementCurrency
      description
      creditDebit
      runningBalance
    }
    pagination {
      __typename
      cursor
      hasMore
    }
  }
}
"""


def _normalize_phone(phone: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", phone.strip())
    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("05"):
        return "+972" + cleaned[1:]
    if cleaned.startswith("972"):
        return "+" + cleaned
    return "+972" + cleaned


def _sanitize_hebrew(text: str) -> str:
    if "\u202d" not in text:
        return text.strip()
    plain = text.replace("\u202d", "").strip()
    matches = list(HEBREW_WORDS_REGEX.finditer(plain))
    out: list[str] = []
    idx = 0
    for m in matches:
        out.append(plain[idx : m.start()])
        out.append(plain[m.start() : m.end()][::-1])
        idx = m.end()
    out.append(plain[idx:])
    return "".join(out)


def _build_mtls_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    with (
        tempfile.NamedTemporaryFile("w", delete=False) as cf,
        tempfile.NamedTemporaryFile("w", delete=False) as kf,
    ):
        cf.write(ONEZERO_MTLS_CERT)
        kf.write(ONEZERO_MTLS_KEY)
        cf_path, kf_path = cf.name, kf.name
    try:
        ctx.load_cert_chain(cf_path, kf_path)
    finally:
        os.unlink(cf_path)
        os.unlink(kf_path)
    return ctx


class OneZeroScraper(BaseScraper):
    """Pure HTTP browserless scraper for One Zero Digital Bank."""

    provider_name = "onezero"

    def __init__(
        self,
        credentials: dict[str, Any],
        options: ScraperOptions | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(credentials, options, client=client)
        self._access_token: str | None = None
        self._otp_context: str | None = None

    async def initialize(self) -> None:
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.options.timeout),
                follow_redirects=True,
                verify=_build_mtls_ssl_context(),
                proxy=self.options.proxy,
            )

    async def login(self) -> None:
        """Authenticate using stored long-term idToken or via SMS OTP."""
        assert self.client is not None

        # 1. Check for stored long-term idToken
        id_token = self.credentials.get("otpLongTermToken")
        if id_token:
            token_res = await self.client.post(
                f"{IDENTITY_SERVER_URL}/tokens/accessToken",
                json={"idToken": str(id_token).strip()},
            )
            if token_res.status_code == 200:
                data = token_res.json()
                self._access_token = data.get("resultData", {}).get("accessToken")
                if self._access_token:
                    return

        # 2. Interactive SMS OTP flow
        raw_phone = self.credentials.get("phoneNumber") or self.credentials.get("phone")
        if not raw_phone:
            raise InvalidCredentialsError("Missing 'phoneNumber' in credentials for OneZero")

        phone = _normalize_phone(str(raw_phone))

        # Get device token
        dev_res = await self.client.post(
            f"{IDENTITY_SERVER_URL}/devices/token",
            json={"extClientId": "mobile", "os": "Android"},
        )
        if dev_res.status_code != 200:
            raise FinanceScraperError(f"OneZero device token error: HTTP {dev_res.status_code}")
        device_token = dev_res.json().get("resultData", {}).get("deviceToken")

        # Prepare OTP
        prep_res = await self.client.post(
            f"{IDENTITY_SERVER_URL}/otp/prepare",
            json={
                "factorValue": phone,
                "deviceToken": device_token,
                "otpChannel": "SMS_OTP",
            },
        )
        if prep_res.status_code != 200:
            raise FinanceScraperError(f"OneZero OTP send error: HTTP {prep_res.status_code}")
        self._otp_context = prep_res.json().get("resultData", {}).get("otpContext")

        # Ask caller for OTP
        if not self.on_otp_request:
            raise InvalidOtpError("OneZero requires OTP verification, but no callback was attached")

        code = await self.on_otp_request()
        if not code or code.strip().lower() == "cancel":
            raise OtpCanceledError()

        # Verify OTP
        ver_res = await self.client.post(
            f"{IDENTITY_SERVER_URL}/otp/verify",
            json={"otpContext": self._otp_context, "otpCode": code.strip()},
        )
        if ver_res.status_code != 200:
            raise InvalidOtpError("OneZero rejected the OTP verification code")

        otp_token = ver_res.json().get("resultData", {}).get("otpToken")

        # Mint long-term idToken
        id_res = await self.client.post(
            f"{IDENTITY_SERVER_URL}/tokens/idToken",
            json={"otpToken": otp_token},
        )
        if id_res.status_code != 200:
            raise FinanceScraperError("Failed to mint OneZero idToken")

        minted_id_token = id_res.json().get("resultData", {}).get("idToken")
        self.refreshed_long_term_token = minted_id_token

        # Exchange idToken for access token
        acc_res = await self.client.post(
            f"{IDENTITY_SERVER_URL}/tokens/accessToken",
            json={"idToken": minted_id_token},
        )
        if acc_res.status_code != 200:
            raise FinanceScraperError("Failed to obtain OneZero access token")

        self._access_token = acc_res.json().get("resultData", {}).get("accessToken")

    async def fetch_data(self) -> None:
        """Fetch bank accounts and transactions via GraphQL."""
        assert self.client is not None
        if not self._access_token:
            raise FinanceScraperError("Must login before fetching OneZero data")

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        # 1. Query Portfolios
        port_res = await self.client.post(
            GRAPHQL_API_URL,
            headers=headers,
            json={"query": GET_PORTFOLIOS, "variables": {}},
        )
        if port_res.status_code != 200:
            raise FinanceScraperError(f"Failed to fetch OneZero portfolios: HTTP {port_res.status_code}")

        port_data = port_res.json()
        portfolios = port_data.get("data", {}).get("portfolios") or []

        scraped_accounts: list[Account] = []
        for p in portfolios:
            acc_id = p.get("accountId")
            if not acc_id:
                continue

            # Query movements
            movements = await self._fetch_movements(headers, acc_id)

            # Calculate balance from latest movement runningBalance
            balance = None
            if movements:
                last_m = movements[0].raw_data
                if last_m and last_m.get("runningBalance") is not None:
                    balance = float(last_m["runningBalance"])

            scraped_accounts.append(
                Account(
                    account_number=acc_id,
                    account_type=AccountType.BANK,
                    balance=balance,
                    currency=p.get("currency") or "ILS",
                    txns=movements,
                )
            )

        self.accounts = scraped_accounts

    async def _fetch_movements(self, headers: dict[str, str], acc_id: str) -> list[Transaction]:
        assert self.client is not None
        txns: list[Transaction] = []
        cursor = None
        has_more = True

        while has_more:
            variables = {
                "portfolioId": acc_id,
                "accountId": acc_id,
                "pagination": {"cursor": cursor, "limit": 50},
                "language": "HEBREW",
            }
            res = await self.client.post(
                GRAPHQL_API_URL,
                headers=headers,
                json={"query": GET_MOVEMENTS, "variables": variables},
            )
            if res.status_code != 200:
                break

            data = res.json()
            mov_block = data.get("data", {}).get("movements") or {}
            raw_movements = mov_block.get("movements") or []
            pag = mov_block.get("pagination") or {}

            for m in raw_movements:
                amt = float(m.get("movementAmount") or 0.0)
                if m.get("creditDebit") == "DEBIT":
                    amt = -abs(amt)
                else:
                    amt = abs(amt)

                raw_date = str(m.get("valueDate") or m.get("movementTimestamp") or "")[:10]

                txns.append(
                    Transaction(
                        identifier=str(m.get("movementId") or ""),
                        date=raw_date,
                        processed_date=raw_date,
                        original_amount=amt,
                        original_currency=m.get("movementCurrency") or "ILS",
                        charged_amount=amt,
                        description=_sanitize_hebrew(m.get("description") or ""),
                        status=TransactionStatus.COMPLETED,
                        type=TransactionType.NORMAL,
                        raw_data=m,
                    )
                )

            cursor = pag.get("cursor")
            has_more = bool(pag.get("hasMore") and cursor)

            # Date filter check
            if self.options.start_date and txns:
                start_iso = self.options.start_date[:10]
                if txns[-1].date < start_iso:
                    break

        if self.options.start_date:
            start_iso = self.options.start_date[:10]
            txns = [t for t in txns if t.date >= start_iso]

        return txns
