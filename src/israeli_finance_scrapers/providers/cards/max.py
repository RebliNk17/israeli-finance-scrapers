"""Pure HTTP browserless scraper for Max (Leumi Card).

Connects to `https://mpg.max.co.il/MPG49/DRS04/TPS2/lcapi`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
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
from israeli_finance_scrapers.utils import extract_number, parse_il_date

MAX_LCAPI_BASE_URL = "https://mpg.max.co.il/MPG49/DRS04/TPS2/lcapi"
APP_ID = "505"
APP_TP = "756"
APP_CV = "20.90.1"
APP_BVER = "20.90.1.37"

# Default enrolled device identifiers from com.ideomobile.leumicard
DEFAULT_DID = "LC_c93264a2-2aa4-4c97-854f-5370ebad1699"
DEFAULT_KEY_FP = "06f6ea7b-9289-4238-aae1-47aba456c651"
DEFAULT_FPR = hashlib.sha256((DEFAULT_KEY_FP + DEFAULT_DID).encode("utf-8")).hexdigest()

MAX_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json",
    "Cache-Control": "No-Transform",
    "X-Requested-With": "com.leumicard.wallet",
    "User-Agent": "okhttp/4.12.0",
}

_CURRENCY_BY_CODE = {
    376: "ILS",
    840: "USD",
    978: "EUR",
    826: "GBP",
}


def _parse_amount(val: Any) -> float:
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = (
        str(val)
        .replace("₪", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace(",", "")
        .strip()
    )
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else 0.0


def _parse_frame_limits(balance_text: str | None) -> tuple[float | None, float | None]:
    """Parse ``'יתרת מסגרת:\\n₪5,576.00 מתוך ₪10,000.00'`` -> ``(credit_limit, open_to_buy)``."""
    if not balance_text:
        return None, None
    nums = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", str(balance_text))]
    if len(nums) >= 2:
        return nums[1], nums[0]
    return None, None


class MaxScraper(BaseScraper):
    """Pure HTTP browserless scraper for Max (`com.ideomobile.leumicard`)."""

    provider_name = "max"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sid: str = str(uuid.uuid4())
        self._did: str = DEFAULT_DID
        self._fpr: str = DEFAULT_FPR
        self._dl_cards: list[dict[str, Any]] = []
        self._logged_in: bool = False
        self._load_device_token()

    def _load_device_token(self) -> None:
        raw = self.credentials.get("otpLongTermToken")
        if not raw:
            return
        with contextlib.suppress(Exception):
            parsed = json.loads(str(raw))
            if isinstance(parsed, dict):
                if parsed.get("dId"):
                    self._did = str(parsed["dId"])
                if parsed.get("fpr"):
                    self._fpr = str(parsed["fpr"])
                elif parsed.get("keyFp"):
                    self._fpr = hashlib.sha256(
                        (str(parsed["keyFp"]) + self._did).encode("utf-8")
                    ).hexdigest()

    def _envelope(self, vars_dict: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "AppId": APP_ID,
            "AppTp": APP_TP,
            "DId": self._did,
            "Fpr": self._fpr,
            "FprSdkReqId": "1792939405952.q4ZjKB",
            "FprSdk": "B4DX5XYy7KsDI60kjgMP",
            "SId": self._sid,
            "Lang": "en",
            "Pl": "16",
            "Cv": APP_CV,
            "BVer": APP_BVER,
        }
        if vars_dict is not None:
            payload["vars"] = vars_dict
        return payload

    async def _post_cmd(
        self,
        cmd_id: int | str,
        vars_dict: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert self.client is not None
        url = f"{MAX_LCAPI_BASE_URL}/C{cmd_id}/post"
        resp = await self.client.post(
            url,
            headers=MAX_HEADERS,
            json=self._envelope(vars_dict),
        )
        if resp.status_code >= 400:
            raise FinanceScraperError(f"Max C{cmd_id} failed with HTTP {resp.status_code}")
        return resp.json()

    async def login(self) -> None:
        """Authenticate via C391 -> C305 using username and password."""
        if self.client is None:
            await self.initialize()

        username = self.credentials.get("username")
        password = self.credentials.get("password")
        if not username or not password:
            raise InvalidCredentialsError("Both 'username' and 'password' are required for Max")

        # 1. Bootstrap session via C391
        await self._post_cmd(
            391,
            {
                "lat": 0.0,
                "lon": 0.0,
                "mod": "Pixel 3",
                "osVer": "11",
                "vnum": APP_BVER,
            },
        )

        # 2. Authenticate via C305
        r305 = await self._post_cmd(
            305,
            {
                "uName": str(username).strip(),
                "pass": str(password),
                "uId": 0,
                "eP": False,
                "uRecreate": False,
                "gistInfo": False,
                "swUser": False,
                "action": 0,
            },
        )
        do305 = r305.get("DO") or {}
        gen305 = do305.get("Gen") or {}
        if gen305.get("UAuth") is True and gen305.get("Status") == 0:
            if gen305.get("NewSId"):
                self._sid = str(gen305["NewSId"])
            self._dl_cards = do305.get("DLCards") or []
            self._logged_in = True
            self.refreshed_long_term_token = json.dumps({"dId": self._did, "fpr": self._fpr})
            return

        msg305 = str(gen305.get("Msg") or do305.get("ErrorMessage") or "")
        if any(w in msg305 for w in ("נחסם", "נעול", "ננעל")):
            raise AccountBlockedError(msg305)
        raise InvalidCredentialsError(msg305 or "Invalid Max username or password")

    async def fetch_data(self) -> None:
        """Fetch all cards and monthly transactions via C495 and C382."""
        if not self._logged_in:
            raise FinanceScraperError("Must login before fetching Max data")

        cards = self._dl_cards
        if not cards:
            r495 = await self._post_cmd(495)
            cards = ((r495.get("DO") or {}).get("Pnl") or {}).get("Cards") or []

        accounts_by_num: dict[str, Account] = {}
        card_indices: list[str] = []
        for idx, c in enumerate(cards):
            if not isinstance(c, dict):
                continue
            cnum = str(c.get("Number") or "").strip()
            if not cnum:
                continue
            c_idx = str(c.get("Index") if c.get("Index") is not None else idx)
            card_indices.append(c_idx)
            limit, otb = _parse_frame_limits(c.get("Balance"))
            used = round(limit - otb, 2) if (limit is not None and otb is not None) else None
            accounts_by_num[cnum] = Account(
                account_number=cnum,
                account_type=AccountType.CREDIT_CARD,
                balance=-used if used is not None else None,
                credit_limit=limit,
                open_to_buy=otb,
                currency="ILS",
                txns=[],
            )

        if not accounts_by_num:
            self.accounts = []
            return

        c_indexes_str = ",".join(card_indices) if card_indices else "0"

        now = datetime.now(UTC)
        start_dt = (
            datetime.strptime(self.options.start_date, "%Y-%m-%d").replace(tzinfo=UTC)
            if self.options.start_date
            else datetime(now.year - 1, now.month, 1, tzinfo=UTC)
        )
        months: list[str] = []
        cur_y, cur_m = start_dt.year, start_dt.month
        end_m = now.month + 1
        end_y = now.year + (1 if end_m > 12 else 0)
        if end_m > 12:
            end_m -= 12
        while (cur_y, cur_m) <= (end_y, end_m):
            months.append(f"{cur_m:02d}{cur_y:04d}")
            cur_m += 1
            if cur_m > 12:
                cur_m = 1
                cur_y += 1

        seen_txns: dict[str, set[tuple[str | None, str, float]]] = {
            cnum: set() for cnum in accounts_by_num
        }

        for m_str in months:
            r382 = await self._post_cmd(
                382,
                {
                    "cIndexes": c_indexes_str,
                    "cNum": "-1",
                    "month": m_str,
                    "sort": 0,
                },
            )
            trans_obj = ((r382.get("DO") or {}).get("Trans")) or {}
            sections = [
                (trans_obj.get("ListCycleDate") or [], TransactionStatus.COMPLETED),
                (trans_obj.get("ListImmediate") or [], TransactionStatus.COMPLETED),
                (trans_obj.get("ListForeign") or [], TransactionStatus.COMPLETED),
                (trans_obj.get("ListMoneyPockets") or [], TransactionStatus.COMPLETED),
                (trans_obj.get("ListRefunds") or [], TransactionStatus.COMPLETED),
                (trans_obj.get("ListApprovals") or [], TransactionStatus.PENDING),
            ]
            for items, status in sections:
                for raw_item in items:
                    if not isinstance(raw_item, dict) or raw_item.get("Type") != 0:
                        continue
                    cnum = str(raw_item.get("CNum") or "").strip()
                    if cnum not in accounts_by_num:
                        continue
                    txn = self._map_txn(raw_item, status)
                    if txn is None:
                        continue
                    effective_dt = txn.processed_date if txn.installments else txn.date
                    if (
                        self.options.start_date
                        and (effective_dt or txn.date) < self.options.start_date
                    ):
                        continue
                    dedup_key = (
                        txn.identifier,
                        txn.date,
                        txn.charged_amount,
                        txn.installments.number if txn.installments else None,
                    )
                    if dedup_key not in seen_txns[cnum]:
                        seen_txns[cnum].add(dedup_key)
                        accounts_by_num[cnum].txns.append(txn)

        self.accounts = list(accounts_by_num.values())

    @staticmethod
    def _map_txn(raw: dict[str, Any], status: TransactionStatus) -> Transaction | None:
        pdate_raw = raw.get("PurchaseDateTime") or raw.get("PurchaseDate")
        pdate = parse_il_date(str(pdate_raw)) if pdate_raw else None
        if not pdate:
            return None

        pay_date_raw = raw.get("PaymentDate")
        processed_date = parse_il_date(str(pay_date_raw)) if pay_date_raw else pdate

        actual_amt = _parse_amount(raw.get("ActualPayment"))
        orig_double = extract_number(raw.get("OriginalAmountDouble"), None)
        orig_amt = (
            orig_double if orig_double is not None else _parse_amount(raw.get("OriginalAmount"))
        )
        if orig_amt == 0.0:
            orig_amt = actual_amt

        # Max reports charges as positive numbers in ActualPayment (e.g. "₪158.00")
        charged_amount = -actual_amt
        original_amount = -orig_amt if actual_amt >= 0 else abs(orig_amt)

        curr_code = int(raw.get("PaymentCurrency") or 376)
        currency = _CURRENCY_BY_CODE.get(curr_code, "ILS")

        desc = str(raw.get("MerchantDescription") or "").strip()
        comments = str(raw.get("Comments") or "").strip()
        category = str(raw.get("CName") or "").strip() or None

        installments: InstallmentsInfo | None = None
        if "תשלום" in comments and "מתוך" in comments:
            nums = re.findall(r"\d+", comments)
            if len(nums) >= 2:
                installments = InstallmentsInfo(number=int(nums[0]), total=int(nums[1]))

        plan_desc = str(raw.get("PlanDesc") or "").strip()
        t_type = (
            TransactionType.INSTALLMENTS
            if (installments is not None or plan_desc in ("תשלומים", "קרדיט"))
            else TransactionType.NORMAL
        )

        arn = str(raw.get("OriginalARN") or raw.get("TId") or "").strip()
        ident = arn if arn and not arn.startswith(("undefined", "null")) else None

        return Transaction(
            identifier=ident,
            date=pdate,
            processed_date=processed_date,
            original_amount=original_amount,
            original_currency=currency,
            charged_amount=charged_amount,
            description=desc,
            memo=comments or None,
            status=status,
            type=t_type,
            installments=installments,
            category=category,
            raw_data=raw,
        )
