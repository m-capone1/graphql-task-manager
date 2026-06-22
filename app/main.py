import structlog
from fastapi import Depends, FastAPI, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.fastapi import GraphQLRouter

from app.context import GraphQLContext
from app.database import get_session
from app.models.user import User
from app.schema import schema as graphql_schema

logger = structlog.get_logger()


async def get_context(
    x_user_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_session),
) -> GraphQLContext:
    current_user: User | None = None

    if x_user_id:
        try:
            import uuid
            user_uuid = uuid.UUID(x_user_id)
            result = await db.execute(select(User).where(User.id == user_uuid))
            current_user = result.scalar_one_or_none()
        except (ValueError, Exception):
            pass

    return GraphQLContext(db=db, current_user=current_user)


graphql_router = GraphQLRouter(graphql_schema, context_getter=get_context)

app = FastAPI(
    title="Lush Task Management API",
    description="GraphQL API for managing tasks within projects.",
    version="0.1.0",
)

app.include_router(graphql_router, prefix="/graphql")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
