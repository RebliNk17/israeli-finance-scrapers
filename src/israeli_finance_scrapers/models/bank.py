"""Domain models for bank accounts, credit cards, and transactions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class AccountType(StrEnum):
    BANK = "bank"
    CREDIT_CARD = "credit_card"


class TransactionStatus(StrEnum):
    COMPLETED = "completed"
    PENDING = "pending"


class TransactionType(StrEnum):
    NORMAL = "normal"
    INSTALLMENTS = "installments"


@dataclass
class InstallmentsInfo:
    number: int
    total: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Transaction:
    identifier: str | None
    date: str  # ISO 8601 YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
    processed_date: str | None
    original_amount: float
    original_currency: str
    charged_amount: float
    description: str
    memo: str | None = None
    status: TransactionStatus = TransactionStatus.COMPLETED
    type: TransactionType = TransactionType.NORMAL
    installments: InstallmentsInfo | None = None
    category: str | None = None
    raw_data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        res = asdict(self)
        res["status"] = self.status.value
        res["type"] = self.type.value
        if self.installments is not None:
            res["installments"] = self.installments.to_dict()
        return res


@dataclass
class Account:
    account_number: str
    account_type: AccountType
    balance: float | None = None
    credit_limit: float | None = None
    open_to_buy: float | None = None
    currency: str = "ILS"
    txns: list[Transaction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_number": self.account_number,
            "account_type": self.account_type.value,
            "balance": self.balance,
            "credit_limit": self.credit_limit,
            "open_to_buy": self.open_to_buy,
            "currency": self.currency,
            "txns": [t.to_dict() for t in self.txns],
        }
