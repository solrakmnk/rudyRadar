"""Period navigation: week/month scale, previous/next steps and readable labels."""
from datetime import UTC, date, datetime

import pytest
from jinja2 import Environment, FileSystemLoader

from app.i18n import translate
from app.periods import format_range, period_nav

# Wednesday 11 November 2026, 12:00 in Mexico City.
NOW = datetime(2026, 11, 11, 18, tzinfo=UTC)
TZ = "America/Mexico_City"


@pytest.mark.parametrize("period,label,detail,previous,next_", [
    ("week", "Esta semana", "9–15 nov · día 3 de 7", "last_week", None),
    ("last_week", "Semana pasada", "2–8 nov", None, "week"),
    ("month", "Noviembre", "Este mes · día 11 de 30", "last_month", None),
    ("last_month", "Octubre", "Mes pasado", "two_months_ago", "month"),
    ("two_months_ago", "Septiembre", "Hace 2 meses", None, "last_month"),
])
def test_every_supported_period_has_a_label_dates_and_neighbours(period, label, detail, previous, next_):
    nav = period_nav(period, "es", NOW, TZ)
    assert (nav.label, nav.detail, nav.previous, nav.next) == (label, detail, previous, next_)
    assert nav.is_current is (next_ is None)


def test_english_labels():
    assert period_nav("week", "en", NOW, TZ).detail == "Nov 9–15 · day 3 of 7"
    assert period_nav("two_months_ago", "en", NOW, TZ).label == "September"


def test_week_that_spans_two_months():
    nav = period_nav("week", "es", datetime(2026, 11, 2, 18, tzinfo=UTC), TZ)  # Monday 2 Nov
    previous = period_nav("last_week", "en", datetime(2026, 11, 2, 18, tzinfo=UTC), TZ)
    assert nav.detail == "2–8 nov · día 1 de 7"
    assert previous.detail == "Oct 26 – Nov 1"


def test_months_from_another_year_include_the_year():
    january = datetime(2026, 1, 15, 18, tzinfo=UTC)
    assert period_nav("month", "es", january, TZ).label == "Enero"
    assert period_nav("last_month", "es", january, TZ).label == "Diciembre 2025"


def test_local_timezone_decides_the_current_day():
    # 05:00 UTC on Monday is still Sunday night in Mexico City.
    nav = period_nav("week", "es", datetime(2026, 11, 9, 5, tzinfo=UTC), TZ)
    assert nav.detail == "2–8 nov · día 7 de 7"


def test_unknown_period_falls_back_to_this_week():
    assert period_nav("year", "es", NOW, TZ).period == "week"


def test_format_range():
    assert format_range(date(2026, 11, 9), date(2026, 11, 15), "es") == "9–15 nov"
    assert format_range(date(2026, 12, 28), date(2027, 1, 3), "es") == "28 dic – 3 ene"
    assert format_range(date(2026, 12, 28), date(2027, 1, 3), "en") == "Dec 28 – Jan 3"


def render_nav(period, **kwargs):
    env = Environment(loader=FileSystemLoader("app/templates"), autoescape=True)
    template = env.from_string("{% from '_period_nav.html' import period_nav as nav_ui with context %}{{ nav_ui(nav, base, extra, link_attr) }}")
    return template.render(nav=period_nav(period, "es", NOW, TZ), t=lambda key, **v: translate("es", key, **v), base="/radar", **kwargs)


def test_current_period_has_no_next_arrow_and_marks_the_scale():
    html = render_nav("week", extra="&sport=run", link_attr="data-period-link")
    assert 'href="/radar?period=last_week&amp;sport=run"' in html
    assert 'aria-label="Periodo siguiente"' not in html and 'aria-disabled="true"' in html
    assert '<a data-period-link href="/radar?period=week&amp;sport=run" class="active" aria-current="true">Semana</a>' in html
    assert "Esta semana" in html and "9–15 nov" in html


def test_oldest_period_has_no_previous_arrow():
    html = render_nav("two_months_ago", extra="", link_attr="")
    assert 'aria-label="Periodo anterior"' not in html
    assert 'href="/radar?period=last_month"' in html and 'aria-label="Periodo siguiente"' in html
    assert "Septiembre" in html


def test_month_scale_link_goes_to_the_current_month():
    html = render_nav("last_week", extra="", link_attr="")
    assert 'href="/radar?period=month" class="">Mes</a>' in html
