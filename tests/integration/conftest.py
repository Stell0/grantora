from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class IsolatedPostgresSchema:
    base_url: str
    database_url: str
    schema: str
    admin_engine: Engine


@dataclass(frozen=True)
class ApisixIntegrationTarget:
    admin_url: str
    admin_key: str
    timeout_seconds: float


@pytest.fixture()
def isolated_postgres_schema() -> IsolatedPostgresSchema:
    base_url = _required_postgres_url()
    schema = f"grantora_it_{uuid4().hex}"
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    try:
        yield IsolatedPostgresSchema(
            base_url=base_url,
            database_url=_database_url_with_search_path(base_url, schema),
            schema=schema,
            admin_engine=admin_engine,
        )
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.fixture()
def migrated_postgres_schema(
    isolated_postgres_schema: IsolatedPostgresSchema,
    monkeypatch: pytest.MonkeyPatch,
) -> IsolatedPostgresSchema:
    monkeypatch.setenv("DATABASE_URL", isolated_postgres_schema.database_url)
    alembic_config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")
    return isolated_postgres_schema


@pytest.fixture()
def apisix_target() -> ApisixIntegrationTarget:
    admin_url = os.environ.get("GRANTORA_INTEGRATION_APISIX_ADMIN_URL")
    admin_key = os.environ.get("GRANTORA_INTEGRATION_APISIX_ADMIN_KEY") or os.environ.get(
        "APISIX_ADMIN_KEY"
    )
    if not admin_url or not admin_key:
        pytest.skip(
            "Set GRANTORA_INTEGRATION_APISIX_ADMIN_URL and APISIX_ADMIN_KEY "
            "to run APISIX integration tests."
        )
    return ApisixIntegrationTarget(
        admin_url=admin_url,
        admin_key=admin_key,
        timeout_seconds=float(os.environ.get("GRANTORA_INTEGRATION_TIMEOUT_SECONDS", "10")),
    )


def table_names_for_schema(schema: IsolatedPostgresSchema) -> set[str]:
    with schema.admin_engine.connect() as connection:
        rows = connection.execute(
            text("select table_name from information_schema.tables where table_schema = :schema"),
            {"schema": schema.schema},
        )
    return set(rows.scalars().all())


def _required_postgres_url() -> str:
    database_url = os.environ.get("GRANTORA_INTEGRATION_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "Set GRANTORA_INTEGRATION_DATABASE_URL to a disposable PostgreSQL database "
            "to run integration tests."
        )
    if not database_url.startswith("postgresql"):
        pytest.skip("GRANTORA_INTEGRATION_DATABASE_URL must use a PostgreSQL SQLAlchemy URL.")
    return database_url


def _database_url_with_search_path(database_url: str, schema: str) -> str:
    url = make_url(database_url)
    query = dict(url.query)
    existing_options = query.get("options")
    search_path_option = f"-csearch_path={schema}"
    if existing_options:
        query["options"] = f"{existing_options} {search_path_option}"
    else:
        query["options"] = search_path_option
    return url.set(query=query).render_as_string(hide_password=False)
