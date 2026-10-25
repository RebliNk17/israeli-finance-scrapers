import json

from israeli_finance_scrapers.models import (
    Account,
    AccountType,
    FundPolicy,
    InstallmentsInfo,
    ManagementFees,
    ProductType,
    ScrapingResult,
    Transaction,
    TransactionStatus,
    TransactionType,
)


def test_bank_models_to_dict():
    txn = Transaction(
        identifier="12345",
        date="2026-10-24",
        processed_date="2026-10-25",
        original_amount=150.0,
        original_currency="ILS",
        charged_amount=150.0,
        description="Super-Pharm",
        status=TransactionStatus.COMPLETED,
        type=TransactionType.INSTALLMENTS,
        installments=InstallmentsInfo(number=1, total=3),
    )
    acc = Account(
        account_number="1234",
        account_type=AccountType.CREDIT_CARD,
        balance=-150.0,
        credit_limit=10000.0,
        open_to_buy=9850.0,
        txns=[txn],
    )
    result = ScrapingResult(
        success=True,
        provider="visa_cal",
        accounts=[acc],
        long_term_token="token_xyz",
    )

    d = result.to_dict()
    assert d["success"] is True
    assert d["provider"] == "visa_cal"
    assert len(d["accounts"]) == 1
    assert d["accounts"][0]["account_number"] == "1234"
    assert d["accounts"][0]["account_type"] == "credit_card"
    assert d["accounts"][0]["txns"][0]["description"] == "Super-Pharm"
    assert d["accounts"][0]["txns"][0]["installments"] == {"number": 1, "total": 3}

    json_str = result.to_json(indent=2)
    parsed = json.loads(json_str)
    assert parsed["accounts"][0]["balance"] == -150.0


def test_pension_models_to_dict():
    fund = FundPolicy(
        policy_id="98765",
        name="הפניקס פנסיה",
        product_type=ProductType.PENSION,
        balance=250000.0,
        fees=ManagementFees(from_deposit_pct=1.5, from_savings_pct=0.15),
    )
    result = ScrapingResult(
        success=True,
        provider="haphoenix",
        funds=[fund],
    )
    d = result.to_dict()
    assert d["success"] is True
    assert len(d["funds"]) == 1
    assert d["funds"][0]["policy_id"] == "98765"
    assert d["funds"][0]["fees"]["from_deposit_pct"] == 1.5
