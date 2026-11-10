"""Athlete photos: broken or placeholder URLs fall back to the athlete's initial."""
from datetime import UTC, datetime, timedelta

from jinja2 import Environment, FileSystemLoader

from app import cli
from app.models import Athlete
from app.services import StravaClient, StravaTransientError, profile_photo_url

env = Environment(loader=FileSystemLoader("app/templates"), autoescape=True)


def render(url, name, fallback_class=""):
    template = env.from_string("{% from '_avatar.html' import avatar %}{{ avatar(url, name, fallback_class) }}")
    return template.render(url=url, name=name, fallback_class=fallback_class)


def test_valid_photo_renders_an_image_with_an_initial_fallback():
    html = render("https://dgalywyr863hv.cloudfront.net/pictures/athletes/1/large.jpg", "Carlos", "avatar-fallback")
    assert html.startswith('<img src="https://dgalywyr863hv.cloudfront.net/pictures/athletes/1/large.jpg"')
    assert 'data-initial="C"' in html and 'data-fallback-class="avatar-fallback"' in html
    assert "onerror=" in html and "textContent" in html


def test_relative_placeholder_and_missing_photos_render_the_initial():
    assert render("avatar/athlete/large.png", "Rudo", "avatar-fallback") == '<span class="avatar-fallback">R</span>'
    assert render(None, "Rudo") == "<span>R</span>"
    assert render("", "", "") == "<span>?</span>"


def test_names_are_escaped_in_the_fallback():
    assert render(None, "<b>") == "<span>&lt;</span>"
    assert 'data-initial="&#34;"' in render("https://x.example/p.jpg", '"quoted')


def test_profile_photo_url_ignores_placeholders():
    assert profile_photo_url({"profile": "avatar/athlete/large.png", "profile_medium": "avatar/athlete/medium.png"}) is None
    assert profile_photo_url({"profile": "https://a.example/large.jpg"}) == "https://a.example/large.jpg"
    assert profile_photo_url({"profile": "avatar/athlete/large.png", "profile_medium": "https://a.example/m.jpg"}) == "https://a.example/m.jpg"
    assert profile_photo_url({}) is None


def stale_member(db, url):
    athlete = Athlete(strava_athlete_id=7, firstname="Foto", is_active=True, is_club_member=True, profile_url=url,
                      membership_checked_at=datetime.now(UTC) - timedelta(days=8))
    db.add(athlete)
    db.commit()
    return athlete


def test_weekly_maintenance_replaces_a_stale_photo_url(db, monkeypatch, fake_token):
    athlete = stale_member(db, "https://dgalywyr863hv.cloudfront.net/pictures/athletes/7/old/large.jpg")
    monkeypatch.setattr(StravaClient, "clubs", lambda self, token: [{"id": 1187973}])
    monkeypatch.setattr(StravaClient, "athlete", lambda self, token: {"id": 7, "profile": "https://dgalywyr863hv.cloudfront.net/pictures/athletes/7/new/large.jpg"})

    result = cli.revalidate_memberships(db, StravaClient())

    db.refresh(athlete)
    assert result["photos_updated"] == 1
    assert athlete.profile_url.endswith("/7/new/large.jpg")


def test_photo_removed_on_strava_clears_the_url(db, monkeypatch, fake_token):
    athlete = stale_member(db, "https://dgalywyr863hv.cloudfront.net/pictures/athletes/7/old/large.jpg")
    monkeypatch.setattr(StravaClient, "clubs", lambda self, token: [{"id": 1187973}])
    monkeypatch.setattr(StravaClient, "athlete", lambda self, token: {"id": 7, "profile": "avatar/athlete/large.png"})

    cli.revalidate_memberships(db, StravaClient())

    db.refresh(athlete)
    assert athlete.profile_url is None


def test_photo_refresh_failure_keeps_the_current_url_and_membership(db, monkeypatch, fake_token):
    athlete = stale_member(db, "https://dgalywyr863hv.cloudfront.net/pictures/athletes/7/old/large.jpg")
    monkeypatch.setattr(StravaClient, "clubs", lambda self, token: [{"id": 1187973}])

    def unavailable(self, token):
        raise StravaTransientError("503")

    monkeypatch.setattr(StravaClient, "athlete", unavailable)
    result = cli.revalidate_memberships(db, StravaClient())

    db.refresh(athlete)
    assert result["checked"] == 1 and "photos_updated" not in result
    assert athlete.profile_url.endswith("/old/large.jpg") and athlete.membership_check_status == "verified"
