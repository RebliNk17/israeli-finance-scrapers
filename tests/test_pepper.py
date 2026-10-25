"""Unit tests for PepperScraper (`com.pepper.ldb`)."""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest

from israeli_finance_scrapers import (
    AccountType,
    ScraperOptions,
    TransactionStatus,
    create_scraper,
)


def _make_fresh_jwt() -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode("ascii").rstrip("=")
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 3600}).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    return f"{header}.{payload}.sig"


@pytest.mark.asyncio
async def test_pepper_saved_jwt_and_graphql_scrape() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        qname = req.headers.get("queryname")
        if qname == "UserDataV2":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "userDataV2": {
                            "getUserDataV2": {
                                "customerAndAccounts": {
                                    "customerId": "cust-1",
                                    "accounts": [
                                        {
                                            "accountId": "acc-1",
                                            "accountNumber": "12-857-123456",
                                            "accountCategory": "CHECKING",
                                        }
                                    ],
                                }
                            }
                        }
                    }
                },
            )
        if qname == "fetchAccountBalance":
            return httpx.Response(
                200,
                json={"data": {"accounts": {"balance": {"currentBalance": 12500.75}}}},
            )
        if qname == "Transactions":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "accounts": {
                            "oshTransactionsNew": {
                                "totalCount": 1,
                                "pendingTransactions": [],
                                "transactions": [
                                    {
                                        "transactionId": "tx-100",
                                        "transactionAmount": -85.0,
                                        "bookingDate": "2026-10-15",
                                        "effectiveDate": "2026-10-15",
                                        "currency": "ILS",
                                        "title": "העברה בביט",
                                        "subTitle": "לחבר",
                                    }
                                ],
                            }
                        }
                    }
                },
            )
        return httpx.Response(200, json={"data": {}})

    jwt_tok = _make_fresh_jwt()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scraper = create_scraper(
            "pepper",
            {
                "phoneNumber": "0501234567",
                "password": "secret",
                "otpLongTermToken": jwt_tok,
            },
            ScraperOptions(start_date="2026-10-01"),
            client=client,
        )
        res = await scraper.scrape()

    assert res.success is True
    assert len(res.accounts) == 1
    acc = res.accounts[0]
    assert acc.account_number == "12-857-123456"
    assert acc.account_type == AccountType.BANK
    assert acc.balance == 12500.75
    assert len(acc.txns) == 1
    assert acc.txns[0].identifier == "tx-100"
    assert acc.txns[0].charged_amount == -85.0
    assert acc.txns[0].status == TransactionStatus.COMPLETED
