"""Pure HTTP browserless scraper for Pepper Bank.

Implements Transmit Security v2 device binding, EC P-256 content signatures,
SMS OTP verification, persistent device-state resume, and GraphQL account &
transaction queries against `https://sa.pepper.co.il` and `https://fe-sec.pepper.co.il/graphql`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from israeli_finance_scrapers.base.base_scraper import OTP_CANCEL_SENTINEL, BaseScraper
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

IDENTITY_BASE_URL = "https://sa.pepper.co.il"
GRAPHQL_API_URL = "https://fe-sec.pepper.co.il/graphql"
AID = "DIGITAL_BLL"
LOCALE = "en-US"
APK_VERSION = "11.11.1"
APP_VERSION_HEADER = "11.11.1-202610131543"
TS_CLIENT_VERSION = "8.2.3 (10870);[1,2,3,6,7,8,10,11,12,14,28,19,27]"
SDK_VERSION_METADATA = "8.2.3 (10870)"
STATIC_AUTH_HEADER = "TSToken 7cf2d7a7-681d-450a-ab23-06e48d2b8fd6; tid=digital_client_token_token"
USER_AGENT = "okhttp/4.12.0"
PAGE_SIZE = 100
TOKEN_FRESHNESS_MARGIN_SECONDS = 60

USER_DATA_V2_QUERY = """
query UserDataV2 {
  userDataV2 {
    getUserDataV2 {
      customerAndAccounts {
        customerId
        accounts {
          accountId
          accountNumber
          accountCategory
        }
      }
    }
  }
}
"""

FETCH_ACCOUNT_BALANCE_QUERY = """
query fetchAccountBalance($accountId: String!) {
  accounts {
    balance(accountId: $accountId) {
      currentBalance
    }
  }
}
"""

TRANSACTIONS_QUERY = """
query Transactions(
  $accountId: String!
  $from: String
  $to: String
  $pageNumber: Int
  $pageCount: Int
) {
  accounts {
    oshTransactionsNew(
      accountId: $accountId
      from: $from
      to: $to
      pageNumber: $pageNumber
      pageCount: $pageCount
    ) {
      totalCount
      transactions {
        transactionId
        transactionAmount
        bookingDate
        effectiveDate
        currency
        description
        title
        subTitle
        referenceNumber
        liquidityStatus
      }
      pendingTransactions {
        transactionId
        transactionAmount
        bookingDate
        effectiveDate
        currency
        description
        title
        subTitle
        referenceNumber
        liquidityStatus
      }
    }
  }
}
"""

_APP_PERMISSIONS = [
    {"name": name, "granted": True}
    for name in (
        "android.permission.INTERNET",
        "android.permission.ACCESS_NETWORK_STATE",
        "com.google.android.c2dm.permission.RECEIVE",
        "com.google.android.gms.permission.AD_ID",
        "android.permission.RECEIVE_BOOT_COMPLETED",
        "android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
        "android.permission.VIBRATE",
        "android.permission.WAKE_LOCK",
        "android.permission.ACCESS_WIFI_STATE",
        "android.permission.DOWNLOAD_WITHOUT_NOTIFICATION",
        "android.permission.ACCESS_ADSERVICES_ATTRIBUTION",
        "android.permission.USE_FINGERPRINT",
        "android.permission.USE_BIOMETRIC",
        "android.permission.READ_PROFILE",
        "android.permission.ACCESS_ADSERVICES_AD_ID",
        "android.permission.FOREGROUND_SERVICE",
        "com.google.android.finsky.permission.BIND_GET_INSTALL_REFERRER_SERVICE",
        "com.google.android.providers.gsf.permission.READ_GSERVICES",
        "com.pepper.ldb.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION",
        "android.permission.NFC",
        "android.permission.USE_FULL_SCREEN_INTENT",
        "android.permission.SCHEDULE_EXACT_ALARM",
        "android.permission.ACCESS_NOTIFICATION_POLICY",
    )
]


@dataclass
class _EcKeyBundle:
    private_key: ec.EllipticCurvePrivateKey
    public_key_b64: str
    key_id_hex: str
    pkcs8_b64: str


def _generate_ec_bundle() -> _EcKeyBundle:
    priv = ec.generate_private_key(ec.SECP256R1())
    pub_der = priv.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pkcs8_der = priv.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return _EcKeyBundle(
        private_key=priv,
        public_key_b64=base64.b64encode(pub_der).decode("ascii"),
        key_id_hex=hashlib.sha256(pub_der).hexdigest(),
        pkcs8_b64=base64.b64encode(pkcs8_der).decode("ascii"),
    )


def _import_ec_bundle(pkcs8_b64: str) -> _EcKeyBundle | None:
    try:
        pkcs8_der = base64.b64decode(pkcs8_b64)
        priv = serialization.load_der_private_key(pkcs8_der, password=None)
        if not isinstance(priv, ec.EllipticCurvePrivateKey):
            return None
        pub_der = priv.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return _EcKeyBundle(
            private_key=priv,
            public_key_b64=base64.b64encode(pub_der).decode("ascii"),
            key_id_hex=hashlib.sha256(pub_der).hexdigest(),
            pkcs8_b64=pkcs8_b64,
        )
    except Exception:  # noqa: BLE001
        return None


def _generate_rsa_public_key_b64() -> str:
    priv = rsa.generate_private_key(public_exponent=0x10001, key_size=2048)
    pub_der = priv.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(pub_der).decode("ascii")


def _build_content_signature(path_and_query: str, body_json: str, ec_bundle: _EcKeyBundle) -> str:
    if "?" not in path_and_query:
        sorted_pq = path_and_query
    else:
        path_part, query_part = path_and_query.split("?", 1)
        sorted_pq = f"{path_part}?{'&'.join(sorted(query_part.split('&')))}"
    parts = [p.replace("%%", "\\%") for p in (sorted_pq, TS_CLIENT_VERSION, body_json)]
    canonical = "%%".join(parts).encode("utf-8")
    sig_der = ec_bundle.private_key.sign(canonical, ec.ECDSA(hashes.SHA256()))
    sig_b64 = base64.b64encode(sig_der).decode("ascii")
    return f"data:{sig_b64};key-id:{ec_bundle.key_id_hex};scheme:4"


def _normalize_pepper_phone(raw: str | None) -> tuple[str, str] | None:
    digits = re.sub(r"\D", "", str(raw or ""))
    if re.match(r"^05\d{8}$", digits):
        return f"972{digits[1:]}", digits
    if re.match(r"^9725\d{8}$", digits):
        return digits, f"0{digits[3:]}"
    return None


def _build_collection_result(now_ms: int, device_name: str | None = None) -> dict[str, Any]:
    return {
        "metadata": {
            "scheme_version": 2,
            "physical_app_id": "com.pepper.ldb",
            "version": SDK_VERSION_METADATA,
            "timestamp": now_ms // 1000,
        },
        "content": {
            "hw_authenticators": {
                "device_biometrics": {
                    "supported": True,
                    "user_registered": False,
                    "possible_types": ["fingerprint"],
                },
                "fingerprint": {"supported": False, "user_registered": False},
                "face_id": {"supported": False, "user_registered": False},
            },
            "device_details": {
                "hw_type": "Phone",
                "tampered": True,
                "sim_operator": "310260",
                "roaming": False,
                "device_model": "Google/sdk_gphone64_x86_64",
                "os_version": "13",
                "jailbroken": True,
                "security_patch": "2024-03-01",
                "sim_operator_name": "T-Mobile",
                "frontal_camera": False,
                "device_name": device_name or uuid.uuid4().hex[:16],
                "has_hw_security": False,
                "screen_lock": False,
                "os_type": "Android",
                "boot_loader": "unknown",
                "base_os": "",
                "logged_users": 0,
                "persistence_mode": "false",
                "last_reboot": 85993,
                "tz": "GMT",
                "sflags": -3,
                "supported_abis": ["x86_64"],
                "master_key_generated": now_ms,
            },
            "app_permissions": _APP_PERMISSIONS,
            "capabilities": {
                "fido2_user_verifying_platform_authenticator_available": False,
                "audio_acquisition_supported": True,
                "finger_print_supported": False,
                "image_acquisition_supported": True,
                "persistent_keys_supported": True,
                "face_id_key_bio_protection_supported": False,
                "fido2_client_present": True,
                "dyadic_present": False,
                "installed_plugins": [],
                "host_provided_features": "19",
            },
            "collector_state": {
                "accounts": "active",
                "devicedetails": "active",
                "contacts": "active",
                "owner": "active",
                "locationcountry": "active",
                "bluetooth": "active",
                "externalsdkdetails": "active",
                "hwauthenticators": "active",
                "capabilities": "active",
                "largedata": "active",
                "localenrollments": "active",
                "devicefingerprint": "active",
                "apppermissions": "active",
                "software": "disabled",
                "location": "disabled",
            },
            "local_enrollments": {},
        },
    }


def _is_jwt_fresh(token: str | None) -> bool:
    try:
        parts = str(token or "").split(".")
        if len(parts) < 2:
            return False
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        exp = payload.get("exp")
        return (
            isinstance(exp, (int, float))
            and exp > int(time.time()) + TOKEN_FRESHNESS_MARGIN_SECONDS
        )
    except Exception:  # noqa: BLE001
        return False


def _encode_state(state: dict[str, Any]) -> str:
    raw = json.dumps(state, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_state(encoded: str | None) -> dict[str, Any] | None:
    try:
        s = str(encoded or "").strip()
        if not s:
            return None
        padded = s + "=" * (-len(s) % 4)
        parsed = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if (
            isinstance(parsed, dict)
            and parsed.get("v") == 1
            and isinstance(parsed.get("deviceId"), str)
            and isinstance(parsed.get("clientInstanceId"), str)
            and isinstance(parsed.get("ecPrivateKeyPkcs8Base64"), str)
            and isinstance(parsed.get("token"), str)
        ):
            return parsed
        return None
    except Exception:  # noqa: BLE001
        return None


def _extract_header_field(headers: Any, key: str) -> str | None:
    if not isinstance(headers, list):
        return None
    for h in headers:
        if isinstance(h, dict) and isinstance(h.get(key), str):
            return h[key]
    return None


def _extract_password_assertion_id(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    cf = data.get("control_flow")
    if not isinstance(cf, list) or not cf or not isinstance(cf[0], dict):
        return None
    for m in cf[0].get("methods") or []:
        if (
            isinstance(m, dict)
            and m.get("type") == "password"
            and isinstance(m.get("assertion_id"), str)
        ):
            return m["assertion_id"]
    return None


def _extract_sms_assertion_id(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    cf = data.get("control_flow")
    if not isinstance(cf, list) or not cf or not isinstance(cf[0], dict):
        return None
    for m in cf[0].get("methods") or []:
        if not isinstance(m, dict):
            continue
        for ch in m.get("channels") or []:
            if (
                isinstance(ch, dict)
                and ch.get("type") == "sms"
                and isinstance(ch.get("assertion_id"), str)
            ):
                return ch["assertion_id"]
    return None


class PepperScraper(BaseScraper):
    """Pure HTTP scraper for Pepper Bank."""

    provider_name = "pepper"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.access_token: str | None = None
        self.local_user_id: str = ""
        self.pepper_client_id: str = str(uuid.uuid4())

    async def _post_transmit(
        self,
        path_and_query: str,
        body_obj: dict[str, Any],
        ec_bundle: _EcKeyBundle,
    ) -> dict[str, Any]:
        assert self.client is not None
        body_json = json.dumps(body_obj, separators=(",", ":"), ensure_ascii=False)
        sig = _build_content_signature(path_and_query, body_json, ec_bundle)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": STATIC_AUTH_HEADER,
            "X-TS-Client-Version": TS_CLIENT_VERSION,
            "User-Agent": USER_AGENT,
            "Content-Signature": sig,
        }
        resp = await self.client.post(
            f"{IDENTITY_BASE_URL}{path_and_query}",
            content=body_json.encode("utf-8"),
            headers=headers,
        )
        if resp.status_code >= 400:
            raise FinanceScraperError(
                f"Pepper identity endpoint {path_and_query} returned HTTP {resp.status_code}"
            )
        return resp.json()

    async def _resume_with_saved_state(
        self,
        uid: str,
        password: str,
        saved: dict[str, Any],
    ) -> bool:
        if _is_jwt_fresh(saved.get("token")):
            self.access_token = saved["token"]
            self.refreshed_long_term_token = _encode_state(saved)
            return True

        ec_bundle = _import_ec_bundle(saved["ecPrivateKeyPkcs8Base64"])
        if ec_bundle is None:
            return False

        flow_id = str(uuid.uuid4())
        now_ms = int(time.time() * 1000)
        login_path = (
            f"/api/v2/auth/login?aid={AID}&did={saved['deviceId']}&locale={LOCALE}&tsm={now_ms}"
        )
        login_resp = await self._post_transmit(
            login_path,
            {
                "headers": [
                    {"type": "flow_id", "flow_id": flow_id},
                    {"type": "uid", "uid": uid},
                ],
                "data": {
                    "collection_result": _build_collection_result(now_ms),
                    "policy_request_id": "default",
                    "params": {
                        "CellPhoneID": saved["clientInstanceId"],
                        "Version_App": APK_VERSION,
                        "transactionId": str(uuid.uuid4()),
                    },
                },
            },
            ec_bundle,
        )
        login_data = login_resp.get("data") or {}
        challenge = login_data.get("challenge")
        cf = login_data.get("control_flow") or []
        pwd_action = (
            cf[0].get("type") if cf and isinstance(cf[0], dict) else None
        ) or "authentication"
        pwd_assertion_id = _extract_password_assertion_id(login_data)
        session_id = _extract_header_field(login_resp.get("headers"), "session_id")
        if not challenge or not pwd_assertion_id or not session_id:
            return False

        assert_ms = int(time.time() * 1000)
        assert_path = (
            f"/api/v2/auth/assert?aid={AID}&did={saved['deviceId']}"
            f"&sid={session_id}&locale={LOCALE}&tsm={assert_ms}"
        )
        assert_resp = await self._post_transmit(
            assert_path,
            {
                "headers": [
                    {"type": "flow_id", "flow_id": flow_id},
                    {"type": "uid", "uid": uid},
                ],
                "data": {
                    "action": pwd_action,
                    "assert": "authenticate",
                    "assertion_id": pwd_assertion_id,
                    "fch": challenge,
                    "data": {"password": password},
                    "method": "password",
                },
            },
            ec_bundle,
        )
        token = (assert_resp.get("data") or {}).get("token")
        if not token:
            raise InvalidCredentialsError(
                assert_resp.get("error_message") or "Pepper rejected the password"
            )
        self.access_token = token
        self.refreshed_long_term_token = _encode_state({**saved, "token": token})
        return True

    async def login(self) -> None:
        """Authenticate with Pepper via saved device state or SMS OTP enrollment."""
        if self.client is None:
            await self.initialize()

        normalized = _normalize_pepper_phone(self.credentials.get("phoneNumber"))
        password = self.credentials.get("password")
        if not normalized or not password:
            raise InvalidCredentialsError(
                "Both 'phoneNumber' and 'password' are required for Pepper"
            )
        uid, self.local_user_id = normalized

        long_term = self.credentials.get("otpLongTermToken")
        if long_term:
            saved_state = _decode_state(str(long_term))
            if saved_state is not None:
                if await self._resume_with_saved_state(uid, str(password), saved_state):
                    return
            elif _is_jwt_fresh(str(long_term)):
                self.access_token = str(long_term)
                self.refreshed_long_term_token = str(long_term)
                return

        if self.on_otp_request is None:
            raise FinanceScraperError(
                "SMS OTP verification is required to enroll Pepper device, but on_otp_request is not set"
            )

        ec_bundle = _generate_ec_bundle()
        rsa_pub_b64 = _generate_rsa_public_key_b64()
        client_instance_id = str(uuid.uuid4())
        flow_id = str(uuid.uuid4())
        bind_ms = int(time.time() * 1000)

        bind_path = f"/api/v2/auth/bind?aid={AID}&locale={LOCALE}&tsm={bind_ms}"
        bind_resp = await self._post_transmit(
            bind_path,
            {
                "headers": [
                    {"type": "flow_id", "flow_id": flow_id},
                    {"type": "uid", "uid": uid},
                ],
                "data": {
                    "collection_result": _build_collection_result(bind_ms),
                    "public_key": {"key": ec_bundle.public_key_b64, "type": "ec"},
                    "encryption_public_key": {"key": rsa_pub_b64, "type": "rsa"},
                    "params": {
                        "CellPhoneID": client_instance_id,
                        "Version_App": APK_VERSION,
                        "transactionId": str(uuid.uuid4()),
                    },
                },
            },
            ec_bundle,
        )
        bind_data = bind_resp.get("data") or {}
        challenge = bind_data.get("challenge")
        pwd_assertion_id = _extract_password_assertion_id(bind_data)
        session_id = _extract_header_field(bind_resp.get("headers"), "session_id")
        device_id = _extract_header_field(bind_resp.get("headers"), "device_id")
        if not challenge or not pwd_assertion_id or not session_id or not device_id:
            raise InvalidCredentialsError(
                bind_resp.get("error_message") or "Failed to initiate Pepper device bind"
            )

        pwd_ms = int(time.time() * 1000)
        pwd_path = (
            f"/api/v2/auth/assert?aid={AID}&did={device_id}"
            f"&sid={session_id}&locale={LOCALE}&tsm={pwd_ms}"
        )
        pwd_resp = await self._post_transmit(
            pwd_path,
            {
                "headers": [
                    {"type": "flow_id", "flow_id": flow_id},
                    {"type": "uid", "uid": uid},
                ],
                "data": {
                    "action": "authentication",
                    "assert": "authenticate",
                    "assertion_id": pwd_assertion_id,
                    "fch": challenge,
                    "data": {"password": str(password)},
                    "method": "password",
                },
            },
            ec_bundle,
        )
        sms_assertion_id = _extract_sms_assertion_id(pwd_resp.get("data"))
        if not sms_assertion_id:
            raise InvalidCredentialsError(
                pwd_resp.get("error_message") or "Pepper rejected the phone number or password"
            )

        otp_code = (await self.on_otp_request()).strip()
        if not otp_code or otp_code in (OTP_CANCEL_SENTINEL, "__OTP_CANCELLED__"):
            raise OtpCanceledError()

        otp_ms = int(time.time() * 1000)
        otp_path = (
            f"/api/v2/auth/assert?aid={AID}&did={device_id}"
            f"&sid={session_id}&locale={LOCALE}&tsm={otp_ms}"
        )
        otp_resp = await self._post_transmit(
            otp_path,
            {
                "headers": [
                    {"type": "flow_id", "flow_id": flow_id},
                    {"type": "uid", "uid": uid},
                ],
                "data": {
                    "action": "authentication",
                    "assert": "authenticate",
                    "assertion_id": sms_assertion_id,
                    "fch": challenge,
                    "data": {"otp": otp_code},
                    "method": "otp",
                },
            },
            ec_bundle,
        )
        token = (otp_resp.get("data") or {}).get("token")
        if not token:
            raise InvalidOtpError(
                otp_resp.get("error_message") or "Pepper rejected the verification code"
            )

        self.access_token = token
        self.refreshed_long_term_token = _encode_state(
            {
                "v": 1,
                "deviceId": device_id,
                "clientInstanceId": client_instance_id,
                "ecPrivateKeyPkcs8Base64": ec_bundle.pkcs8_b64,
                "token": token,
            }
        )

    async def _query_graphql(
        self,
        query_name: str,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert self.client is not None
        resp = await self.client.post(
            GRAPHQL_API_URL,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "authorization": self.access_token or "",
                "x-pepper-id": self.pepper_client_id,
                "x-user-id": self.local_user_id,
                "appversion": APP_VERSION_HEADER,
                "queryname": query_name,
                "x-transaction-id": str(uuid.uuid4()),
            },
            json={"query": query, "variables": variables or {}},
        )
        if resp.status_code >= 400:
            raise FinanceScraperError(
                f"Pepper GraphQL {query_name} failed with HTTP {resp.status_code}"
            )
        parsed = resp.json()
        if parsed.get("errors"):
            raise FinanceScraperError(
                str(parsed["errors"][0].get("message") or parsed["errors"][0])
            )
        return parsed.get("data") or {}

    async def fetch_data(self) -> None:
        """Fetch checking accounts, balances, and completed/pending transactions."""
        if not self.access_token:
            raise FinanceScraperError("Must login before fetching Pepper data")

        user_data = await self._query_graphql("UserDataV2", USER_DATA_V2_QUERY)
        raw_accounts = ((user_data.get("userDataV2") or {}).get("getUserDataV2") or {}).get(
            "customerAndAccounts", {}
        ).get("accounts") or []
        checking = [a for a in raw_accounts if a.get("accountCategory") == "CHECKING"]
        if not checking:
            checking = raw_accounts

        now = datetime.now(UTC)
        from_date = self.options.start_date or (now - timedelta(days=365)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d")

        accounts: list[Account] = []
        for raw_acct in checking:
            account_id = str(raw_acct.get("accountId") or "")
            account_num = str(raw_acct.get("accountNumber") or account_id)

            bal_data = await self._query_graphql(
                "fetchAccountBalance",
                FETCH_ACCOUNT_BALANCE_QUERY,
                {"accountId": account_id},
            )
            cur_bal = ((bal_data.get("accounts") or {}).get("balance") or {}).get("currentBalance")
            balance = float(cur_bal) if cur_bal is not None else None

            txns: list[Transaction] = []
            page_number = 1
            while True:
                txn_data = await self._query_graphql(
                    "Transactions",
                    TRANSACTIONS_QUERY,
                    {
                        "accountId": account_id,
                        "from": from_date,
                        "to": to_date,
                        "pageNumber": page_number,
                        "pageCount": PAGE_SIZE,
                    },
                )
                page_obj = (txn_data.get("accounts") or {}).get("oshTransactionsNew") or {}
                if page_number == 1:
                    for pt in page_obj.get("pendingTransactions") or []:
                        txns.append(self._map_txn(pt, TransactionStatus.PENDING))
                completed = page_obj.get("transactions") or []
                for ct in completed:
                    txns.append(self._map_txn(ct, TransactionStatus.COMPLETED))
                if len(completed) < PAGE_SIZE:
                    break
                page_number += 1

            accounts.append(
                Account(
                    account_number=account_num,
                    account_type=AccountType.BANK,
                    balance=balance,
                    currency="ILS",
                    txns=txns,
                )
            )

        self.accounts = accounts

    @staticmethod
    def _map_txn(raw: dict[str, Any], status: TransactionStatus) -> Transaction:
        amt = float(raw.get("transactionAmount") or 0.0)
        currency = str(raw.get("currency") or "ILS")
        desc = str(raw.get("title") or raw.get("description") or "").strip()
        bdate = str(raw.get("bookingDate") or "")
        edate = str(raw.get("effectiveDate") or bdate)
        ident = raw.get("transactionId") or raw.get("referenceNumber")
        return Transaction(
            identifier=str(ident) if ident else None,
            date=bdate,
            processed_date=edate or None,
            original_amount=amt,
            original_currency=currency,
            charged_amount=amt,
            description=desc,
            memo=str(raw["subTitle"]) if raw.get("subTitle") else None,
            status=status,
            type=TransactionType.NORMAL,
            raw_data=raw,
        )
