from fastapi.testclient import TestClient

from app.main import app


def test_public_pages_and_protected_routes_are_wired():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/").status_code == 200
        assert client.get("/radar", follow_redirects=False).status_code == 303
        assert client.get("/admin", follow_redirects=False).status_code == 401
