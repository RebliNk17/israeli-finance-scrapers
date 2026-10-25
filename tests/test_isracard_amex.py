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
