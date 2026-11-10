from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.services import api_metrics


@pytest.fixture()
def db() -> Session:
    # StaticPool shares one connection so threadpool workers (webhook endpoint)
    # see the same in-memory database as the test.
    # Set TEST_DATABASE_URL to run the suite against a disposable PostgreSQL database.
    url = os.getenv("TEST_DATABASE_URL")
    engine = create_engine(url, poolclass=StaticPool) if url else create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def reset_api_metrics():
    api_metrics.reset()
    yield
    api_metrics.reset()


@pytest.fixture()
def fake_token(monkeypatch):
    """Skip token decryption: every Strava call receives the token "access"."""
    calls = []

    def token(db, athlete, client, *, force_refresh=False):
        calls.append(force_refresh)
        return "access"

    monkeypatch.setattr("app.services.get_valid_access_token", token)
    return calls
