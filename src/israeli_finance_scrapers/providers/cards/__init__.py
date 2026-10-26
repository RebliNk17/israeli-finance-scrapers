"""Credit card scrapers."""

from israeli_finance_scrapers.providers.cards.isracard_amex import (
    AmexScraper,
    IsracardScraper,
)
from israeli_finance_scrapers.providers.cards.max import MaxScraper
from israeli_finance_scrapers.providers.cards.visa_cal import VisaCalScraper

__all__ = ["AmexScraper", "IsracardScraper", "MaxScraper", "VisaCalScraper"]
