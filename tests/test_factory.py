import pytest

from israeli_finance_scrapers import (
    PROVIDERS,
    AmexScraper,
    HaPhoenixScraper,
    IsracardScraper,
    MaxScraper,
    MigdalScraper,
    OneZeroScraper,
    PepperScraper,
    ScraperOptions,
    VisaCalScraper,
    create_scraper,
)


def test_create_scraper_providers():
    cal = create_scraper("visa_cal", {"username": "u", "password": "p"})
    assert isinstance(cal, VisaCalScraper)

    cal_alias = create_scraper("cal", {"username": "u", "password": "p"})
    assert isinstance(cal_alias, VisaCalScraper)

    max_s = create_scraper("max", {"username": "u", "password": "p"})
    assert isinstance(max_s, MaxScraper)

    isracard = create_scraper("isracard", {"id": "123", "card6Digits": "123456", "password": "p"})
    assert isinstance(isracard, IsracardScraper)

    amex = create_scraper("amex", {"id": "123", "card6Digits": "123456", "password": "p"})
    assert isinstance(amex, AmexScraper)

    onezero = create_scraper("onezero", {"phoneNumber": "0501234567"})
    assert isinstance(onezero, OneZeroScraper)

    pepper = create_scraper("pepper", {"phoneNumber": "0501234567", "password": "p"})
    assert isinstance(pepper, PepperScraper)

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
    assert set(PROVIDERS) == {
        "onezero",
        "pepper",
        "visa_cal",
        "max",
        "isracard",
        "amex",
        "haphoenix",
        "migdal",
    }
    assert PROVIDERS["visa_cal"].category == "credit_card"
    assert PROVIDERS["max"].category == "credit_card"
    assert PROVIDERS["isracard"].category == "credit_card"
    assert PROVIDERS["amex"].category == "credit_card"
    assert PROVIDERS["onezero"].category == "bank"
    assert PROVIDERS["pepper"].category == "bank"
    assert PROVIDERS["haphoenix"].category == "pension"
    assert PROVIDERS["migdal"].category == "pension"
