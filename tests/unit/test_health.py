from fastapi.testclient import TestClient

from grantora import __version__
from grantora.config import Settings
from grantora.main import create_app


class PassingProbe:
    def ping(self) -> None:
        return None

    def dispose(self) -> None:
        return None


class FailingProbe:
    def ping(self) -> None:
        raise RuntimeError("database unavailable")

    def dispose(self) -> None:
        return None


def test_healthz_returns_process_status() -> None:
    app = create_app(settings=make_test_settings(), database=PassingProbe())

    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "grantora-api",
        "environment": "test",
        "version": __version__,
    }


def test_readyz_returns_ok_when_database_ping_succeeds() -> None:
    app = create_app(settings=make_test_settings(), database=PassingProbe())

    response = TestClient(app).get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "grantora-api",
        "checks": {"database": "ok"},
    }


def test_readyz_returns_safe_error_when_database_ping_fails() -> None:
    app = create_app(settings=make_test_settings(), database=FailingProbe())

    response = TestClient(app).get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "service": "grantora-api",
        "checks": {"database": "unavailable"},
    }


def make_test_settings() -> Settings:
    return Settings(database_url="sqlite+pysqlite:///:memory:", environment="test")
