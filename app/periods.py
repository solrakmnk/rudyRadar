"""Period navigation for the radar: a week/month scale plus previous/next steps.

The analytics layer supports five reporting periods. They are presented as two
scales, each an ordered list from newest to oldest, so the UI only needs a
scale switch and two arrows instead of five pills.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.analytics import period_bounds
from app.config import get_settings
from app.i18n import translate

# Newest first. Index 0 is the period in progress.
SCALES: dict[str, tuple[str, ...]] = {
    "week": ("week", "last_week"),
    "month": ("month", "last_month", "two_months_ago"),
}
SCALE_OF = {period: scale for scale, periods in SCALES.items() for period in periods}
RELATIVE_LABEL = {"week": "this_week", "last_week": "last_week", "month": "this_month", "last_month": "last_month", "two_months_ago": "two_months_ago"}


@dataclass(frozen=True)
class PeriodNav:
    period: str
    scale: str
    label: str
    detail: str
    previous: str | None  # older period, or None at the oldest supported one
    next: str | None  # newer period, or None for the period in progress
    is_current: bool


def _month(locale: str, month: int, *, short: bool) -> str:
    return translate(locale, f"month_{'short_' if short else ''}{month}")


def format_range(start: date, end: date, locale: str) -> str:
    """Inclusive local date range: "10–16 nov" / "27 oct – 2 nov" (es), "Nov 10–16" / "Oct 27 – Nov 2" (en)."""
    if locale == "en":
        if start.month == end.month:
            return f"{_month(locale, start.month, short=True)} {start.day}–{end.day}"
        return f"{_month(locale, start.month, short=True)} {start.day} – {_month(locale, end.month, short=True)} {end.day}"
    if start.month == end.month:
        return f"{start.day}–{end.day} {_month(locale, end.month, short=True)}"
    return f"{start.day} {_month(locale, start.month, short=True)} – {end.day} {_month(locale, end.month, short=True)}"


def period_nav(period: str, locale: str, now: datetime | None = None, timezone: str | None = None) -> PeriodNav:
    period = period if period in SCALE_OF else "week"
    scale = SCALE_OF[period]
    periods = SCALES[scale]
    index = periods.index(period)
    tz = ZoneInfo(timezone or get_settings().app_timezone)
    now = now or datetime.now(UTC)
    start_utc, end_utc = period_bounds(period, now, tz.key)
    start = start_utc.astimezone(tz).date()
    last_day = (end_utc.astimezone(tz) - timedelta(days=1)).date()
    is_current = index == 0
    relative = translate(locale, RELATIVE_LABEL[period])

    if scale == "week":
        label = relative
        detail = format_range(start, last_day, locale)
    else:
        name = _month(locale, start.month, short=False)
        label = name if start.year == now.astimezone(tz).year else f"{name} {start.year}"
        detail = relative
    if is_current:
        today = now.astimezone(tz).date()
        detail += " · " + translate(locale, "day_of", day=(today - start).days + 1, total=(last_day - start).days + 1)

    return PeriodNav(
        period=period,
        scale=scale,
        label=label,
        detail=detail,
        previous=periods[index + 1] if index + 1 < len(periods) else None,
        next=periods[index - 1] if index > 0 else None,
        is_current=is_current,
    )
