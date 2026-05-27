"""A-share trading calendar — maps dates to trading days."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

_HOLIDAYS: set[date] = set()

def _populate_holidays() -> None:
    for year in range(2020, 2027):
        _HOLIDAYS.add(date(year, 1, 1))
    spring_festival_ranges = [
        (2020, 1, 24, 1, 30), (2021, 2, 11, 2, 17), (2022, 1, 31, 2, 6),
        (2023, 1, 21, 1, 27), (2024, 2, 10, 2, 16), (2025, 1, 28, 2, 3),
        (2026, 2, 17, 2, 23),
    ]
    for year, sm, sd, em, ed in spring_festival_ranges:
        d = date(year, sm, sd)
        end = date(year, em, ed)
        while d <= end:
            _HOLIDAYS.add(d)
            d += timedelta(days=1)
    for year in range(2020, 2027):
        for day in [4, 5, 6]:
            try:
                _HOLIDAYS.add(date(year, 4, day))
            except ValueError:
                pass
    for year in range(2020, 2027):
        for day in range(1, 6):
            _HOLIDAYS.add(date(year, 5, day))
    dragon_boat = [
        (2020, 6, 25, 6, 27), (2021, 6, 12, 6, 14), (2022, 6, 3, 6, 5),
        (2023, 6, 22, 6, 24), (2024, 6, 8, 6, 10), (2025, 5, 31, 6, 2),
        (2026, 6, 19, 6, 21),
    ]
    for year, sm, sd, em, ed in dragon_boat:
        d = date(year, sm, sd)
        end = date(year, em, ed)
        while d <= end:
            _HOLIDAYS.add(d)
            d += timedelta(days=1)
    mid_autumn = [
        (2020, 10, 1, 10, 8),
        (2021, 9, 19, 9, 21), (2022, 9, 10, 9, 12),
        (2023, 9, 29, 10, 6), (2024, 9, 15, 9, 17),
        (2025, 10, 6, 10, 8), (2026, 9, 25, 9, 27),
    ]
    for year, sm, sd, em, ed in mid_autumn:
        d = date(year, sm, sd)
        end = date(year, em, ed)
        while d <= end:
            _HOLIDAYS.add(d)
            d += timedelta(days=1)
    for year in range(2020, 2027):
        for day in range(1, 8):
            _HOLIDAYS.add(date(year, 10, day))

_populate_holidays()

CLOSE_TIME = time(15, 0, 0)


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d not in _HOLIDAYS


def next_trading_day(d: date) -> date:
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def available_at_to_trading_date(available_at: datetime) -> str:
    d = available_at.date()
    if is_trading_day(d) and available_at.time() < CLOSE_TIME:
        return d.isoformat()
    return next_trading_day(d + timedelta(days=1)).isoformat()
