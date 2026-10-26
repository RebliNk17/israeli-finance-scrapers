"""Unit tests for IsracardScraper and AmexScraper."""

from __future__ import annotations

import json

import httpx
import pytest

from israeli_finance_scrapers import (
    AccountType,
    ScraperOptions,
    TransactionStatus,
    TransactionType,
    create_scraper,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["isracard", "amex"])
async def test_isracard_and_amex_mobile_scrape(provider: str) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if "serviceName=ValidateIdDataNoReg" in url:
            return httpx.Response(
                200,
                json={
                    "Header": {"Status": "1", "Message": []},
                    "ValidateIdDataNoRegBean": {
                        "returnCode": "1",
                        "userName": "IsraUser",
                        "bcKey": "bc-key-123",
                    },
                },
            )
        if "serviceName=performNewLogon" in url:
            return httpx.Response(
                200,
                json={
                    "Header": {"Status": "1", "Message": []},
                    "NewCustomerLogonBean": {"firstName": "ישראל", "lastName": "ישראלי"},
                },
            )
        if "serviceName=CardsList_102Digital" in url:
            return httpx.Response(
                200,
                json={
                    "Header": {"Status": "1", "Message": []},
                    "CardsList_102DigitalBean": {
                        "Table1": [
                            {
                                "cardNumber": "5678",
                                "cardName": "פלטינה",
                                "paymentDate": "10",
                                "activateInd": "1",
                            }
                        ]
                    },
                },
            )
        if "serviceName=RikuzNetuneyCreditDigi" in url:
            return httpx.Response(
                200,
                json={
                    "Header": {"Status": "1", "Message": []},
                    "RikuzNetuneyCreditDigiBean": {
                        "cardsTotal": [
                            {
                                "cardNumberTail": "5678",
                                "misgeretKolelet": "30,000.00",
                                "usedBalanceCredit": "4,500.00",
                                "yitraLeNitzul": "25,500.00",
                            }
                        ]
                    },
                },
            )
        if url.endswith("/GatewayV2"):
            body = json.loads(req.content.decode())
            bmonth = (body.get("Data") or {}).get("billingMonth") or ""
            if "/10/2026" in bmonth:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "approvals": {
                                "approvedTransactions": [
                                    {
                                        "purchaseDate": "20/10/2026",
                                        "businessName": "סופרמרקט לדוגמה",
                                        "originalAmount": 120.0,
                                        "ilsBillingAmount": 120.0,
                                        "currencyIso": "ILS",
                                        "seqConfirmationNumber": "conf-999",
                                        "branchCodeDescription": "מזון",
                                    }
                                ]
                            },
                            "israelAbroadVouchers": {
                                "vouchers": {
                                    "israelAbroadVouchersList": [
                                        {
                                            "purchaseDate": "05/10/2026",
                                            "businessName": "חנות אלקטרוניקה",
                                            "originalAmount": 1200.0,
                                            "billingAmount": 400.0,
                                            "originalCurrencyIso": "ILS",
                                            "moreInfo": "תשלום 1 מ 3",
                                            "currentInstallmentNum": 1,
                                            "numberOfInstallment": 3,
                                            "voucherNumber": 888777,
                                        }
                                    ]
                                }
                            },
                        }
                    },
                )
            return httpx.Response(200, json={"data": {}})
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scraper = create_scraper(
            provider,
            {"id": "123456789", "card6Digits": "123456", "password": "secret"},
            ScraperOptions(start_date="2026-10-01"),
            client=client,
        )
        res = await scraper.scrape()

    assert res.success is True
    assert len(res.accounts) == 1
    acc = res.accounts[0]
    assert acc.account_number == "5678"
    assert acc.account_type == AccountType.CREDIT_CARD
    assert acc.credit_limit == 30000.0
    assert acc.open_to_buy == 25500.0
    assert acc.balance == -4500.0
    assert len(acc.txns) == 2

    pending = next(t for t in acc.txns if t.status == TransactionStatus.PENDING)
    assert pending.identifier == "conf-999"
    assert pending.charged_amount == -120.0

    completed = next(t for t in acc.txns if t.status == TransactionStatus.COMPLETED)
    assert completed.identifier == "888777"
    assert completed.charged_amount == -400.0
    assert completed.original_amount == -1200.0
    assert completed.type == TransactionType.INSTALLMENTS
    assert completed.installments is not None
    assert (completed.installments.number, completed.installments.total) == (1, 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["isracard", "amex"])
