import uuid

import strawberry
from strawberry.types import Info

from app.schema.types.enums import gql_priority_to_orm, gql_status_to_orm
from app.schema.types.errors import NotFoundError
from app.schema.types.task import (
    PageInfo,
    TaskConnection,
    TaskEdge,
    TaskFilter,
    TaskResult,
    TaskSort,
    TaskType,
)
from app.services import task_service


@strawberry.type
class Query:
    @strawberry.field
    async def task(self, info: Info, id: strawberry.ID) -> TaskResult:
        try:
            task_id = uuid.UUID(str(id))
        except ValueError:
            return NotFoundError(message=f"Task {id} not found")

        task = await task_service.get_task(info.context.db, task_id)
        if task is None:
            return NotFoundError(message=f"Task {id} not found")
        return TaskType.from_orm(task)

    @strawberry.field
    async def tasks(
        self,
        info: Info,
        filter: TaskFilter | None = None,
        sort: TaskSort | None = None,
        first: int = 20,
        after: str | None = None,
    ) -> TaskConnection:
        if sort is None:
            sort = TaskSort()

        project_id = uuid.UUID(str(filter.project_id)) if filter and filter.project_id else None
        assignee_id = uuid.UUID(str(filter.assignee_id)) if filter and filter.assignee_id else None
        orm_status = gql_status_to_orm(filter.status) if filter and filter.status else None
        orm_priority = gql_priority_to_orm(filter.priority) if filter and filter.priority else None

        tasks, has_next, total = await task_service.list_tasks(
            db=info.context.db,
            project_id=project_id,
            status=orm_status,
            priority=orm_priority,
            assignee_id=assignee_id,
            sort_field=sort.field,
            sort_direction=sort.direction,
            first=max(1, min(first, 100)),
            after=after,
        )

        edges = [
            TaskEdge(
                node=TaskType.from_orm(t),
                cursor=task_service.encode_cursor(
                    sort.field, task_service.task_sort_value(t, sort.field), t.id
                ),
            )
            for t in tasks
        ]

        return TaskConnection(
            edges=edges,
            page_info=PageInfo(
                has_next_page=has_next,
                has_previous_page=after is not None,
                start_cursor=edges[0].cursor if edges else None,
                end_cursor=edges[-1].cursor if edges else None,
            ),
            total_count=total,
        )
