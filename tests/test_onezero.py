import httpx
import pytest

from israeli_finance_scrapers.models.bank import AccountType, TransactionStatus
from israeli_finance_scrapers.providers.banks.onezero import OneZeroScraper


@pytest.mark.asyncio
async def test_onezero_login_with_stored_token_and_scrape():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/tokens/accessToken" in url:
            return httpx.Response(
                200,
                json={"resultData": {"accessToken": "onezero_access_123"}},
            )
        if "graphql" in url:
            body = request.read().decode("utf-8")
            if "GetCustomer" in body or "GetPortfolios" in body:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "portfolios": [
                                {
                                    "accountId": "10-800-123456",
                                    "accountType": "CURRENT",
                                    "currency": "ILS",
                                }
                            ]
                        }
                    },
                )
            if "GetMovements" in body:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "movements": {
                                "movements": [
                                    {
                                        "movementId": "mov-001",
                                        "movementTimestamp": "2026-10-24T12:00:00Z",
                                        "valueDate": "2026-10-24",
                                        "movementAmount": 250.0,
                                        "movementCurrency": "ILS",
                                        "description": "משכורת",
                                        "creditDebit": "CREDIT",
                                        "runningBalance": 12500.0,
                                    }
                                ],
                                "pagination": {"cursor": None, "hasMore": False},
                            }
                        }
                    },
                )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    scraper = OneZeroScraper(
        credentials={"otpLongTermToken": "stored_id_token"},
        client=client,
    )

    result = await scraper.scrape()
    assert result.success is True
    assert result.provider == "onezero"
    assert len(result.accounts) == 1

    acc = result.accounts[0]
    assert acc.account_number == "10-800-123456"
    assert acc.account_type == AccountType.BANK
    assert acc.balance == 12500.0
    assert len(acc.txns) == 1
    assert acc.txns[0].charged_amount == 250.0
    assert acc.txns[0].description == "משכורת"
    assert acc.txns[0].status == TransactionStatus.COMPLETED
