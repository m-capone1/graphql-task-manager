import logging
import uuid

import structlog
from fastapi import Depends, FastAPI, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from strawberry.fastapi import GraphQLRouter

from app.config import settings
from app.context import GraphQLContext, Loaders
from app.database import get_session
from app.models.user import User
from app.schema import schema as graphql_schema
from app.schema.dataloaders import make_project_loader, make_user_loader


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=settings.log_level.upper(), format="%(message)s")


configure_logging()
logger = structlog.get_logger()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=str(uuid.uuid4()))
        response: Response = await call_next(request)  # type: ignore[arg-type]
        return response


async def get_context(
    x_user_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_session),
) -> GraphQLContext:
    current_user: User | None = None

    if x_user_id:
        try:
            user_uuid = uuid.UUID(x_user_id)
            result = await db.execute(select(User).where(User.id == user_uuid))
            current_user = result.scalar_one_or_none()
            if current_user is None:
                logger.warning("auth.user_not_found", x_user_id=x_user_id)
        except ValueError:
            logger.warning("auth.invalid_user_id", x_user_id=x_user_id)

    if current_user:
        structlog.contextvars.bind_contextvars(user_id=str(current_user.id))

    loaders = Loaders(
        user=make_user_loader(db),
        project=make_project_loader(db),
    )
    return GraphQLContext(db=db, current_user=current_user, loaders=loaders)


graphql_router = GraphQLRouter(graphql_schema, context_getter=get_context)

app = FastAPI(
    title="Lush Task Management API",
    description="GraphQL API for managing tasks within projects.",
    version="0.1.0",
)

app.add_middleware(RequestLoggingMiddleware)
app.include_router(graphql_router, prefix="/graphql")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
