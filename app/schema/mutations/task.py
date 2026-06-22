import strawberry
from strawberry.types import Info

from app.schema.types.enums import TaskStatus
from app.schema.types.task import (
    CreateTaskInput,
    DeleteResult,
    TaskResult,
    UpdateTaskInput,
)


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_task(self, info: Info, input: CreateTaskInput) -> TaskResult:
        raise NotImplementedError("Implemented in Phase 4")

    @strawberry.mutation
    async def update_task(
        self, info: Info, id: strawberry.ID, input: UpdateTaskInput
    ) -> TaskResult:
        raise NotImplementedError("Implemented in Phase 4")

    @strawberry.mutation
    async def change_task_status(
        self, info: Info, id: strawberry.ID, status: TaskStatus, version: int
    ) -> TaskResult:
        raise NotImplementedError("Implemented in Phase 4")

    @strawberry.mutation
    async def assign_task(
        self, info: Info, id: strawberry.ID, user_id: strawberry.ID | None
    ) -> TaskResult:
        raise NotImplementedError("Implemented in Phase 4")

    @strawberry.mutation
    async def delete_task(self, info: Info, id: strawberry.ID) -> DeleteResult:
        raise NotImplementedError("Implemented in Phase 4")
