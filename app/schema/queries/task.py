import strawberry
from strawberry.types import Info

from app.schema.types.task import (
    TaskConnection,
    TaskFilter,
    TaskResult,
    TaskSort,
    TaskType,
)


@strawberry.type
class Query:
    @strawberry.field
    async def task(self, info: Info, id: strawberry.ID) -> TaskResult:
        raise NotImplementedError("Implemented in Phase 3")

    @strawberry.field
    async def tasks(
        self,
        info: Info,
        filter: TaskFilter | None = None,
        sort: TaskSort | None = None,
        first: int = 20,
        after: str | None = None,
    ) -> TaskConnection:
        raise NotImplementedError("Implemented in Phase 3")
