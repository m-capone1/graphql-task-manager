import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.dataloader import DataLoader

from app.models.project import Project
from app.models.user import User


def make_user_loader(db: AsyncSession) -> DataLoader:
    async def load_fn(keys: list[uuid.UUID]) -> list[User | None]:
        result = await db.execute(select(User).where(User.id.in_(keys)))
        by_id = {u.id: u for u in result.scalars().all()}
        return [by_id.get(k) for k in keys]

    return DataLoader(load_fn=load_fn)


def make_project_loader(db: AsyncSession) -> DataLoader:
    async def load_fn(keys: list[uuid.UUID]) -> list[Project | None]:
        result = await db.execute(select(Project).where(Project.id.in_(keys)))
        by_id = {p.id: p for p in result.scalars().all()}
        return [by_id.get(k) for k in keys]

    return DataLoader(load_fn=load_fn)
