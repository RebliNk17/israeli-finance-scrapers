"""Pure HTTP browserless scrapers for Isracard and American Express Israel.

Reverse-engineered from `com.isracard.hatavot` (v10.0.1) and `com.americanexpress.android` (v9.0.71)
against `https://ring.isracard.co.il` and `https://ring.americanexpress.co.il`.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from israeli_finance_scrapers.base.base_scraper import BaseScraper
from israeli_finance_scrapers.base.exceptions import (
    AccountBlockedError,
    FinanceScraperError,
    InvalidCredentialsError,
)
from israeli_finance_scrapers.models.bank import (
    Account,
    AccountType,
    InstallmentsInfo,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from israeli_finance_scrapers.utils import extract_number, normalize_israeli_id, parse_il_date

MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 11; Pixel 3 Build/RQ1A.210105.003; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/83.0.4103.120 "
    "Mobile Safari/537.36"
)

_CURRENCY_MAP = {
    "₪": "ILS",
    'ש"ח': "ILS",
    "NIS": "ILS",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
}


def _normalize_currency(sym: str | None) -> str:
    if not sym:
        return "ILS"
    cleaned = sym.strip()
    return _CURRENCY_MAP.get(cleaned, cleaned)


class BaseIsracardAmexScraper(BaseScraper):
    """Shared pure-HTTP mobile scraper for Isracard and Amex Israel."""

    ring_base_url: str = "https://ring.isracard.co.il"
    application_id: str = "mi"
    isr_domain: str = "isracard"
    company_code: int = 11

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._bc_key: str = str(uuid.uuid4())
        self._logged_in: bool = False

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json; charset=utf-8",
            "Content-Type": "application/json",
            "isrdomain": self.isr_domain,
            "Accept-Language": "en",
            "platform": "mobile",
            "BCKey": self._bc_key,
            "TraceIdentifier": str(uuid.uuid4()),
            "User-Agent": MOBILE_USER_AGENT,
        }

    async def _post_service(self, service_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.client is not None
        url = f"{self.ring_base_url}/service?serviceName={service_name}&applicationId={self.application_id}"
        resp = await self.client.post(url, headers=self._headers(), json=payload)
        if resp.status_code >= 400:
            raise FinanceScraperError(
                f"{self.provider_name} {service_name} failed with HTTP {resp.status_code}"
            )
        return resp.json()

    async def _post_gateway_v2(self, service_url: str, data: dict[str, Any]) -> dict[str, Any]:
        assert self.client is not None
        url = f"{self.ring_base_url}/GatewayV2"
        resp = await self.client.post(
            url,
            headers=self._headers(),
            json={"serviceUrl": service_url, "Data": data},
        )
        if resp.status_code >= 400:
            raise FinanceScraperError(
                f"{self.provider_name} GatewayV2 ({service_url}) failed with HTTP {resp.status_code}"
            )
        return resp.json()

    async def login(self) -> None:
        """Authenticate via ValidateIdDataNoReg -> performNewLogon."""
        if self.client is None:
            await self.initialize()

        raw_id = self.credentials.get("id")
        card6 = self.credentials.get("card6Digits")
        password = self.credentials.get("password")
        if not raw_id or not card6 or not password:
            raise InvalidCredentialsError(
                f"'id', 'card6Digits', and 'password' are required for {self.provider_name}"
            )

        id_num = normalize_israeli_id(str(raw_id))
        card_suffix = str(card6).strip()

        val_resp = await self._post_service(
            "ValidateIdDataNoReg",
            {
                "id": id_num,
                "idType": "1",
                "cardSuffix": card_suffix,
                "countryCode": "212",
                "companyCode": str(self.company_code),
                "checkLevel": "1",
                "returnMessage": "true",
                "reqName": "ValidateIdDataNoReg",
                "loginTypeId": "1",
            },
        )
        val_bean = val_resp.get("ValidateIdDataNoRegBean") or {}
        ret_code = str(val_bean.get("returnCode") or "")
        if ret_code == "4":
            raise AccountBlockedError("Account is blocked")
        if ret_code != "1":
            raise InvalidCredentialsError(
                str(val_bean.get("message") or "Invalid ID or card6Digits")
            )

        if val_bean.get("bcKey"):
            self._bc_key = str(val_bean["bcKey"])
        user_name = str(val_bean.get("userName") or "")

        logon_resp = await self._post_service(
            "performNewLogon",
            {
                "MisparZihuy": id_num,
                "KodMishtamesh": user_name,
                "Sisma": str(password),
                "KodZihuy": "1",
                "KodEretz": "212",
                "returnMessage": "true",
                "ap": "MisparZihuy",
                "reqName": "performNewLogon",
                "bcKey": self._bc_key,
            },
        )
        header = logon_resp.get("Header") or {}
        status = str(header.get("Status") or "")
        if status in ("-2", "-4"):
            raise AccountBlockedError(str(header.get("Message") or "Account blocked"))
        if status != "1":
            raise InvalidCredentialsError(str(header.get("Message") or "Invalid password"))

        self._logged_in = True

    async def fetch_data(self) -> None:
        """Fetch all cards and monthly completed & pending transactions."""
        if not self._logged_in:
            raise FinanceScraperError(f"Must login before fetching {self.provider_name} data")

        cards_resp = await self._post_service(
            "CardsList_102Digital",
            {"walletId": "216", "reqName": "CardsList_102Digital"},
        )
        raw_cards = (cards_resp.get("CardsList_102DigitalBean") or {}).get("Table1") or []

        # Fetch credit limits & balances per card via RikuzNetuneyCreditDigi
        limits_by_tail: dict[str, tuple[float | None, float | None, float | None]] = {}
        with contextlib.suppress(Exception):
            rikuz_resp = await self._post_service(
                "RikuzNetuneyCreditDigi",
                {"stage": 0, "reqName": "RikuzNetuneyCreditDigi"},
            )
            cards_total = (rikuz_resp.get("RikuzNetuneyCreditDigiBean") or {}).get(
                "cardsTotal"
            ) or []
            for ct in cards_total:
                if not isinstance(ct, dict):
                    continue
                tail = str(ct.get("cardNumberTail") or "").strip()
                if not tail:
                    continue
                limit = extract_number(ct.get("misgeretKolelet"), None)
                used = extract_number(ct.get("usedBalanceCredit"), None)
                otb = extract_number(ct.get("yitraLeNitzul"), None)
                bal = -used if used is not None else None
                limits_by_tail[tail] = (bal, limit, otb)

        now = datetime.now(UTC)
        start_dt = (
            datetime.strptime(self.options.start_date, "%Y-%m-%d").replace(tzinfo=UTC)
            if self.options.start_date
            else datetime(now.year - 1, now.month, 1, tzinfo=UTC)
        )

        # Build list of (year, month, is_next_billing) from start_dt through now + 1 month
        months_to_query: list[tuple[int, int, bool]] = []
        cur_y, cur_m = start_dt.year, start_dt.month
        end_m = now.month + 1
        end_y = now.year + (1 if end_m > 12 else 0)
        if end_m > 12:
            end_m -= 12
        while (cur_y, cur_m) <= (end_y, end_m):
            is_next = (cur_y, cur_m) >= (now.year, now.month)
            months_to_query.append((cur_y, cur_m, is_next))
            cur_m += 1
            if cur_m > 12:
                cur_m = 1
                cur_y += 1

        accounts: list[Account] = []
        for card in raw_cards:
            card_num = str(card.get("cardNumber") or "").strip()
            if not card_num:
                continue
            pay_day = str(card.get("paymentDate") or "10").strip().zfill(2)
            is_cancelled = str(card.get("activateInd") or "1") == "0"

            txns: list[Transaction] = []
            seen_vouchers: set[tuple[str | None, str, float]] = set()
            seen_approvals: set[tuple[str | None, str, float]] = set()

            for y, m, is_next in months_to_query:
                billing_month = f"{pay_day}/{m:02d}/{y}"
                gw_resp = await self._post_gateway_v2(
                    "11/v3-transactions/v1.1.0/GetTransactionsList",
                    {
                        "card4Number": card_num,
                        "cardStatus": 1 if is_cancelled else 0,
                        "companyCode": self.company_code,
                        "billingMonth": billing_month,
                        "isPartner": False,
                        "isNextBillingDate": is_next,
                    },
                )
                gw_data = gw_resp.get("data") or {}
                processed_iso = f"{y:04d}-{m:02d}-{pay_day}"

                # Pending approvals (only include once)
                approvals = (gw_data.get("approvals") or {}).get("approvedTransactions") or []
                for app_item in approvals:
                    if not isinstance(app_item, dict):
                        continue
                    t = self._map_approval(app_item, processed_iso)
                    if t is None:
                        continue
                    if self.options.start_date and t.date < self.options.start_date:
                        continue
                    key = (t.identifier, t.date, t.charged_amount)
                    if key not in seen_approvals:
                        seen_approvals.add(key)
                        txns.append(t)

                # Completed vouchers
                vouchers = ((gw_data.get("israelAbroadVouchers") or {}).get("vouchers") or {}).get(
                    "israelAbroadVouchersList"
                ) or []
                for v_item in vouchers:
                    if not isinstance(v_item, dict):
                        continue
                    t = self._map_voucher(v_item, processed_iso)
                    if t is None:
                        continue
                    effective_dt = t.processed_date if t.installments else t.date
                    if (
                        self.options.start_date
                        and (effective_dt or t.date) < self.options.start_date
                    ):
                        continue
                    key = (t.identifier, t.date, t.charged_amount)
                    if key not in seen_vouchers:
                        seen_vouchers.add(key)
                        txns.append(t)

            bal, limit, otb = limits_by_tail.get(card_num, (None, None, None))
            accounts.append(
                Account(
                    account_number=card_num,
                    account_type=AccountType.CREDIT_CARD,
                    balance=bal,
                    credit_limit=limit,
                    open_to_buy=otb,
                    currency="ILS",
                    txns=txns,
                )
            )

        self.accounts = accounts

    @staticmethod
    def _map_approval(raw: dict[str, Any], processed_iso: str) -> Transaction | None:
        pdate = parse_il_date(raw.get("purchaseDate"))
        if not pdate:
            return None
        orig_amt = float(raw.get("originalAmount") or 0.0)
        bill_amt = float(raw.get("ilsBillingAmount") or orig_amt)
        desc = str(raw.get("businessName") or "").strip()
        ident = raw.get("seqConfirmationNumber") or raw.get("confirmationNumber")
        curr = _normalize_currency(raw.get("currencyIso") or raw.get("currencySimbol"))
        return Transaction(
            identifier=str(ident).strip() if ident else None,
            date=pdate,
            processed_date=processed_iso,
            original_amount=-orig_amt,
            original_currency=curr,
            charged_amount=-bill_amt,
            description=desc,
            memo=str(raw["extraDetails"]).strip() if raw.get("extraDetails") else None,
            category=str(raw["branchCodeDescription"]).strip()
            if raw.get("branchCodeDescription")
            else None,
            status=TransactionStatus.PENDING,
            type=TransactionType.NORMAL,
            raw_data=raw,
        )

    @staticmethod
    def _map_voucher(raw: dict[str, Any], processed_iso: str) -> Transaction | None:
        pdate = parse_il_date(raw.get("purchaseDate"))
        if not pdate:
            return None
        desc = str(raw.get("businessName") or "").strip()
        if desc in ('סך חיוב בש"ח בבנק', "סך חיוב בחשבון"):
            return None

        orig_amt = float(raw.get("originalAmount") or 0.0)
        bill_amt = float(raw.get("billingAmount") or raw.get("ilsAmount") or orig_amt)
        curr = _normalize_currency(
            raw.get("originalCurrencyIso") or raw.get("originalCurrencySymbol")
        )
        more_info = str(raw.get("moreInfo") or "").strip()

        installments: InstallmentsInfo | None = None
        if raw.get("currentInstallmentNum") and raw.get("numberOfInstallment"):
            installments = InstallmentsInfo(
                number=int(raw["currentInstallmentNum"]),
                total=int(raw["numberOfInstallment"]),
            )
        elif "תשלום" in more_info:
            nums = re.findall(r"\d+", more_info)
            if len(nums) >= 2:
                installments = InstallmentsInfo(number=int(nums[0]), total=int(nums[1]))

        t_type = (
            TransactionType.INSTALLMENTS if installments is not None else TransactionType.NORMAL
        )
        voucher_num = raw.get("voucherNumber") or raw.get("seqVoucherNumber")
        ident = str(voucher_num).strip() if voucher_num and str(voucher_num) != "0" else None

        return Transaction(
            identifier=ident,
            date=pdate,
            processed_date=processed_iso,
            original_amount=-orig_amt,
            original_currency=curr,
            charged_amount=-bill_amt,
            description=desc,
            memo=more_info or None,
            status=TransactionStatus.COMPLETED,
            type=t_type,
            installments=installments,
            raw_data=raw,
        )


class IsracardScraper(BaseIsracardAmexScraper):
    """Pure HTTP browserless scraper for Isracard (`com.isracard.hatavot`)."""

    provider_name = "isracard"
    ring_base_url = "https://ring.isracard.co.il"
    application_id = "mi"
    isr_domain = "isracard"
    company_code = 11


class AmexScraper(BaseIsracardAmexScraper):
    """Pure HTTP browserless scraper for American Express Israel (`com.americanexpress.android`)."""

    provider_name = "amex"
    ring_base_url = "https://ring.americanexpress.co.il"
    application_id = "ma"
    isr_domain = "amex"
    company_code = 77
