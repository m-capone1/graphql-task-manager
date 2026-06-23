import uuid
from datetime import datetime
from typing import Annotated, Union

import strawberry
from strawberry.types import Info

from app.models.task import Task as TaskModel
from app.schema.types.enums import TaskPriority, TaskSortField, TaskStatus, SortDirection
from app.schema.types.errors import (
    ConflictError,
    DeleteSuccess,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.schema.types.project import ProjectType
from app.schema.types.user import UserType


@strawberry.type(name="Task")
class TaskType:
    id: strawberry.ID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    version: int
    project_id: strawberry.ID
    assignee_id: strawberry.ID | None
    created_by_id: strawberry.ID
    created_at: datetime
    updated_at: datetime

    @strawberry.field
    async def project(self, info: Info) -> ProjectType:
        model = await info.context.loaders.project.load(uuid.UUID(str(self.project_id)))
        return ProjectType.from_orm(model)

    @strawberry.field
    async def assignee(self, info: Info) -> UserType | None:
        if self.assignee_id is None:
            return None
        model = await info.context.loaders.user.load(uuid.UUID(str(self.assignee_id)))
        return UserType.from_orm(model) if model else None

    @strawberry.field
    async def created_by(self, info: Info) -> UserType:
        model = await info.context.loaders.user.load(uuid.UUID(str(self.created_by_id)))
        return UserType.from_orm(model)

    @classmethod
    def from_orm(cls, model: TaskModel) -> "TaskType":
        return cls(
            id=strawberry.ID(str(model.id)),
            title=model.title,
            description=model.description,
            status=TaskStatus[model.status.name],
            priority=TaskPriority[model.priority.name],
            version=model.version,
            project_id=strawberry.ID(str(model.project_id)),
            assignee_id=strawberry.ID(str(model.assignee_id)) if model.assignee_id else None,
            created_by_id=strawberry.ID(str(model.created_by_id)),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


# --- Cursor pagination types ---

@strawberry.type
class PageInfo:
    has_next_page: bool
    has_previous_page: bool
    start_cursor: str | None
    end_cursor: str | None


@strawberry.type
class TaskEdge:
    node: TaskType
    cursor: str


@strawberry.type
class TaskConnection:
    edges: list[TaskEdge]
    page_info: PageInfo
    total_count: int


# --- Input types ---

@strawberry.input
class CreateTaskInput:
    title: str
    project_id: strawberry.ID
    description: str | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: strawberry.ID | None = None


@strawberry.input
class UpdateTaskInput:
    title: str | None = strawberry.UNSET
    description: str | None = strawberry.UNSET
    priority: TaskPriority | None = strawberry.UNSET
    # UNSET = don't touch; None = unassign
    assignee_id: strawberry.ID | None = strawberry.UNSET


@strawberry.input
class TaskFilter:
    project_id: strawberry.ID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee_id: strawberry.ID | None = None


@strawberry.input
class TaskSort:
    field: TaskSortField = TaskSortField.CREATED_AT
    direction: SortDirection = SortDirection.DESC


# --- Union result types ---

TaskResult = Annotated[
    Union[TaskType, NotFoundError, ValidationError, ConflictError, ForbiddenError],
    strawberry.union("TaskResult"),
]

DeleteResult = Annotated[
    Union[DeleteSuccess, NotFoundError, ForbiddenError],
    strawberry.union("DeleteResult"),
]
