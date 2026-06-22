import base64
import enum
import json
import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.models.task import TaskPriority as ORMPriority
from app.models.task import TaskStatus as ORMStatus
from app.schema.types.enums import SortDirection, TaskSortField

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
