# israeli-finance-scrapers

[![PyPI version](https://img.shields.io/pypi/v/israeli-finance-scrapers.svg)](https://pypi.org/project/israeli-finance-scrapers/)
[![Python versions](https://img.shields.io/pypi/pyversions/israeli-finance-scrapers.svg)](https://pypi.org/project/israeli-finance-scrapers/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Unified, modern async Python library to scrape Israeli banks, credit cards, and pension providers.

**Browserless First**: Wherever possible, scrapers connect directly to mobile and web REST/GraphQL APIs with pure HTTP (`httpx`), requiring no heavy headless browsers (no Puppeteer, no Chromium, no Playwright).

---

## Supported Providers

| Provider Key | Institution | Hebrew Name | Category | Auth Flow |
|---|---|---|---|---|
| `onezero` | One Zero Bank | וואן זירו | Bank | GraphQL API + mTLS, SMS OTP + 10-year `otpLongTermToken` (`idToken`) |
| `pepper` | Pepper Bank | פפר | Bank | Transmit Security v2 + GraphQL (`phoneNumber` + `password`), SMS OTP + persistent `otpLongTermToken` |
| `visa_cal` | Visa Cal | ויזה כאל | Credit Card | Mobile REST API (`username` + `password` OR `id` + `card4Digits` SMS OTP) + persistent `otpLongTermToken` (`bioLogin`) |
| `max` | Max (Leumi Card) | מקס | Credit Card | Mobile REST API (`lcapi`, `username` + `password`) + persistent device fingerprint (`otpLongTermToken`) |
| `isracard` | Isracard | ישראכרט | Credit Card | Mobile REST API (`ring.isracard.co.il`, `id` + `card6Digits` + `password` OR SMS OTP) + persistent `otpLongTermToken` |
| `amex` | American Express IL | אמריקן אקספרס | Credit Card | Mobile REST API (`ring.americanexpress.co.il`, `id` + `card6Digits` + `password` OR SMS OTP) + persistent `otpLongTermToken` |
| `haphoenix` | The Phoenix | הפניקס | Pension & Savings | SMS OTP (`id` + `phoneNumber`) + 6-month `otpLongTermToken` |
| `migdal` | Migdal | מגדל | Pension & Savings | SMS OTP (`id` + `phoneNumber`) + AES-CBC `otpLongTermToken` |

*(Additional bank and card providers are actively being added! PRs welcome.)*

---

## Installation

Using `pip`:
```bash
pip install israeli-finance-scrapers
```

Using `uv`:
```bash
uv add israeli-finance-scrapers
```

*(Requires Python 3.11+)*

---

## Quickstart

### 1. Scraping Credit Cards (e.g. Visa Cal)

```python
import asyncio
from israeli_finance_scrapers import create_scraper


async def main():
    scraper = create_scraper(
        provider="visa_cal",
        credentials={
            "username": "your_username",
            "password": "your_password",
            # Or use bioLogin token on subsequent runs:
            # "otpLongTermToken": "saved_hash",
        },
    )

    result = await scraper.scrape()

    if not result.success:
        print(f"Failed: {result.error_type} - {result.error_message}")
        return

    for account in result.accounts:
        print(f"💳 Card ending in {account.account_number}")
        print(f"   Balance: ₪{account.balance}")
        print(f"   Credit Limit: ₪{account.credit_limit}")
        print(f"   Transactions: {len(account.txns)}")

        for txn in account.txns[:5]:
            print(f"   - {txn.date}: {txn.description} (₪{txn.charged_amount})")

    # Save the token to skip username/password next time!
    if result.long_term_token:
        print(f"🔑 Saved long-term token: {result.long_term_token}")


asyncio.run(main())
```

### 2. Scraping Banks (e.g. One Zero)

```python
import asyncio
from israeli_finance_scrapers import create_scraper


async def prompt_otp() -> str:
    return input("Enter the SMS verification code: ").strip()


async def main():
    scraper = create_scraper(
        provider="onezero",
        credentials={
            "phoneNumber": "0501234567",
            # Or use 10-year idToken on subsequent runs:
            # "otpLongTermToken": "saved_id_token",
        },
    )
    scraper.on_otp_request = prompt_otp

    result = await scraper.scrape()

    for account in result.accounts:
        print(f"🏦 Account: {account.account_number} (Balance: ₪{account.balance})")
        for txn in account.txns[:5]:
            print(f"   - {txn.date}: {txn.description} (₪{txn.charged_amount})")


asyncio.run(main())
```

### 3. Scraping Pensions & Education Funds (e.g. Phoenix or Migdal)

```python
import asyncio
from israeli_finance_scrapers import create_scraper


async def prompt_otp() -> str:
    return input("Enter SMS OTP code: ").strip()


async def main():
    scraper = create_scraper(
        provider="haphoenix",  # or "migdal"
        credentials={
            "id": "123456789",
            "phoneNumber": "0501234567",
        },
    )
    scraper.on_otp_request = prompt_otp

    result = await scraper.scrape()

    print(f"💰 Total Balance: ₪{result.portfolio_summary.total_balance:,.2f}")
    for fund in result.funds:
        print(f"📂 {fund.name} ({fund.product_type}): ₪{fund.balance:,.2f}")


asyncio.run(main())
```

---

## Unified JSON Schema

Every scraper returns a `ScrapingResult` (`.to_dict()` / `.to_json()`):

```json
{
  "success": true,
  "provider": "visa_cal",
  "accounts": [
    {
      "account_number": "1234",
      "account_type": "credit_card",
      "balance": -1250.0,
      "credit_limit": 15000.0,
      "open_to_buy": 12000.0,
      "currency": "ILS",
      "txns": [
        {
          "identifier": "999",
          "date": "2026-10-24",
          "processed_date": null,
          "original_amount": 45.0,
          "original_currency": "ILS",
          "charged_amount": 45.0,
          "description": "Cafe Aroma",
          "status": "pending",
          "type": "normal"
        }
      ]
    }
  ],
  "funds": [],
  "portfolio_summary": null,
  "long_term_token": "hash_or_token"
}
```

---

## License

This project is licensed under the [Apache-2.0 License](LICENSE).
