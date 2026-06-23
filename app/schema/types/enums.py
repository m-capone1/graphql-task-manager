import enum

import strawberry

from app.models.task import TaskPriority as ORMPriority
from app.models.task import TaskStatus as ORMStatus


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


def gql_status_to_orm(status: TaskStatus) -> ORMStatus:
    return ORMStatus[status.name]


def gql_priority_to_orm(priority: TaskPriority) -> ORMPriority:
    return ORMPriority[priority.name]
