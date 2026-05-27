from datetime import date, datetime

from myQuant.news_ingestion.calendar import available_at_to_trading_date, is_trading_day, next_trading_day


def test_saturday_maps_to_monday():
    assert next_trading_day(date(2026, 5, 23)) == date(2026, 5, 25)


def test_sunday_maps_to_monday():
    assert next_trading_day(date(2026, 5, 24)) == date(2026, 5, 25)


def test_friday_maps_to_friday():
    assert next_trading_day(date(2026, 5, 22)) == date(2026, 5, 22)


def test_holiday_maps_to_next_trading_day():
    result = next_trading_day(date(2026, 1, 1))
    assert result >= date(2026, 1, 2)
    assert is_trading_day(result)


def test_is_trading_day_weekday():
    assert is_trading_day(date(2026, 5, 22)) is True


def test_is_trading_day_weekend():
    assert is_trading_day(date(2026, 5, 23)) is False


def test_available_at_to_trading_date_intraday():
    dt = datetime(2026, 5, 22, 10, 30)
    assert available_at_to_trading_date(dt) == "2026-05-22"


def test_available_at_to_trading_date_after_close():
    dt = datetime(2026, 5, 22, 15, 30)
    assert available_at_to_trading_date(dt) == "2026-05-25"


def test_available_at_to_trading_date_weekend():
    dt = datetime(2026, 5, 23, 10, 0)
    assert available_at_to_trading_date(dt) == "2026-05-25"
