from datetime import UTC, datetime
import httpx
from app.config import get_settings
from app.analytics import period_bounds
from app.services import StravaClient, is_club_member, normalize_sport, parse_scopes

def test_normalize_sport():
    assert normalize_sport("Swim")=="swim"; assert normalize_sport("Swim", 2)=="open_water"; assert normalize_sport("OpenWaterSwim")=="open_water"; assert normalize_sport("WeightTraining")=="strength"; assert normalize_sport("Workout")=="strength"; assert normalize_sport("Yoga")=="wellbeing"; assert normalize_sport("Pilates")=="wellbeing"; assert normalize_sport("GravelRide")=="bike"; assert normalize_sport("TrailRun")=="run"; assert normalize_sport("Walk")=="walk"; assert normalize_sport("Hike")=="walk"
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


def test_authorization_requests_non_private_activity_access():
    url = StravaClient().authorization_url("state-value")
    assert "activity%3Aread" in url
    assert "activity%3Aread_all" not in url
    assert "approval_prompt=force" in url


def test_authorization_can_request_private_activity_access():
    url = StravaClient().authorization_url("state-value", include_private=True)
    assert "activity%3Aread_all" in url


def test_login_authorization_reuses_existing_approval():
    url = StravaClient().authorization_url("state-value", force_approval=False)
    assert "approval_prompt=auto" in url


def test_parse_scopes_accepts_callback_and_token_formats():
    expected = {"read", "profile:read_all", "activity:read"}
    assert parse_scopes("read,profile:read_all,activity:read") == expected
    assert parse_scopes("read profile:read_all activity:read") == expected


def test_clubs_requests_all_pages():
    requests = []

    def handler(request):
        requests.append(request)
        page = int(request.url.params["page"])
        return httpx.Response(200, json=[{"id": item} for item in range(200)] if page == 1 else [{"id": 1187973}])

    client = StravaClient(httpx.Client(transport=httpx.MockTransport(handler)))

    clubs = client.clubs("token")

    assert len(clubs) == 201
    assert clubs[-1]["id"] == 1187973
    assert [request.url.params["page"] for request in requests] == ["1", "2"]
