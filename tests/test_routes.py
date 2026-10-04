from fastapi.testclient import TestClient
from jinja2 import DictLoader, Environment

from app.main import app


def test_translated_comparison_macro_inherits_template_context():
    env = Environment(loader=DictLoader({
        "comparison.html": "{% macro bars() %}{{ t('current_period') }}{% endmacro %}",
        "page.html": "{% from 'comparison.html' import bars with context %}{{ bars() }}",
    }))

    rendered = env.get_template("page.html").render(t=lambda key: {"current_period": "Periodo actual"}[key])

    assert rendered == "Periodo actual"


def test_public_pages_and_protected_routes_are_wired():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/").status_code == 200
        assert client.get("/radar", follow_redirects=False).status_code == 303
        assert client.get("/admin", follow_redirects=False).status_code == 401
