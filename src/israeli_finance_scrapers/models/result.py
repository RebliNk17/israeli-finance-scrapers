"""Canonical scraping result model uniting banks, credit cards, and pension providers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from israeli_finance_scrapers.models.bank import Account
from israeli_finance_scrapers.models.pension import FundPolicy, InsuredProfile, PortfolioSummary


@dataclass
class ScrapingResult:
    """The canonical output returned by every scraper in `israeli-finance-scrapers`."""

    success: bool
    provider: str
    accounts: list[Account] = field(default_factory=list)
    funds: list[FundPolicy] = field(default_factory=list)
    portfolio_summary: PortfolioSummary | None = None
    insured: InsuredProfile | None = None
    long_term_token: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    scraped_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def refreshed_long_term_token(self) -> str | None:
        """Alias for long_term_token for backwards compatibility with pension scrapers."""
        return self.long_term_token

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "provider": self.provider,
            "accounts": [a.to_dict() for a in self.accounts],
            "funds": [f.to_dict() for f in self.funds],
            "portfolio_summary": self.portfolio_summary.to_dict()
            if self.portfolio_summary
            else None,
            "insured": self.insured.to_dict() if self.insured else None,
            "long_term_token": self.long_term_token,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "scraped_at": self.scraped_at,
        }

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
