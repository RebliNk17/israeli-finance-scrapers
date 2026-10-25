"""Unified, provider-agnostic data models and JSON schema for Israeli pension & savings scrapers."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProductType(StrEnum):
    """Normalized Israeli long-term savings / pension product types."""

    PENSION = "pension"  # קרן פנסיה (מקיפה / משלימה / כללית / ותיקה)
    HISHTALMUT = "hishtalmut"  # קרן השתלמות
    GEMEL = "gemel"  # קופת גמל לתגמולים / קצבה
    GEMEL_INVESTMENT = "gemel_investment"  # קופת גמל להשקעה
    FINANCIAL_SAVINGS = "financial_savings"  # פוליסת חיסכון / השקעה
    PIZUIM = "pizuim"  # קופת פיצויים אישית
    CHILD_SAVINGS = "child_savings"  # חיסכון לכל ילד
    LIFE_SAVINGS = "life_savings"  # ביטוח חיים עם חיסכון / ביטוח מנהלים
    UNKNOWN = "unknown"


class PensionType(StrEnum):
    """Sub-type for pension funds."""

    MAKIFA = "makifa"  # פנסיה מקיפה
    MASHLIMA = "mashlima"  # פנסיה משלימה / כללית
    VATIKA = "vatika"  # פנסיה ותיקה
    OTHER = "other"


class PolicyStatus(StrEnum):
    """Lifecycle status of a policy/fund."""

    ACTIVE = "active"  # פעילה (הפקדות שוטפות או יתרה פעילה)
    INACTIVE = "inactive"  # מסולקת / מוקפאת (ללא הפקדות פעילות)
    EXPIRED = "expired"  # פגה / נפדתה


class EmploymentStatus(StrEnum):
    """Saver's employment status on the policy."""

    EMPLOYEE = "employee"  # שכיר
    SELF_EMPLOYED = "self_employed"  # עצמאי
    OTHER = "other"


class LoginResult(StrEnum):
    """Outcome of the authentication step."""

    SUCCESS = "success"
    INVALID_CREDENTIALS = "invalid_credentials"
    INVALID_OTP = "invalid_otp"
    ACCOUNT_BLOCKED = "account_blocked"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class InsuredProfile:
    """Normalized personal details of the policy owner."""

    id_number: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    birth_date: str | None = None  # YYYY-MM-DD
    gender: str | None = None  # "M" | "F" | None
    city: str | None = None
    street: str | None = None
    house_number: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class BalancePoint:
    """A single point in a fund or portfolio historical balance time-series."""

    date: str  # YYYY-MM-DD
    balance: float
    currency: str = "ILS"

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ExposureBucket:
    """An asset-allocation exposure slice."""

    id: str
    label: str
    percentage: float
    amount: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class AssetExposure:
    """Portfolio or fund-level asset exposure breakdown."""

    geographic: list[ExposureBucket] = field(default_factory=list)
    currency: list[ExposureBucket] = field(default_factory=list)
    equity_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "geographic": [b.to_dict() for b in self.geographic],
            "currency": [b.to_dict() for b in self.currency],
            "equity_pct": self.equity_pct,
        }


@dataclass
class PortfolioSummary:
    """High-level summary across all funds held at the provider."""

    total_balance: float
    liquid_balance: float | None = None
    currency: str = "ILS"
    balance_history: list[BalancePoint] = field(default_factory=list)
    asset_exposure: AssetExposure | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_balance": self.total_balance,
            "liquid_balance": self.liquid_balance,
            "currency": self.currency,
            "balance_history": [p.to_dict() for p in self.balance_history],
            "asset_exposure": self.asset_exposure.to_dict() if self.asset_exposure else None,
        }


