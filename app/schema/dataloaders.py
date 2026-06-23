import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.dataloader import DataLoader

from app.models.project import Project
from app.models.user import User


def _make_loader(model: Any, db: AsyncSession) -> DataLoader:
    async def load_fn(keys: list[uuid.UUID]) -> list[Any]:
        result = await db.execute(select(model).where(model.id.in_(keys)))
        by_id = {obj.id: obj for obj in result.scalars().all()}
        return [by_id.get(k) for k in keys]

    return DataLoader(load_fn=load_fn)


def make_user_loader(db: AsyncSession) -> DataLoader:
    return _make_loader(User, db)


def make_project_loader(db: AsyncSession) -> DataLoader:
    return _make_loader(Project, db)
