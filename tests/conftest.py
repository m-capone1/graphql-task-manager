import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.context import GraphQLContext, Loaders
from app.main import app, get_context
from app.models.task import TaskPriority as ORMPriority
from app.models.task import TaskStatus as ORMStatus


def make_mock_task(**kwargs) -> MagicMock:
    """A MagicMock that quacks like a Task ORM instance."""
    t = MagicMock()
    t.id = kwargs.get("id", uuid.uuid4())
    t.title = kwargs.get("title", "Test Task")
    t.description = kwargs.get("description", None)
    t.status = kwargs.get("status", ORMStatus.TODO)
    t.priority = kwargs.get("priority", ORMPriority.MEDIUM)
    t.version = kwargs.get("version", 1)
    t.project_id = kwargs.get("project_id", uuid.uuid4())
    t.assignee_id = kwargs.get("assignee_id", None)
    t.created_by_id = kwargs.get("created_by_id", uuid.uuid4())
    t.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
    t.updated_at = kwargs.get("updated_at", datetime.now(timezone.utc))
    return t


def make_execute_result(scalar=None) -> MagicMock:
    """Builds a mock that covers the SQLAlchemy CursorResult access patterns we use."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.scalar_one.return_value = scalar
    scalars_mock = MagicMock()
    scalars_mock.one_or_none.return_value = scalar
    scalars_mock.all.return_value = [] if scalar is None else [scalar]
    result.scalars.return_value = scalars_mock
    return result


# ---------------------------------------------------------------------------
# Service-test fixtures — isolated AsyncMock session, no real DB
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    from sqlalchemy.ext.asyncio import AsyncSession

    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = make_execute_result()
    return session


# ---------------------------------------------------------------------------
# GraphQL-test fixtures — mocked context, no DB at all
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    return u


def _context_override(current_user):
    async def override():
        return GraphQLContext(
            db=AsyncMock(),
            current_user=current_user,
            loaders=Loaders(user=AsyncMock(), project=AsyncMock()),
        )

    return override


@pytest_asyncio.fixture
async def client(mock_user):
    app.dependency_overrides[get_context] = _context_override(mock_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_context, None)


@pytest_asyncio.fixture
async def unauthed_client():
    app.dependency_overrides[get_context] = _context_override(None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_context, None)


# ---------------------------------------------------------------------------
# Integration-test fixtures — real PostgreSQL, schema assumed already migrated
# (the app container runs `alembic upgrade head` on startup; `make test` execs
# into it). Override the target with TEST_DATABASE_URL. If no database is
# reachable, these fixtures skip rather than fail, so the mocked suite still
# runs standalone.
# ---------------------------------------------------------------------------

def _integration_db_url() -> str:
    return os.environ.get("TEST_DATABASE_URL") or settings.database_url


@pytest_asyncio.fixture
async def integration_engine():
    engine = create_async_engine(_integration_db_url(), poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — any connect failure means skip
        await engine.dispose()
        pytest.skip(f"Integration database not reachable: {exc}")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(integration_engine):
    """A session wrapped in a transaction that is always rolled back, so tests
    never persist anything. Service functions only flush (commit lives in the
    resolver layer), so the rollback fully isolates each test."""
    conn = await integration_engine.connect()
    trans = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        if trans.is_active:
            await trans.rollback()
        await conn.close()
