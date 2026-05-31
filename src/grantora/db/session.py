from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from grantora.config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_engine(self._settings.database_url, **self._engine_kwargs())
        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                autoflush=False,
                expire_on_commit=False,
            )
        return self._session_factory

    def session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None

    def _engine_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {"pool_pre_ping": True}
        if self._settings.database_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            return kwargs

        kwargs["pool_size"] = self._settings.database_pool_size
        kwargs["max_overflow"] = self._settings.database_max_overflow
        return kwargs