@dataclass
class ManagementFees:
    from_deposit_pct: float | None = None
    from_savings_pct: float | None = None
    investment_expense_pct: float | None = None
    discount_valid_from: str | None = None
    discount_valid_until: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class InvestmentTrack:
    name: str
    code: str | None = None
    allocation_pct: float | None = None
    balance: float | None = None
    currency: str = "ILS"
    yield_ytd_pct: float | None = None
    yield_as_of_date: str | None = None
    fee_deposit_pct: float | None = None
    fee_savings_pct: float | None = None
    investment_expense_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class DepositTransaction:
    identifier: str | None
    date: str
    salary_month: str | None
    total_amount: float
    employee_amount: float | None = None
    employer_amount: float | None = None
    compensation_amount: float | None = None
    disability_amount: float | None = None
    insured_salary: float | None = None
    employer_name: str | None = None
    payment_method: str | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class MovementItem:
    """Raw line item from a yearly movement statement."""

    title: str
    subtitle: str | None = None
    amount: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class YearlyMovementSummary:
    year: str
    as_of_date: str | None = None
    opening_balance: float | None = None
    deposits: float | None = None
    withdrawals: float | None = None
    transfers_in: float | None = None
    transfers_out: float | None = None
    gains: float | None = None
    management_fees: float | None = None
    insurance_costs: float | None = None
    closing_balance: float | None = None
    items: list[MovementItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        res = dataclasses.asdict(self)
        res["items"] = [item.to_dict() for item in self.items]
        return res


@dataclass
class InsuranceCover:
    title: str
    description: str | None = None
    insured_amount: float | None = None
    monthly_cost: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ExpectedPayment:
    title: str
    subtitle: str | None = None
    amount: float | None = None
    currency: str = "ILS"

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class FundPolicy:
    policy_id: str
    raw_policy_id: str | None = None
    internal_account_id: str | None = None
    product_type: ProductType = ProductType.UNKNOWN
    pension_type: PensionType | None = None
    status: PolicyStatus = PolicyStatus.ACTIVE
    employment_status: EmploymentStatus | None = None

    name: str = ""
    manufacturer: str = ""
    employer_name: str | None = None
    agent_name: str | None = None

    balance: float = 0.0
    as_of_balance: float | None = None
    liquid_balance: float | None = None
    taxable_balance: float | None = None
    currency: str = "ILS"

    balance_date: str | None = None
    data_as_of_date: str | None = None
    establishment_date: str | None = None
    start_date: str | None = None
    liquidity_date: str | None = None
    is_independent: bool = False  # IRA / קופה בניהול אישי
    is_section_14: bool | None = None  # סעיף 14

    fees: ManagementFees = field(default_factory=ManagementFees)
    tracks: list[InvestmentTrack] = field(default_factory=list)
    deposits: list[DepositTransaction] = field(default_factory=list)
    yearly_movements: list[YearlyMovementSummary] = field(default_factory=list)
    insurance_covers: list[InsuranceCover] = field(default_factory=list)
    expected_payments: list[ExpectedPayment] = field(default_factory=list)
    balance_history: list[BalancePoint] = field(default_factory=list)
    asset_exposure: AssetExposure | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "raw_policy_id": self.raw_policy_id,
            "internal_account_id": self.internal_account_id,
            "product_type": self.product_type.value,
            "pension_type": self.pension_type.value if self.pension_type else None,
            "status": self.status.value,
            "employment_status": self.employment_status.value if self.employment_status else None,
            "name": self.name,
            "manufacturer": self.manufacturer,
            "employer_name": self.employer_name,
            "agent_name": self.agent_name,
            "balance": self.balance,
            "as_of_balance": self.as_of_balance,
            "liquid_balance": self.liquid_balance,
            "taxable_balance": self.taxable_balance,
            "currency": self.currency,
            "balance_date": self.balance_date,
            "data_as_of_date": self.data_as_of_date,
            "establishment_date": self.establishment_date,
            "start_date": self.start_date,
            "liquidity_date": self.liquidity_date,
            "fees": self.fees.to_dict(),
            "tracks": [t.to_dict() for t in self.tracks],
            "deposits": [d.to_dict() for d in self.deposits],
            "yearly_movements": [m.to_dict() for m in self.yearly_movements],
            "insurance_covers": [c.to_dict() for c in self.insurance_covers],
            "expected_payments": [p.to_dict() for p in self.expected_payments],
            "balance_history": [b.to_dict() for b in self.balance_history],
            "asset_exposure": self.asset_exposure.to_dict() if self.asset_exposure else None,
        }
