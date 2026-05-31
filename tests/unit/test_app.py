from grantora.config import Settings
from grantora.main import create_app


class Probe:
    def ping(self) -> None:
        return None

    def dispose(self) -> None:
        return None


def test_create_app_imports_without_connecting_to_database() -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", environment="test")

    app = create_app(settings=settings, database=Probe())

    assert app.title == "Grantora Gateway API"
