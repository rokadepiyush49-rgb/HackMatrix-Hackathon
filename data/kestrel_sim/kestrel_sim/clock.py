"""Simulation calendar. All timestamps are IST, timezone-aware."""

from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

WINDOW_START = datetime(2026, 6, 24, 0, 0, tzinfo=IST)
WINDOW_END = datetime(2026, 9, 22, 23, 59, 59, tzinfo=IST)
DEMO_DAY = date(2026, 9, 21)


def at(d: date, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm, ss), tzinfo=IST)


def days() -> list[date]:
    out, d = [], WINDOW_START.date()
    while d <= WINDOW_END.date():
        out.append(d)
        d += timedelta(days=1)
    return out


def is_bank_holiday(d: date) -> bool:
    """Sundays and the 2nd/4th Saturday are closed (Indian bank convention)."""
    if d.weekday() == 6:
        return True
    if d.weekday() == 5:
        nth = (d.day - 1) // 7 + 1
        return nth in (2, 4)
    return False


def working_days() -> list[date]:
    return [d for d in days() if not is_bank_holiday(d)]


def last_working_day_of_month(d: date) -> date:
    nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    x = nxt - timedelta(days=1)
    while is_bank_holiday(x):
        x -= timedelta(days=1)
    return x


def month_ends() -> list[date]:
    seen, out = set(), []
    for d in days():
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            lw = last_working_day_of_month(d)
            if WINDOW_START.date() <= lw <= WINDOW_END.date():
                out.append(lw)
    return out
