from datetime import UTC, datetime
from app.config import get_settings
from app.services import normalize_sport, period_bounds

def test_normalize_sport():
    assert normalize_sport("Swim")=="swim"; assert normalize_sport("GravelRide")=="bike"; assert normalize_sport("TrailRun")=="run"; assert normalize_sport("Walk") is None
def test_week_boundaries():
    start,end=period_bounds("week",datetime(2026,9,28,12,tzinfo=UTC),"America/Mexico_City")
    assert (end-start).days==7 and start.weekday()==0
def test_month_boundaries():
    start,end=period_bounds("month",datetime(2026,2,15,tzinfo=UTC),"UTC")
    assert start.day==1 and end.month==3
