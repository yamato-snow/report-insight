"""integration テストの共通フィクスチャ（testcontainers 上の実 PostgreSQL+pgvector）。

コーディング規約 §6: integration は compose/実DBを使用。ここでは testcontainers で
pgvector イメージを起動し、Alembic マイグレーションを適用する（マイグレーション自体も検証）。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.core.config import get_settings
from app.infra.db import models

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session", autouse=True)
def _migrate(pg_url: str) -> None:
    # env.py は get_settings().database_url を使うため、env 変数で上書きしキャッシュを破棄する
    os.environ["DATABASE_URL"] = pg_url
    get_settings.cache_clear()
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "app/infra/db/migrations")
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def session_factory(pg_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(pg_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """基礎データ（2支店・物件・利用者）を投入し、各テスト後に全テーブルを掃除する。"""
    async with session_factory() as session:
        await session.execute(
            pg_insert(models.Branch)
            .values([{"id": 1, "name": "東京"}, {"id": 2, "name": "大阪"}])
            .on_conflict_do_nothing()
        )
        await session.execute(
            pg_insert(models.Property)
            .values(
                [
                    {"id": 101, "branch_id": 1, "name": "東京物件A"},
                    {"id": 201, "branch_id": 2, "name": "大阪物件A"},
                ]
            )
            .on_conflict_do_nothing()
        )
        await session.execute(
            pg_insert(models.User)
            .values(
                [
                    {"id": 1, "branch_id": 1, "email": "tokyo@e.com", "role": "branch_manager"},
                    {"id": 2, "branch_id": None, "email": "qa@e.com", "role": "qa"},
                ]
            )
            .on_conflict_do_nothing()
        )
        await session.commit()

    yield session_factory

    async with session_factory() as session:
        await session.execute(
            text("TRUNCATE report_chunks, report_analyses, reports RESTART IDENTITY CASCADE")
        )
        await session.commit()
