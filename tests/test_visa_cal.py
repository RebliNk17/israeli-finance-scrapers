import json

import httpx
import pytest

from israeli_finance_scrapers.base.base_scraper import ScraperOptions
from israeli_finance_scrapers.models.bank import TransactionStatus
from israeli_finance_scrapers.providers.cards.visa_cal import VisaCalScraper


def _cal_txn(tid: str, merchant: str, code: str, trn_amt: float, billed: float, **extra) -> dict:
    return {
        "trnIntId": tid,
        "trnPurchaseDate": "2026-09-28",
        "debCrdDate": "2026-10-02",
        "trnAmt": trn_amt,
        "cashAccountTrnAmt": 0.0,
        "amtBeforeConvAndIndex": billed,
        "merchantName": merchant,
        "trnCurrencySymbol": "₪",
        "debCrdCurrencySymbol": "₪",
        "trnTypeCode": code,
        **extra,
    }


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
                                        "trnAmt": 45.0,
                                        "trnCurrencySymbol": "₪",
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
                                        # Real shapes: trnAmt unsigned in the purchase currency,
                                        # amtBeforeConvAndIndex the signed shekel bill,
                                        # cashAccountTrnAmt 0 throughout.
                                        "date": "2026-10-02",
                                        "transactions": [
                                            _cal_txn("tx1", "Shufersal", "5", 320.0, 320.0),
                                            _cal_txn("tx2", "Shufersal refund", "6", 50.0, -50.0),
                                            _cal_txn("tx3", "Fee refund", "71", 9.54, -9.54),
                                            _cal_txn(
                                                "tx4",
                                                "aliexpress",
                                                "5",
                                                67.49,
                                                209.81,
                                                trnCurrencySymbol="$",
                                            ),
                                            _cal_txn(
                                                "tx5",
                                                "Samsung",
                                                "8",
                                                8362.5,
                                                232.0,
                                                curPaymentNum=4,
                                                numOfPayments=36,
                                            ),
                                            _cal_txn("tx6", "CashCal", "6", 13.26, 0.0),
                                            _cal_txn(  # issue #2: foreign cash withdrawal
                                                "tx7",
                                                "SEVEN BANK",
                                                "7",
                                                10000.0,
                                                195.0,
                                                trnCurrencySymbol="JPY",
                                                curPaymentNum=0,
                                                numOfPayments=0,
                                            ),
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
    assert len(account.txns) == 8

    # A charge is negative (Cal reports purchases as positive amounts), a refund positive.
    pending = [t for t in account.txns if t.status == TransactionStatus.PENDING]
    assert len(pending) == 1
    assert pending[0].description == "Cafe Aroma"
    assert (pending[0].charged_amount, pending[0].original_amount) == (-45.0, -45.0)

    completed = {t.description: t for t in account.txns if t.status == TransactionStatus.COMPLETED}
    amounts = {
        d: (t.charged_amount, t.original_amount, t.original_currency) for d, t in completed.items()
    }
    assert amounts == {
        "Shufersal": (-320.0, -320.0, "ILS"),
        "Shufersal refund": (50.0, 50.0, "ILS"),
        "Fee refund": (9.54, 9.54, "ILS"),
        "aliexpress": (-209.81, -67.49, "USD"),  # billed in shekels, bought in dollars
        "Samsung": (-232.0, -8362.5, "ILS"),  # this statement's installment, not the purchase
        "CashCal": (0.0, 13.26, "ILS"),  # a club accrual: nothing billed
        "SEVEN BANK": (-195.0, -10000.0, "JPY"),  # billed in shekels, withdrawn in yen
    }


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


def test_visa_cal_foreign_currency_is_billed_in_shekels():
    """Issue #2: a JPY cash withdrawal is reported in yen and billed in shekels."""
    scraper = VisaCalScraper({"username": "u", "password": "p"})
    raw = {
        "trnIntId": "xxx",
        "trnNumaretor": 2,
        "merchantName": "SEVEN BANK",
        "trnPurchaseDate": "2026-10-01T00:00:00",
        "trnAmt": 10000.0,
        "trnCurrencySymbol": "JPY",
        "trnType": "משיכת מזומן",
        "trnTypeCode": "7",
        "debCrdDate": "2026-11-02T00:00:00",
        "amtBeforeConvAndIndex": 195.0,
        "debCrdCurrencySymbol": "₪",
        "curPaymentNum": 0,
        "numOfPayments": 0,
        "cashAccountTrnAmt": 0.0,
    }
    txn = scraper._parse_completed_txn(raw, None)
    assert txn.original_amount == -10000.0
    assert txn.original_currency == "JPY"
    assert txn.charged_amount == -195.0
    assert txn.category == "משיכת מזומן"
    assert txn.installments is None
