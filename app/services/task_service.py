import base64
import enum
import json
import uuid
from datetime import datetime

import structlog
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.task import Task
from app.models.task import TaskPriority as ORMPriority
from app.models.task import TaskStatus as ORMStatus
from app.models.user import User
from app.schema.types.enums import SortDirection, TaskSortField
from app.services.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.services.validators import CreateTaskData, extract_pydantic_error

logger = structlog.get_logger()


class _UnsetType:
    pass


_UNSET = _UnsetType()

# Cursor helpers

def encode_cursor(field: TaskSortField, value: object, task_id: uuid.UUID) -> str:
    if isinstance(value, datetime):
        serialized = value.isoformat()
    elif isinstance(value, enum.Enum):
        serialized = value.value
    else:
        serialized = str(value)
    payload = {"field": field.value, "value": serialized, "id": str(task_id)}
    return base64.b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(cursor: str) -> tuple[TaskSortField, object, uuid.UUID]:
    data = json.loads(base64.b64decode(cursor).decode())
    field = TaskSortField(data["field"])
    raw: str = data["value"]
    task_id = uuid.UUID(data["id"])
    if field == TaskSortField.CREATED_AT:
        value: object = datetime.fromisoformat(raw)
    elif field == TaskSortField.PRIORITY:
        value = ORMPriority(raw)
    elif field == TaskSortField.STATUS:
        value = ORMStatus(raw)
    else:
        value = raw
    return field, value, task_id


def task_sort_value(task: Task, field: TaskSortField) -> object:
    return {
        TaskSortField.CREATED_AT: task.created_at,
        TaskSortField.PRIORITY: task.priority,
        TaskSortField.STATUS: task.status,
        TaskSortField.TITLE: task.title,
    }[field]


def _sort_col(field: TaskSortField):
    return {
        TaskSortField.CREATED_AT: Task.created_at,
        TaskSortField.PRIORITY: Task.priority,
        TaskSortField.STATUS: Task.status,
        TaskSortField.TITLE: Task.title,
    }[field]

# Queries

async def get_task(db: AsyncSession, task_id: uuid.UUID) -> Task | None:
    result = await db.execute(select(Task).where(Task.id == task_id))
    return result.scalar_one_or_none()


async def list_tasks(
    db: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    status: ORMStatus | None = None,
    priority: ORMPriority | None = None,
    assignee_id: uuid.UUID | None = None,
    sort_field: TaskSortField = TaskSortField.CREATED_AT,
    sort_direction: SortDirection = SortDirection.DESC,
    first: int = 20,
    after: str | None = None,
) -> tuple[list[Task], bool, int]:
    if not (1 <= first <= 100):
        raise ValidationError("'first' must be between 1 and 100", field="first")

    filter_conditions = []
    if project_id is not None:
        filter_conditions.append(Task.project_id == project_id)
    if status is not None:
        filter_conditions.append(Task.status == status)
    if priority is not None:
        filter_conditions.append(Task.priority == priority)
    if assignee_id is not None:
        filter_conditions.append(Task.assignee_id == assignee_id)

    # Total matching the filter (not cursor-adjusted — stable across pages)
    count_q = select(func.count()).select_from(Task)
    if filter_conditions:
        count_q = count_q.where(and_(*filter_conditions))
    total: int = (await db.execute(count_q)).scalar_one()

    # Keyset cursor: (sort_col, id) comparison avoids OFFSET scans
    page_conditions = list(filter_conditions)
    if after:
        _, cursor_val, cursor_id = decode_cursor(after)
        col = _sort_col(sort_field)
        if sort_direction == SortDirection.DESC:
            page_conditions.append(
                or_(col < cursor_val, and_(col == cursor_val, Task.id < cursor_id))
            )
        else:
            page_conditions.append(
                or_(col > cursor_val, and_(col == cursor_val, Task.id > cursor_id))
            )

    col = _sort_col(sort_field)
    q = select(Task)
    if page_conditions:
        q = q.where(and_(*page_conditions))
    if sort_direction == SortDirection.DESC:
        q = q.order_by(col.desc(), Task.id.desc())
    else:
        q = q.order_by(col.asc(), Task.id.asc())
    q = q.limit(first + 1)

    rows = list((await db.execute(q)).scalars().all())
    has_next = len(rows) > first
    return rows[:first], has_next, total


