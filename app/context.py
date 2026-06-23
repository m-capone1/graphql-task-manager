from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.dataloader import DataLoader
from strawberry.fastapi import BaseContext

from app.models.user import User


@dataclass
class Loaders:
    user: DataLoader
    project: DataLoader


class GraphQLContext(BaseContext):
    def __init__(self, *, db: AsyncSession, current_user: User | None, loaders: Loaders) -> None:
        super().__init__()
        self.db = db
        self.current_user = current_user
        self.loaders = loaders
