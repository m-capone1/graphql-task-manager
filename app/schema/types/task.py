import enum
import uuid
from datetime import datetime
from typing import Annotated, Union

import strawberry
from sqlalchemy import select
from strawberry.types import Info

from app.models.task import Task as TaskModel
from app.models.task import TaskPriority as ORMPriority
from app.models.task import TaskStatus as ORMStatus
from app.schema.types.errors import (
    ConflictError,
    DeleteSuccess,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.schema.types.project import ProjectType
from app.schema.types.user import UserType


@strawberry.enum
class TaskStatus(str, enum.Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    IN_REVIEW = "IN_REVIEW"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


@strawberry.enum
class TaskPriority(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@strawberry.enum
class SortDirection(str, enum.Enum):
    ASC = "ASC"
    DESC = "DESC"


@strawberry.enum
class TaskSortField(str, enum.Enum):
    CREATED_AT = "CREATED_AT"
    PRIORITY = "PRIORITY"
    STATUS = "STATUS"
    TITLE = "TITLE"


@strawberry.type
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
        # Phase 5: replace body with info.context.loaders.project.load(...)
        from app.models.project import Project as ProjectModel

        result = await info.context.db.execute(
            select(ProjectModel).where(ProjectModel.id == uuid.UUID(str(self.project_id)))
        )
        return ProjectType.from_orm(result.scalar_one())

    @strawberry.field
    async def assignee(self, info: Info) -> UserType | None:
        if self.assignee_id is None:
            return None
        # Phase 5: replace body with info.context.loaders.user.load(...)
        from app.models.user import User as UserModel

        result = await info.context.db.execute(
            select(UserModel).where(UserModel.id == uuid.UUID(str(self.assignee_id)))
        )
        model = result.scalar_one_or_none()
        return UserType.from_orm(model) if model else None

    @strawberry.field
    async def created_by(self, info: Info) -> UserType:
        # Phase 5: replace body with info.context.loaders.user.load(...)
        from app.models.user import User as UserModel

        result = await info.context.db.execute(
            select(UserModel).where(UserModel.id == uuid.UUID(str(self.created_by_id)))
        )
        return UserType.from_orm(result.scalar_one())

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


# --- ORM enum conversion helpers ---

def orm_status_to_gql(status: ORMStatus) -> TaskStatus:
    return TaskStatus[status.name]


def gql_status_to_orm(status: TaskStatus) -> ORMStatus:
    return ORMStatus[status.name]


def orm_priority_to_gql(priority: ORMPriority) -> TaskPriority:
    return TaskPriority[priority.name]


def gql_priority_to_orm(priority: TaskPriority) -> ORMPriority:
    return ORMPriority[priority.name]
