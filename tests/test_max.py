"""Unit tests for MaxScraper."""

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
async def test_max_registered_device_login_and_scrape() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/C391/post"):
            return httpx.Response(200, json={"DO": {}, "CR": {"RS": 0, "MId": 391}})
        if path.endswith("/C305/post"):
            return httpx.Response(
                200,
                json={
                    "DO": {
                        "Gen": {
                            "UAuth": True,
                            "Status": 0,
                            "RC": 0,
                            "NewSId": "sid-rotated-1",
                        },
                        "DLCards": [
                            {
                                "Index": 0,
                                "Number": "1234",
                                "Name": "max executive",
                                "Balance": "יתרת מסגרת:\n₪6,000.00 מתוך ₪10,000.00",
                            }
                        ],
                    },
                    "CR": {"RS": 0, "MId": 305},
                },
            )
        if path.endswith("/C382/post"):
            body = json.loads(req.content.decode())
            month = (body.get("vars") or {}).get("month")
            if month == "102026":
                return httpx.Response(
                    200,
                    json={
                        "DO": {
                            "Gen": {"Status": 0, "RC": 0},
                            "Trans": {
                                "ListCycleDate": [
                                    {"Type": 1, "TotalTitle": "חיוב ב-10.10.26"},
                                    {
                                        "Type": 0,
                                        "CNum": "1234",
                                        "TId": "arn-111",
                                        "OriginalARN": "arn-111",
                                        "MerchantDescription": "חנות לדוגמה",
                                        "CName": "מזון",
                                        "PaymentCurrency": 376,
                                        "PaymentDate": "2026-10-10 00:00:00",
                                        "PurchaseDateTime": "2026-09-28T10:00:00",
                                        "ActualPayment": "₪150.00",
                                        "OriginalAmountDouble": 450.0,
                                        "PlanDesc": "תשלומים",
                                        "Comments": "תשלום 1 מתוך 3",
                                    },
                                ],
                                "ListApprovals": [
                                    {
                                        "Type": 0,
                                        "CNum": "1234",
                                        "TId": "arn-222",
                                        "OriginalARN": "arn-222",
                                        "MerchantDescription": "קפה לדוגמה",
                                        "CName": "מסעדות",
                                        "PaymentCurrency": 376,
                                        "PurchaseDateTime": "2026-10-20T09:00:00",
                                        "ActualPayment": "₪22.50",
                                        "OriginalAmountDouble": 22.5,
                                        "PlanDesc": "רגילה",
                                        "Comments": "",
                                    }
                                ],
                            },
                        },
                        "CR": {"RS": 0, "MId": 382},
                    },
                )
            return httpx.Response(200, json={"DO": {"Trans": {}}, "CR": {"RS": 0, "MId": 382}})
        return httpx.Response(200, json={"DO": {}, "CR": {"RS": 0}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scraper = create_scraper(
            "max",
            {"username": "user@example.com", "password": "secret"},
            ScraperOptions(start_date="2026-09-01"),
            client=client,
        )
        res = await scraper.scrape()

    assert res.success is True
    assert len(res.accounts) == 1
    acc = res.accounts[0]
    assert acc.account_number == "1234"
    assert acc.account_type == AccountType.CREDIT_CARD
    assert acc.credit_limit == 10000.0
    assert acc.open_to_buy == 6000.0
    assert acc.balance == -4000.0
    assert len(acc.txns) == 2

    t0 = acc.txns[0]
    assert t0.identifier == "arn-111"
    assert t0.charged_amount == -150.0
    assert t0.original_amount == -450.0
    assert t0.type == TransactionType.INSTALLMENTS
    assert t0.installments is not None
    assert (t0.installments.number, t0.installments.total) == (1, 3)

    t1 = acc.txns[1]
    assert t1.status == TransactionStatus.PENDING
    assert t1.charged_amount == -22.5


@pytest.mark.asyncio
async def test_max_sms_otp_and_8_digit_card_login() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        body = json.loads(req.content.decode()) if req.content else {}
        if path.endswith("/C391/post"):
            return httpx.Response(200, json={"DO": {}, "CR": {"RS": 0, "MId": 391}})
        if path.endswith("/C703/post"):
            return httpx.Response(
                200, json={"DO": {"Gen": {"Status": 0, "RC": 0}}, "CR": {"RS": 0, "MId": 703}}
            )
        if path.endswith("/C704/post"):
            assert (body.get("vars") or {}).get("uId") == "000000018"
            return httpx.Response(
                200, json={"DO": {"Gen": {"Status": 0, "RC": 0}}, "CR": {"RS": 0, "MId": 704}}
            )
        if path.endswith("/C705/post"):
            vars_obj = body.get("vars") or {}
            assert vars_obj.get("cNum") == "12345678"
            assert vars_obj.get("code") == "55443"
            return httpx.Response(
                200,
                json={
                    "DO": {
                        "DO305": {
                            "Gen": {
                                "UAuth": True,
                                "Status": 0,
                                "RC": 0,
                                "NewSId": "sid-from-705",
                            },
                            "DLCards": [
                                {
                                    "Index": 0,
                                    "Number": "5678",
                                    "Name": "max card",
                                    "Balance": "יתרת מסגרת:\n₪8,000.00 מתוך ₪10,000.00",
                                }
                            ],
                        }
                    },
                    "CR": {"RS": 0, "MId": 705},
                },
            )
        if path.endswith("/C382/post"):
            return httpx.Response(200, json={"DO": {"Trans": {}}, "CR": {"RS": 0, "MId": 382}})
        return httpx.Response(200, json={"DO": {}, "CR": {"RS": 0}})

    async def resolve_otp() -> str:
        return "55443"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scraper = create_scraper(
            "max",
            {"id": "000000018", "card8Digits": "12345678"},
            ScraperOptions(start_date="2026-10-01", otp_code_resolver=resolve_otp),
            client=client,
        )
        res = await scraper.scrape()

    assert res.success is True
    assert len(res.accounts) == 1
    assert res.accounts[0].account_number == "5678"
    assert res.accounts[0].balance == -2000.0
