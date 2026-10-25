import json

import httpx
import pytest

from israeli_finance_scrapers.base.base_scraper import ScraperOptions
from israeli_finance_scrapers.models.bank import TransactionStatus
from israeli_finance_scrapers.providers.cards.visa_cal import VisaCalScraper


@pytest.mark.asyncio
async def test_visa_cal_login_and_scrape_success():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/Authentication/api/login/regularLogin" in url:
            return httpx.Response(
                200,
                json={
                    "statusCode": 1,
                    "result": {
                        "calConnectToken": "token123",
                        "temporaryGuid": "guid456",
                        "hash": "bio_hash_789",
                    },
                },
            )
        if "/Authentication/api/account/init" in url:
            return httpx.Response(
                200,
                json={
                    "statusCode": 1,
                    "result": {
                        "cards": [
                            {"cardUniqueId": "card_abc", "last4Digits": "1234"},
                        ]
                    },
                },
            )
        if "/Frames/api/Frames/GetTotalFrameStatus" in url:
            return httpx.Response(
                200,
                json={
                    "result": {
                        "calIssuedCards": {
                            "frameLimitForCardAmount": 15000.0,
                            "fictiveMaxAccAmt": 3000.0,
                            "cardLevelFrames": [
                                {
                                    "cardUniqueId": "card_abc",
                                    "nextTotalDebit": 1250.0,
                                    "nextDebitDate": "2026-11-02",
                                }
                            ],
                        }
                    }
                },
            )
        if "/Transactions/api/approvals/getClearanceRequests" in url:
            return httpx.Response(
                200,
                json={
                    "statusCode": 1,
                    "result": {
                        "cardsList": [
                            {
                                "cardUniqueID": "card_abc",
                                "authDetalisList": [
                                    {
                                        "authNum": "999",
                                        "trnPurchaseDate": "2026-10-24T18:00:00",
                                        "amount": 45.0,
                                        "currencySymbol": "₪",
                                        "merchantName": "Cafe Aroma",
                                    }
                                ],
                            }
                        ]
                    },
                },
            )
        if "/Transactions/api/transactionsDetails/getCardTransactionsDetails" in url:
            return httpx.Response(
                200,
                json={
                    "statusCode": 1,
                    "result": {
                        "bankAccounts": [
                            {
                                "debitDates": [
                                    {
                                        "date": "2026-10-02",
                                        "transactions": [
                                            {
                                                "trnIntId": "tx1",
                                                "trnPurchaseDate": "2026-09-28",
                                                "debCrdDate": "2026-10-02",
                                                "trnAmt": 320.0,
                                                "cashAccountTrnAmt": 320.0,
                                                "merchantName": "Shufersal",
                                                "debCrdCurrencySymbol": "₪",
                                                "trnTypeCode": "5",
                                            }
                                        ],
                                    }
                                ]
                            }
                        ]
                    },
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    scraper = VisaCalScraper(
        credentials={"username": "user", "password": "pw"},
        client=client,
    )

    result = await scraper.scrape()
    assert result.success is True
    assert result.provider == "visa_cal"
    assert result.long_term_token == "bio_hash_789"
    assert len(result.accounts) == 1

    account = result.accounts[0]
    assert account.account_number == "1234"
    assert account.balance == -1250.0
    assert account.balance_date == "2026-11-02"
    assert account.credit_limit == 15000.0
    assert account.open_to_buy == 12000.0
    assert len(account.txns) == 2

    # Check pending
    pending = [t for t in account.txns if t.status == TransactionStatus.PENDING]
    assert len(pending) == 1
    assert pending[0].description == "Cafe Aroma"
    assert pending[0].charged_amount == 45.0

    # Check completed
    completed = [t for t in account.txns if t.status == TransactionStatus.COMPLETED]
    assert len(completed) == 1
    assert completed[0].description == "Shufersal"
    assert completed[0].charged_amount == 320.0


@pytest.mark.asyncio
async def test_visa_cal_frames_requested_per_card():
    frames_by_card = {
        # Bank-issued card-level frame wins over the cal group's account total.
        "card_a": {
            "bankIssuedCards": {
                "frameLimitForCardAmount": 10000.0,
                "fictiveMaxAccAmt": 2000.0,
                "cardLevelFrames": [
                    {
                        "cardUniqueId": "card_a",
                        "nextTotalDebit": 1713.08,
                        "nextDebitDate": "2026-11-10T00:00:00",
                    }
                ],
            },
            "calIssuedCards": {"nextTotalDebitForAccount": 999.0},
        },
        # A zero charge is real, not a reason to fall back to the account total.
        "card_b": {
            "calIssuedCards": {
                "nextTotalDebitForAccount": 417.9,
                "cardLevelFrames": [
                    {
                        "cardUniqueId": "card_b",
                        "nextTotalDebit": 0,
                        "nextDebitDate": "2026-11-02T00:00:00",
                    }
                ],
            }
        },
        # No frame for this card: use its own response's total, never another card's frame.
        "card_c": {
            "calIssuedCards": {
                "nextTotalDebitForAccount": 17.9,
                "nextTotalDebitDateForAccount": "2026-11-02T00:00:00",
                "cardLevelFrames": [{"cardUniqueId": "card_a", "nextTotalDebit": 1713.08}],
            }
        },
    }
    frame_requests: list[list[dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/Authentication/api/login/regularLogin" in url:
            return httpx.Response(200, json={"statusCode": 1, "result": {"calConnectToken": "t"}})
        if "/Authentication/api/account/init" in url:
            cards = [
                {"cardUniqueId": cid, "last4Digits": last4}
                for cid, last4 in (("card_a", "1111"), ("card_b", "2222"), ("card_c", "3333"))
            ]
            return httpx.Response(200, json={"statusCode": 1, "result": {"cards": cards}})
        if "/Frames/api/Frames/GetTotalFrameStatus" in url:
            cards = json.loads(request.content)["cardsForFrameData"]
            frame_requests.append(cards)
            return httpx.Response(200, json={"result": frames_by_card[cards[0]["cardUniqueId"]]})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scraper = VisaCalScraper(credentials={"username": "u", "password": "p"}, client=client)

    result = await scraper.scrape()
    assert result.success is True
    assert frame_requests == [
        [{"cardUniqueId": "card_a"}],
        [{"cardUniqueId": "card_b"}],
        [{"cardUniqueId": "card_c"}],
    ]

    by_num = {a.account_number: a for a in result.accounts}
    assert by_num["1111"].balance == -1713.08
    assert by_num["1111"].balance_date == "2026-11-10"
    assert by_num["1111"].credit_limit == 10000.0
    assert by_num["1111"].open_to_buy == 8000.0
    assert by_num["2222"].balance == 0
    assert by_num["2222"].balance_date == "2026-11-02"
    assert by_num["3333"].balance == -17.9
    assert by_num["3333"].balance_date == "2026-11-02"
    assert by_num["3333"].to_dict()["balance_date"] == "2026-11-02"


@pytest.mark.asyncio
async def test_visa_cal_invalid_password():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"statusCode": 4, "statusDescription": "Invalid credentials"}
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    scraper = VisaCalScraper(
        credentials={"username": "bad", "password": "wrong"},
        client=client,
    )

    result = await scraper.scrape()
    assert result.success is False
    assert result.error_type == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_visa_cal_sms_otp_login_and_long_term_token():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/Authentication/api/login/sendOTP" in url:
            return httpx.Response(
                200,
                json={
                    "statusCode": 1,
                    "result": {"token": "otp-session-token-1", "phoneNumber": "050-*****99"},
                },
            )
        if "/Authentication/api/login/verifyOTP" in url:
            return httpx.Response(
                200,
                json={
                    "statusCode": 1,
                    "result": {
                        "calConnectToken": "token_from_otp",
                        "temporaryGuid": "guid_from_otp",
                        "hash": "bio_hash_from_otp",
                    },
                },
            )
        if "/Authentication/api/account/init" in url:
            return httpx.Response(200, json={"statusCode": 1, "result": {"cards": []}})
        return httpx.Response(404)

    async def resolve_otp() -> str:
        return "654321"

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    scraper = VisaCalScraper(
        credentials={"id": "000000018", "card4Digits": "1234"},
        options=ScraperOptions(otp_code_resolver=resolve_otp),
        client=client,
    )

    result = await scraper.scrape()
    assert result.success is True
    assert result.long_term_token == "bio_hash_from_otp"
