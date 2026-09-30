from datetime import UTC, datetime
from app.config import get_settings
from app.analytics import period_bounds
from app.services import is_club_member, normalize_sport

def test_normalize_sport():
    assert normalize_sport("Swim")=="swim"; assert normalize_sport("Swim", 2)=="open_water"; assert normalize_sport("OpenWaterSwim")=="open_water"; assert normalize_sport("WeightTraining")=="strength"; assert normalize_sport("Pilates")=="wellbeing"; assert normalize_sport("Workout")=="wellbeing"; assert normalize_sport("GravelRide")=="bike"; assert normalize_sport("TrailRun")=="run"; assert normalize_sport("Walk")=="walk"; assert normalize_sport("Hike")=="walk"
def test_week_boundaries():
    start,end=period_bounds("week",datetime(2026,9,28,12,tzinfo=UTC),"America/Mexico_City")
    assert (end-start).days==7 and start.weekday()==0
def test_last_week_boundaries():
    start,end=period_bounds("last_week",datetime(2026,9,30,12,tzinfo=UTC),"America/Mexico_City")
    assert (end-start).days==7 and start.day==21 and end.day==28
def test_month_boundaries():
    start,end=period_bounds("month",datetime(2026,2,15,tzinfo=UTC),"UTC")
    assert start.day==1 and end.month==3
def test_two_months_ago_boundaries():
    start,end=period_bounds("two_months_ago",datetime(2026,9,30,12,tzinfo=UTC),"UTC")
    assert start.month==7 and end.month==8 and start.day==1 and end.day==1
def test_club_membership_matches_the_configured_club():
    assert is_club_member([{"id": 1187973}])
    assert not is_club_member([{"id": 1}])
