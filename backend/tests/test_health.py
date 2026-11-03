from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_reports_running_service() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_database_health_reports_connection_failure(monkeypatch) -> None:
    def fail_connection() -> None:
        raise RuntimeError("test connection failure")

    monkeypatch.setattr("app.main.check_database_connection", fail_connection)
    response = TestClient(app).get("/api/v1/health/database")

    assert response.status_code == 503
    assert "Database connection unavailable" in response.json()["detail"]
