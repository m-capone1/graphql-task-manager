from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.dataloader import DataLoader

from app.models.user import User


@dataclass
class Loaders:
    user: DataLoader
    project: DataLoader


@dataclass
class GraphQLContext:
    db: AsyncSession
    current_user: User | None
    loaders: Loaders
