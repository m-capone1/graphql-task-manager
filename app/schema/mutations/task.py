import uuid

import strawberry
from strawberry.types import Info

from app.schema.types.enums import TaskStatus, gql_priority_to_orm, gql_status_to_orm
from app.schema.types.errors import (
    ConflictError as GQLConflictError,
    DeleteSuccess,
    ForbiddenError as GQLForbiddenError,
    NotFoundError as GQLNotFoundError,
    ValidationError as GQLValidationError,
)
from app.schema.types.task import (
    CreateTaskInput,
    DeleteResult,
    TaskResult,
    TaskType,
    UpdateTaskInput,
)
from app.services import exceptions as svc
from app.services import task_service


def _parse_uuid(raw: str, label: str) -> uuid.UUID | GQLValidationError:
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return GQLValidationError(message=f"Invalid {label}", field=label)


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_task(self, info: Info, input: CreateTaskInput) -> TaskResult:
        if info.context.current_user is None:
            return GQLForbiddenError(message="Authentication required")

        project_id = _parse_uuid(str(input.project_id), "projectId")
        if isinstance(project_id, GQLValidationError):
            return project_id

        assignee_id: uuid.UUID | None = None
        if input.assignee_id is not None and input.assignee_id is not strawberry.UNSET:
            parsed = _parse_uuid(str(input.assignee_id), "assigneeId")
            if isinstance(parsed, GQLValidationError):
                return parsed
            assignee_id = parsed

        try:
            task = await task_service.create_task(
                info.context.db,
                title=input.title,
                project_id=project_id,
                description=input.description,
                priority=gql_priority_to_orm(input.priority),
                assignee_id=assignee_id,
                created_by_id=info.context.current_user.id,
            )
        except svc.ValidationError as e:
            return GQLValidationError(message=e.message, field=e.field)
        except svc.NotFoundError as e:
            return GQLNotFoundError(message=str(e))

        await info.context.db.commit()
        return TaskType.from_orm(task)

    @strawberry.mutation
    async def update_task(
        self, info: Info, id: strawberry.ID, input: UpdateTaskInput
    ) -> TaskResult:
        if info.context.current_user is None:
            return GQLForbiddenError(message="Authentication required")

        task_id = _parse_uuid(str(id), "id")
        if isinstance(task_id, GQLValidationError):
            return GQLNotFoundError(message=f"Task {id} not found")

        kwargs: dict = {}

        if input.title is not strawberry.UNSET:
            kwargs["title"] = input.title

        if input.description is not strawberry.UNSET:
            kwargs["description"] = input.description

        if input.priority is not strawberry.UNSET and input.priority is not None:
            kwargs["priority"] = gql_priority_to_orm(input.priority)

        if input.assignee_id is not strawberry.UNSET:
            if input.assignee_id is not None:
                parsed = _parse_uuid(str(input.assignee_id), "assigneeId")
                if isinstance(parsed, GQLValidationError):
                    return parsed
                kwargs["assignee_id"] = parsed
            else:
                kwargs["assignee_id"] = None

        try:
            task = await task_service.update_task(info.context.db, task_id, **kwargs)
        except svc.NotFoundError as e:
            return GQLNotFoundError(message=str(e))
        except svc.ValidationError as e:
            return GQLValidationError(message=e.message, field=e.field)

        await info.context.db.commit()
        return TaskType.from_orm(task)

    @strawberry.mutation
    async def change_task_status(
        self, info: Info, id: strawberry.ID, status: TaskStatus, version: int
    ) -> TaskResult:
        if info.context.current_user is None:
            return GQLForbiddenError(message="Authentication required")

        task_id = _parse_uuid(str(id), "id")
        if isinstance(task_id, GQLValidationError):
            return GQLNotFoundError(message=f"Task {id} not found")

        try:
            task = await task_service.change_task_status(
                info.context.db,
                task_id,
                gql_status_to_orm(status),
                version,
            )
        except svc.NotFoundError as e:
            return GQLNotFoundError(message=str(e))
        except svc.ValidationError as e:
            return GQLValidationError(message=e.message, field=e.field)
        except svc.ConflictError as e:
            return GQLConflictError(message=e.message, current_version=e.current_version)

        await info.context.db.commit()
        return TaskType.from_orm(task)

    @strawberry.mutation
    async def assign_task(
        self, info: Info, id: strawberry.ID, user_id: strawberry.ID | None
    ) -> TaskResult:
        if info.context.current_user is None:
            return GQLForbiddenError(message="Authentication required")

        task_id = _parse_uuid(str(id), "id")
        if isinstance(task_id, GQLValidationError):
            return GQLNotFoundError(message=f"Task {id} not found")

        assignee_id: uuid.UUID | None = None
        if user_id is not None:
            parsed = _parse_uuid(str(user_id), "userId")
            if isinstance(parsed, GQLValidationError):
                return parsed
            assignee_id = parsed

        try:
            task = await task_service.update_task(
                info.context.db,
                task_id,
                assignee_id=assignee_id,
            )
        except svc.NotFoundError as e:
            return GQLNotFoundError(message=str(e))

        await info.context.db.commit()
        return TaskType.from_orm(task)

    @strawberry.mutation
    async def delete_task(self, info: Info, id: strawberry.ID) -> DeleteResult:
        if info.context.current_user is None:
            return GQLForbiddenError(message="Authentication required")

        task_id = _parse_uuid(str(id), "id")
        if isinstance(task_id, GQLValidationError):
            return GQLNotFoundError(message=f"Task {id} not found")

        try:
            await task_service.delete_task(
                info.context.db,
                task_id,
                info.context.current_user.id,
            )
        except svc.NotFoundError as e:
            return GQLNotFoundError(message=str(e))
        except svc.ForbiddenError as e:
            return GQLForbiddenError(message=e.message)

        await info.context.db.commit()
        return DeleteSuccess(id=id)
