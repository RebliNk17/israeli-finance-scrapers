import pytest

from israeli_finance_scrapers import (
    PROVIDERS,
    HaPhoenixScraper,
    MigdalScraper,
    OneZeroScraper,
    ScraperOptions,
    VisaCalScraper,
    create_scraper,
)


def test_create_scraper_providers():
    cal = create_scraper("visa_cal", {"username": "u", "password": "p"})
    assert isinstance(cal, VisaCalScraper)

    cal_alias = create_scraper("cal", {"username": "u", "password": "p"})
    assert isinstance(cal_alias, VisaCalScraper)

    onezero = create_scraper("onezero", {"phoneNumber": "0501234567"})
    assert isinstance(onezero, OneZeroScraper)

    phoenix = create_scraper("haphoenix", {"id": "123", "phoneNumber": "050"})
    assert isinstance(phoenix, HaPhoenixScraper)

    migdal = create_scraper("migdal", {"id": "123", "phoneNumber": "050"})
    assert isinstance(migdal, MigdalScraper)


def test_create_scraper_invalid():
    with pytest.raises(ValueError, match="Unknown finance provider"):
        create_scraper("non_existent_bank", {})


def test_create_scraper_with_options():
    opts = ScraperOptions(timeout=45.0, start_date="2026-01-01")
    s = create_scraper("cal", {"username": "u", "password": "p"}, options=opts)
    assert s.options.timeout == 45.0
    assert s.options.start_date == "2026-01-01"


def test_providers_registry():
    assert "visa_cal" in PROVIDERS
    assert "onezero" in PROVIDERS
    assert "haphoenix" in PROVIDERS
    assert "migdal" in PROVIDERS
    assert PROVIDERS["visa_cal"].category == "credit_card"
    assert PROVIDERS["onezero"].category == "bank"
    assert PROVIDERS["haphoenix"].category == "pension"