# Mutations


async def create_task(
    db: AsyncSession,
    *,
    title: str,
    project_id: uuid.UUID,
    description: str | None = None,
    priority: ORMPriority = ORMPriority.MEDIUM,
    assignee_id: uuid.UUID | None = None,
    created_by_id: uuid.UUID,
) -> Task:
    try:
        data = CreateTaskData(title=title, description=description)
    except PydanticValidationError as exc:
        msg, field = extract_pydantic_error(exc)
        raise ValidationError(msg, field=field)

    title = data.title
    description = data.description

    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise NotFoundError("Project", str(project_id))

    if assignee_id is not None:
        user = (
            await db.execute(select(User).where(User.id == assignee_id))
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User", str(assignee_id))

    task = Task(
        title=title,
        description=description,
        priority=priority,
        status=ORMStatus.TODO,
        project_id=project_id,
        assignee_id=assignee_id,
        created_by_id=created_by_id,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


async def update_task(
    db: AsyncSession,
    task_id: uuid.UUID,
    *,
    title: str | None | _UnsetType = _UNSET,
    description: str | None | _UnsetType = _UNSET,
    priority: ORMPriority | _UnsetType = _UNSET,
    assignee_id: uuid.UUID | None | _UnsetType = _UNSET,
) -> Task:
    task = await get_task(db, task_id)
    if task is None:
        raise NotFoundError("Task", str(task_id))

    changed = False

    if not isinstance(title, _UnsetType):
        stripped = str(title).strip() if title is not None else ""
        if not stripped:
            raise ValidationError("Title cannot be empty", field="title")
        if len(stripped) > 500:
            raise ValidationError("Title must be 500 characters or fewer", field="title")
        task.title = stripped
        changed = True

    if not isinstance(description, _UnsetType):
        if description is not None and len(description) > 10_000:
            raise ValidationError(
                "Description must be 10,000 characters or fewer", field="description"
            )
        task.description = description
        changed = True

    if not isinstance(priority, _UnsetType):
        task.priority = priority
        changed = True

    if not isinstance(assignee_id, _UnsetType):
        if assignee_id is not None:
            user = (
                await db.execute(select(User).where(User.id == assignee_id))
            ).scalar_one_or_none()
            if user is None:
                raise NotFoundError("User", str(assignee_id))
        task.assignee_id = assignee_id
        changed = True

    if changed:
        await db.flush()
        await db.refresh(task)
    return task


async def change_task_status(
    db: AsyncSession,
    task_id: uuid.UUID,
    status: ORMStatus,
    version: int,
) -> Task:
    stmt = (
        sa_update(Task)
        .where(Task.id == task_id, Task.version == version)
        .values(status=status, version=version + 1, updated_at=func.now())
        .returning(Task)
    )
    result = await db.execute(stmt)
    task = result.scalars().one_or_none()
    if task is not None:
        return task

    # Distinguish not-found from optimistic-lock conflict.
    current = (
        await db.execute(select(Task).where(Task.id == task_id))
    ).scalar_one_or_none()
    if current is None:
        raise NotFoundError("Task", str(task_id))
    logger.warning(
        "task.conflict",
        task_id=str(task_id),
        client_version=version,
        current_version=current.version,
    )
    raise ConflictError(
        "Task was modified concurrently — please refresh and retry.",
        current_version=current.version,
    )


async def delete_task(
    db: AsyncSession,
    task_id: uuid.UUID,
    current_user_id: uuid.UUID,
) -> None:
    task = await get_task(db, task_id)
    if task is None:
        raise NotFoundError("Task", str(task_id))

    if task.created_by_id != current_user_id and task.assignee_id != current_user_id:
        logger.warning(
            "task.delete_forbidden",
            task_id=str(task_id),
            requesting_user_id=str(current_user_id),
            created_by_id=str(task.created_by_id),
        )
        raise ForbiddenError("Only the task creator or assignee can delete this task")

    await db.delete(task)
    await db.flush()
