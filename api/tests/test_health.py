from fastapi.testclient import TestClient

from circulariq.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_cors_allows_configured_origin() -> None:
    response = client.options(
        "/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_stats_returns_503_when_database_unavailable(monkeypatch) -> None:
    def broken_connect():
        raise RuntimeError("DATABASE_URL is not set")

    monkeypatch.setattr("circulariq.main.connect", broken_connect)
    response = client.get("/stats")
    assert response.status_code == 503


def test_redact_hides_database_password() -> None:
    from circulariq.db import redact

    msg = (
        'invalid option "postgresql://neondb_owner:s3cret-pw@ep-x.neon.tech/neondb?sslmode=require"'
    )
    assert "s3cret-pw" not in redact(msg)
    assert "postgresql://neondb_owner:***@ep-x.neon.tech" in redact(msg)
