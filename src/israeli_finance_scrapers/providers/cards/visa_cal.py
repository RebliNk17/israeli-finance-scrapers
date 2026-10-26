"""Pure HTTP browserless scraper for Visa Cal credit cards (api-cc.cal-online.co.il)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from israeli_finance_scrapers.base.base_scraper import BaseScraper, ScraperOptions
from israeli_finance_scrapers.base.exceptions import (
    FinanceScraperError,
    InvalidCredentialsError,
    InvalidOtpError,
)
from israeli_finance_scrapers.models.bank import (
    Account,
    AccountType,
    InstallmentsInfo,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from israeli_finance_scrapers.utils import normalize_israeli_id

CAL_MOBILE_BASE_URL = "https://api-cc.cal-online.co.il"
CAL_MOBILE_SITE_ID = "8D37DF16-5812-4ACD-BAE7-CD1A5BFA2207"
CAL_MOBILE_APP_VERSION = "6.26.17"

CAL_MOBILE_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json; charset=UTF-8",
    "X-Site-Id": CAL_MOBILE_SITE_ID,
    "platform": "android",
    "version": CAL_MOBILE_APP_VERSION,
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 11; Pixel 3 Build/RQ1A.210105.003; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/131.0.6778.135 "
        "Mobile Safari/537.36"
    ),
}

CURRENCY_MAP = {
    "₪": "ILS",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
}


def _normalize_currency(sym: str | None) -> str:
    if not sym:
        return "ILS"
    return CURRENCY_MAP.get(sym.strip(), sym.strip())


class VisaCalScraper(BaseScraper):
    """Browserless scraper for Visa Cal personal credit cards using mobile REST APIs."""

    provider_name = "visa_cal"

    def __init__(
        self,
        credentials: dict[str, Any],
        options: ScraperOptions | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(credentials, options, client=client)
        self.authorization: str | None = None
        self.mobile_token_guid: str = ""

    async def login(self) -> None:
        """Authenticate via bioLogin (using stored hash) or regular username/password."""
        if self.client is None:
            await self.initialize()
        assert self.client is not None

        # 1. Try passwordless biometric token (hash) if provided
        long_term_token = self.credentials.get("otpLongTermToken")
        if long_term_token:
            bio_res = await self.client.post(
                f"{CAL_MOBILE_BASE_URL}/Authentication/api/login/bioLogin",
                headers=CAL_MOBILE_HEADERS,
                json={"hash": str(long_term_token).strip()},
            )
            if bio_res.status_code == 200:
                data = bio_res.json()
                if data.get("statusCode") == 1 and data.get("result", {}).get("calConnectToken"):
                    res_obj = data["result"]
                    token = res_obj["calConnectToken"].strip()
                    self.authorization = f"CALAuthScheme {token}"
                    self.mobile_token_guid = res_obj.get("temporaryGuid", "")
                    if res_obj.get("hash"):
                        self.refreshed_long_term_token = res_obj["hash"]
                    return

        # 2. Regular username and password login (if provided)
        username = self.credentials.get("username")
        password = self.credentials.get("password")
        if username and password:
            await self._login_with_password(str(username).strip(), str(password).strip())
            return

        # 3. SMS OTP login (id + last4Digits/card4Digits or bankAccountNum)
        raw_id = self.credentials.get("id") or self.credentials.get("custExtId")
        last4 = (
            self.credentials.get("card4Digits")
            or self.credentials.get("last4Digits")
            or (
                str(self.credentials["card6Digits"]).strip()[-4:]
                if self.credentials.get("card6Digits")
                else None
            )
        )
        bank_account = self.credentials.get("bankAccountNum")
        if raw_id and (last4 or bank_account):
            await self._login_with_sms_otp(
                normalize_israeli_id(str(raw_id)),
                last4=str(last4).strip() if last4 else None,
                bank_account=str(bank_account).strip() if bank_account else None,
            )
            return

        raise InvalidCredentialsError(
            "Visa Cal requires either ('username' and 'password'), "
            "('id' and 'card4Digits'/'bankAccountNum' for SMS OTP), or 'otpLongTermToken'"
        )

    async def _login_with_password(self, username: str, password: str) -> None:
        assert self.client is not None
        login_res = await self.client.post(
            f"{CAL_MOBILE_BASE_URL}/Authentication/api/login/regularLogin",
            headers=CAL_MOBILE_HEADERS,
            json={
                "username": username,
                "password": password,
                "uuid": uuid.uuid4().hex,
                "newPassword": None,
            },
        )

        if login_res.status_code != 200:
            raise FinanceScraperError(f"Cal login failed with HTTP {login_res.status_code}")

        data = login_res.json()
        status_code = data.get("statusCode")
        if status_code == 4:
            raise InvalidCredentialsError(
                data.get("statusDescription") or "שם המשתמש או הסיסמה שהוזנו שגויים"
            )

        if status_code != 1 or not (data.get("result") or {}).get("calConnectToken"):
            msg = data.get("statusDescription") or data.get("statusTitle") or "Login failed"
            raise FinanceScraperError(f"Cal login failed: {msg}")

        res_obj = data["result"]
        token = res_obj["calConnectToken"].strip()
        self.authorization = f"CALAuthScheme {token}"
        self.mobile_token_guid = res_obj.get("temporaryGuid", "")
        if res_obj.get("hash"):
            self.refreshed_long_term_token = res_obj["hash"]

    async def _login_with_sms_otp(
        self,
        id_num: str,
        *,
        last4: str | None = None,
        bank_account: str | None = None,
    ) -> None:
        assert self.client is not None
        if last4:
            send_url = f"{CAL_MOBILE_BASE_URL}/Authentication/api/login/sendOTP"
            send_payload: dict[str, Any] = {
                "custExtId": id_num,
                "last4Digits": last4,
                "smsByVoice": False,
            }
        else:
            send_url = f"{CAL_MOBILE_BASE_URL}/Authentication/api/login/sendOTPByAccount"
            send_payload = {
                "custExtId": id_num,
                "bankAccountNum": bank_account,
                "smsByVoice": False,
            }

        send_res = await self.client.post(
            send_url,
            headers=CAL_MOBILE_HEADERS,
            json=send_payload,
        )
        if send_res.status_code != 200:
            raise FinanceScraperError(f"Cal sendOTP failed with HTTP {send_res.status_code}")

        send_data = send_res.json()
        res_inner = send_data.get("result") if isinstance(send_data.get("result"), dict) else {}
        otp_token = res_inner.get("token") or send_data.get("token")
        if send_data.get("statusCode") != 1 or not otp_token:
            msg = (
                send_data.get("statusDescription")
                or send_data.get("statusTitle")
                or "Failed to send SMS OTP"
            )
            raise InvalidCredentialsError(str(msg))

        otp_code = self.credentials.get("otpCode") or await self._resolve_otp_code()

        verify_res = await self.client.post(
            f"{CAL_MOBILE_BASE_URL}/Authentication/api/login/verifyOTP",
            headers=CAL_MOBILE_HEADERS,
            json={
                "token": str(otp_token).strip(),
                "password": str(otp_code).strip(),
                "uuid": uuid.uuid4().hex,
            },
        )
        if verify_res.status_code != 200:
            raise FinanceScraperError(f"Cal verifyOTP failed with HTTP {verify_res.status_code}")

        verify_data = verify_res.json()
        res_obj = verify_data.get("result") if isinstance(verify_data.get("result"), dict) else {}
        if verify_data.get("statusCode") != 1 or not res_obj.get("calConnectToken"):
            msg = (
                verify_data.get("statusDescription")
                or verify_data.get("statusTitle")
                or "Invalid SMS OTP code"
            )
            raise InvalidOtpError(str(msg))

        token = res_obj["calConnectToken"].strip()
        self.authorization = f"CALAuthScheme {token}"
        self.mobile_token_guid = res_obj.get("temporaryGuid", "")
        if res_obj.get("hash"):
            self.refreshed_long_term_token = res_obj["hash"]

    async def fetch_data(self) -> None:
        """Fetch all cards, limits, and transactions."""
        assert self.client is not None
        if not self.authorization:
            raise FinanceScraperError("Must login before fetching data")

        auth_headers = {
            **CAL_MOBILE_HEADERS,
            "Authorization": self.authorization,
        }

        # 1. Fetch cards list
        init_res = await self.client.post(
            f"{CAL_MOBILE_BASE_URL}/Authentication/api/account/init",
            headers=auth_headers,
            json={"tokenGuid": self.mobile_token_guid} if self.mobile_token_guid else {},
        )
        if init_res.status_code != 200:
            raise FinanceScraperError(f"Failed to fetch cards list: HTTP {init_res.status_code}")

        init_data = init_res.json()
        raw_cards = init_data.get("result", {}).get("cards") or []
        if not raw_cards:
            self.accounts = []
            return

        # 2. Fetch frame and limit details
        cards_for_frame = [
            {"cardUniqueId": c["cardUniqueId"]} for c in raw_cards if "cardUniqueId" in c
        ]
        frames_res = await self.client.post(
            f"{CAL_MOBILE_BASE_URL}/Frames/api/Frames/GetTotalFrameStatus",
            headers=auth_headers,
            json={"cardsForFrameData": cards_for_frame},
        )
        frames_data = frames_res.json().get("result") or {} if frames_res.status_code == 200 else {}

        # 3. For each card, fetch pending + completed transactions
        scraped_accounts: list[Account] = []
        for card in raw_cards:
            card_id = card.get("cardUniqueId")
            last4 = card.get("last4Digits", "")
            if not card_id:
                continue

            # Frame calculation for this card
            card_limit, open_to_buy, next_debit = self._parse_frame(card_id, frames_data)

            # Pending transactions
            pending_txns = await self._fetch_pending_transactions(card_id, auth_headers)

            # Completed transactions
            completed_txns = await self._fetch_completed_transactions(card_id, auth_headers)

            all_txns = pending_txns + completed_txns

            # Deduplicate transactions (e.g. statement overlaps)
            seen_keys: set[tuple[str | None, str, float]] = set()
            deduped_txns: list[Transaction] = []
            for t in all_txns:
                key = (t.identifier, t.date, t.charged_amount)
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped_txns.append(t)
            all_txns = deduped_txns

            # Filter by start_date if requested
            if self.options.start_date:
                start_iso = self.options.start_date[:10]
                all_txns = [t for t in all_txns if t.date[:10] >= start_iso]

            scraped_accounts.append(
                Account(
                    account_number=last4,
                    account_type=AccountType.CREDIT_CARD,
                    balance=-next_debit if next_debit is not None else None,
                    credit_limit=card_limit,
                    open_to_buy=open_to_buy,
                    currency="ILS",
                    txns=all_txns,
                )
            )

        self.accounts = scraped_accounts

    def _parse_frame(
        self, card_id: str, frames_data: dict[str, Any]
    ) -> tuple[float | None, float | None, float | None]:
        bank_group = frames_data.get("bankIssuedCards") or {}
        cal_group = frames_data.get("calIssuedCards") or {}

        # Look in cardLevelFrames
        frames_list = bank_group.get("cardLevelFrames") or []
        frames_list += cal_group.get("cardLevelFrames") or []
        matched_frame = next((f for f in frames_list if f.get("cardUniqueId") == card_id), None)

        next_debit = matched_frame.get("nextTotalDebit") if matched_frame else None
        if next_debit is None:
            next_debit = bank_group.get("nextTotalDebitForAccount") or cal_group.get(
                "nextTotalDebitForAccount"
            )

        limit = None
        open_to_buy = None
        group = cal_group if cal_group.get("frameLimitForCardAmount") else bank_group
        if group:
            limit = group.get("frameLimitForCardAmount")
            fictive = group.get("fictiveMaxAccAmt")
            if limit is not None and fictive is not None:
                open_to_buy = limit - fictive

        return limit, open_to_buy, next_debit

    async def _fetch_pending_transactions(
        self, card_id: str, headers: dict[str, str]
    ) -> list[Transaction]:
        assert self.client is not None
        try:
            res = await self.client.post(
                f"{CAL_MOBILE_BASE_URL}/Transactions/api/approvals/getClearanceRequests",
                headers=headers,
                json={"cardUniqueIDArray": [card_id]},
            )
            if res.status_code != 200:
                return []
            data = res.json()
            cards_list = data.get("result", {}).get("cardsList") or []
            txns: list[Transaction] = []
            for item in cards_list:
                auth_list = item.get("authDetalisList") or []
                for a in auth_list:
                    raw_date = a.get("trnPurchaseDate") or datetime.now(UTC).strftime("%Y-%m-%d")
                    amount = float(a.get("amount") or 0.0)
                    txns.append(
                        Transaction(
                            identifier=str(a.get("authNum") or ""),
                            date=raw_date[:10],
                            processed_date=None,
                            original_amount=amount,
                            original_currency=_normalize_currency(a.get("currencySymbol")),
                            charged_amount=amount,
                            description=a.get("merchantName") or "",
                            status=TransactionStatus.PENDING,
                            type=TransactionType.NORMAL,
                            raw_data=a,
                        )
                    )
            return txns
        except Exception:  # noqa: BLE001
            return []

    async def _fetch_completed_transactions(
        self, card_id: str, headers: dict[str, str]
    ) -> list[Transaction]:
        assert self.client is not None
        # Cal transactions endpoint returns recent months
        now = datetime.now(UTC)
        months_to_fetch = 3  # default ~3 months
        if self.options.start_date:
            try:
                start_dt = datetime.fromisoformat(self.options.start_date[:10])
                months_diff = (now.year - start_dt.year) * 12 + (now.month - start_dt.month) + 1
                months_to_fetch = max(1, min(18, months_diff))
            except Exception:  # noqa: BLE001
                months_to_fetch = 3

        txns: list[Transaction] = []
        for i in range(months_to_fetch):
            # Calculate month and year
            total_months = now.year * 12 + now.month - 1 - i
            m_year = total_months // 12
            m_num = total_months % 12 + 1

            res = await self.client.post(
                f"{CAL_MOBILE_BASE_URL}/Transactions/api/transactionsDetails/getCardTransactionsDetails",
                headers=headers,
                json={
                    "cardUniqueId": card_id,
                    "month": str(m_num),
                    "year": str(m_year),
                },
            )
            if res.status_code != 200:
                continue

            data = res.json()
            if data.get("statusCode") != 1:
                continue

            bank_accounts = data.get("result", {}).get("bankAccounts") or []
            for b in bank_accounts:
                debit_dates = b.get("debitDates") or []
                for d in debit_dates:
                    raw_txns = d.get("transactions") or []
                    for t in raw_txns:
                        txns.append(self._parse_completed_txn(t, d.get("date")))

        return txns

    def _parse_completed_txn(self, t: dict[str, Any], debit_date: str | None) -> Transaction:
        # Installments detection: trnTypeCode '8' = installments
        trn_type_code = str(t.get("trnTypeCode") or "")
        is_installments = trn_type_code == "8" or (t.get("numOfPayments") or 1) > 1

        installments = None
        if is_installments:
            installments = InstallmentsInfo(
                number=int(t.get("curPaymentNum") or 1),
                total=int(t.get("numOfPayments") or 1),
            )

        purchase_date = str(t.get("trnPurchaseDate") or "")[:10]
        proc_date = str(t.get("debCrdDate") or debit_date or "")[:10]

        original_amount = float(t.get("trnAmt") or 0.0)
        charged_amount = float(t.get("cashAccountTrnAmt") or original_amount)

        return Transaction(
            identifier=str(t.get("trnIntId") or t.get("trnNumaretor") or ""),
            date=purchase_date or proc_date,
            processed_date=proc_date or None,
            original_amount=original_amount,
            original_currency=_normalize_currency(
                t.get("debCrdCurrencySymbol") or t.get("trnCurrencySymbol")
            ),
            charged_amount=charged_amount,
            description=str(t.get("merchantName") or "").strip(),
            memo=str(t.get("branchCodeDesc") or "").strip() or None,
            status=TransactionStatus.COMPLETED,
            type=TransactionType.INSTALLMENTS if is_installments else TransactionType.NORMAL,
            installments=installments,
            category=str(t.get("trnType") or "").strip() or None,
            raw_data=t,
        )