async def test_isracard_and_amex_sms_otp_and_token_login(provider: str) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        body = json.loads(req.content.decode()) if req.content else {}
        if "serviceName=ValidateIdDataNoReg" in url:
            return httpx.Response(
                200,
                json={
                    "Header": {"Status": "1", "Message": []},
                    "ValidateIdDataNoRegBean": {
                        "returnCode": "1",
                        "userName": "IsraUser",
                        "bcKey": "bc-key-otp",
                    },
                },
            )
        if "serviceName=SendOTP" in url:
            return httpx.Response(
                200,
                json={
                    "Header": {"Status": "1", "Message": []},
                    "SendOTPBean": {"returnCode": "0", "smsMasked": "050-0****00"},
                },
            )
        if "serviceName=ValidateOTPNoReg" in url:
            assert body.get("otp") == "112233"
            return httpx.Response(
                200,
                json={
                    "Header": {"Status": "1", "Message": []},
                    "ValidateOTPNoRegBean": {"returnCode": "0"},
                },
            )
        if "serviceName=performLogonOtp" in url:
            return httpx.Response(
                200,
                json={
                    "Header": {"Status": "1", "Message": []},
                    "CustomerLogonBean": {"returnCode": "1"},
                },
            )
        if "serviceName=CustomerValidateKeyOtp" in url:
            if body.get("checkLevel") == "9":
                return httpx.Response(
                    200,
                    json={
                        "Header": {"Status": "1", "Message": []},
                        "CustomerValidateKeyOtpBean": {
                            "returnCode": "1",
                            "key": "minted-long-term-key",
                        },
                    },
                )
            if body.get("checkLevel") == "4":
                return httpx.Response(
                    200,
                    json={
                        "Header": {"Status": "1", "Message": []},
                        "CustomerValidateKeyOtpBean": {
                            "returnCode": "1",
                            "key": "rotated-long-term-key",
                            "idNumber": "000000018",
                            "userName": "IsraUser",
                        },
                    },
                )
        if "serviceName=CustomerDataRegistration" in url:
            return httpx.Response(
                200,
                json={
                    "Header": {"Status": "1", "Message": []},
                    "CustomerDataRegistrationBean": {"returnCode": "1"},
                },
            )
        if "serviceName=CardsList_102Digital" in url:
            return httpx.Response(
                200,
                json={
                    "Header": {"Status": "1", "Message": []},
                    "CardsList_102DigitalBean": {"Table1": []},
                },
            )
        return httpx.Response(200, json={})

    async def resolve_otp() -> str:
        return "112233"

    # 1. SMS OTP login mints a persistent udid:key long_term_token
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scraper1 = create_scraper(
            provider,
            {"id": "000000018", "card6Digits": "123456"},
            ScraperOptions(start_date="2026-10-01", otp_code_resolver=resolve_otp),
            client=client,
        )
        res1 = await scraper1.scrape()

    assert res1.success is True
    assert res1.long_term_token is not None
    assert res1.long_term_token.endswith(":minted-long-term-key")

    # 2. Subsequent login with otpLongTermToken succeeds without SMS or password
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client2:
        scraper2 = create_scraper(
            provider,
            {"id": "000000018", "card6Digits": "123456", "otpLongTermToken": res1.long_term_token},
            ScraperOptions(start_date="2026-10-01"),
            client=client2,
        )
        res2 = await scraper2.scrape()

    assert res2.success is True
    assert res2.long_term_token is not None
    assert res2.long_term_token.endswith(":rotated-long-term-key")
