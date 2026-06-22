from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # Pool sized for typical async workload: 10 concurrent sessions, 20 overflow
    pool_size=10,
    max_overflow=20,
)

# expire_on_commit=False: prevents SQLAlchemy from expiring attributes after commit.
# In async code, accessing an expired attribute outside a session raises MissingGreenlet.
# Since we return data immediately after committing, this is safe.
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
