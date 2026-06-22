from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@dataclass
class GraphQLContext:
    db: AsyncSession
    current_user: User | None
