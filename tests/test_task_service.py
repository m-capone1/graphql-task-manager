import uuid
from unittest.mock import MagicMock

import pytest

from app.models.task import TaskPriority as ORMPriority, TaskStatus as ORMStatus
from app.services import task_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from tests.conftest import make_execute_result, make_mock_task


class TestCreateTask:
    async def test_rejects_empty_title(self, db):
        with pytest.raises(ValidationError, match="empty"):
            await task_service.create_task(
                db, title="   ", project_id=uuid.uuid4(), created_by_id=uuid.uuid4()
            )
        db.execute.assert_not_called()

    async def test_rejects_title_over_500_chars(self, db):
        with pytest.raises(ValidationError):
            await task_service.create_task(
                db, title="x" * 501, project_id=uuid.uuid4(), created_by_id=uuid.uuid4()
            )

    async def test_project_not_found(self, db):
        db.execute.return_value = make_execute_result(scalar=None)

        with pytest.raises(NotFoundError) as exc_info:
            await task_service.create_task(
                db, title="Task", project_id=uuid.uuid4(), created_by_id=uuid.uuid4()
            )
        assert exc_info.value.resource == "Project"

    async def test_assignee_not_found(self, db):
        mock_project = MagicMock()
        db.execute.side_effect = [
            make_execute_result(scalar=mock_project),
            make_execute_result(scalar=None),
        ]

        with pytest.raises(NotFoundError) as exc_info:
            await task_service.create_task(
                db,
                title="Task",
                project_id=uuid.uuid4(),
                assignee_id=uuid.uuid4(),
                created_by_id=uuid.uuid4(),
            )
        assert exc_info.value.resource == "User"

    async def test_creates_successfully(self, db):
        db.execute.return_value = make_execute_result(scalar=MagicMock())

        task = await task_service.create_task(
            db, title="  New Task  ", project_id=uuid.uuid4(), created_by_id=uuid.uuid4()
        )

        assert task.title == "New Task"
        assert task.status == ORMStatus.TODO
        assert task.priority == ORMPriority.MEDIUM


class TestUpdateTask:
    async def test_not_found(self, db):
        db.execute.return_value = make_execute_result(scalar=None)

        with pytest.raises(NotFoundError) as exc_info:
            await task_service.update_task(db, uuid.uuid4(), title="New Title")
        assert exc_info.value.resource == "Task"

    async def test_updates_title_with_trim(self, db):
        mock_task = make_mock_task(title="Old Title")
        db.execute.return_value = make_execute_result(scalar=mock_task)

        result = await task_service.update_task(db, uuid.uuid4(), title="  Updated  ")

        assert result.title == "Updated"
        db.flush.assert_awaited_once()

    async def test_rejects_empty_title(self, db):
        db.execute.return_value = make_execute_result(scalar=make_mock_task())

        with pytest.raises(ValidationError, match="empty"):
            await task_service.update_task(db, uuid.uuid4(), title="   ")

    async def test_rejects_long_description(self, db):
        db.execute.return_value = make_execute_result(scalar=make_mock_task())

        with pytest.raises(ValidationError):
            await task_service.update_task(db, uuid.uuid4(), description="x" * 10_001)

    async def test_assignee_not_found(self, db):
        db.execute.side_effect = [
            make_execute_result(scalar=make_mock_task()),
            make_execute_result(scalar=None),
        ]

        with pytest.raises(NotFoundError) as exc_info:
            await task_service.update_task(db, uuid.uuid4(), assignee_id=uuid.uuid4())
        assert exc_info.value.resource == "User"

    async def test_unsets_assignee(self, db):
        mock_task = make_mock_task()
        db.execute.return_value = make_execute_result(scalar=mock_task)

        result = await task_service.update_task(db, uuid.uuid4(), assignee_id=None)

        assert result.assignee_id is None


class TestListTasks:
    def _make_list_result(self, tasks: list, total: int):
        count_result = make_execute_result(scalar=total)

        tasks_result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = tasks
        tasks_result.scalars.return_value = scalars
        return [count_result, tasks_result]

    async def test_rejects_first_below_1(self, db):
        with pytest.raises(ValidationError):
            await task_service.list_tasks(db, first=0)

    async def test_rejects_first_above_100(self, db):
        with pytest.raises(ValidationError):
            await task_service.list_tasks(db, first=101)

    async def test_returns_tasks(self, db):
        mock_task = make_mock_task()
        db.execute.side_effect = self._make_list_result([mock_task], total=1)

        tasks, has_next, total = await task_service.list_tasks(db, first=10)

        assert tasks == [mock_task]
        assert has_next is False
        assert total == 1

    async def test_has_next_page(self, db):
        mock_tasks = [make_mock_task() for _ in range(6)]
        db.execute.side_effect = self._make_list_result(mock_tasks, total=10)

        tasks, has_next, total = await task_service.list_tasks(db, first=5)

        assert len(tasks) == 5
        assert has_next is True
        assert total == 10


class TestChangeTaskStatus:
    async def test_advances_status(self, db):
        current = MagicMock(status=ORMStatus.TODO, version=1)
        updated = MagicMock(status=ORMStatus.IN_PROGRESS, version=2)
        db.execute.side_effect = [
            make_execute_result(scalar=current),
            make_execute_result(scalar=updated),
        ]

        result = await task_service.change_task_status(
            db, uuid.uuid4(), ORMStatus.IN_PROGRESS, version=1
        )

        assert result.status == ORMStatus.IN_PROGRESS
        assert result.version == 2

    async def test_rejects_invalid_transition(self, db):
        current = MagicMock(status=ORMStatus.DONE, version=3)
        db.execute.return_value = make_execute_result(scalar=current)

        with pytest.raises(ValidationError):
            await task_service.change_task_status(
                db, uuid.uuid4(), ORMStatus.TODO, version=3
            )

    async def test_conflict_on_stale_version(self, db):
        current = MagicMock(status=ORMStatus.TODO, version=1)
        db.execute.side_effect = [
            make_execute_result(scalar=current),
            make_execute_result(scalar=None),
        ]

        with pytest.raises(ConflictError) as exc_info:
            await task_service.change_task_status(
                db, uuid.uuid4(), ORMStatus.IN_PROGRESS, version=99
            )
        assert exc_info.value.current_version == 1

    async def test_not_found(self, db):
        db.execute.return_value = make_execute_result(scalar=None)

        with pytest.raises(NotFoundError):
            await task_service.change_task_status(
                db, uuid.uuid4(), ORMStatus.IN_PROGRESS, version=1
            )


class TestDeleteTask:
    async def test_creator_can_delete(self, db):
        creator_id = uuid.uuid4()
        mock_task = MagicMock()
        mock_task.created_by_id = creator_id
        mock_task.assignee_id = None
        db.execute.return_value = make_execute_result(scalar=mock_task)

        await task_service.delete_task(db, uuid.uuid4(), creator_id)

        db.delete.assert_called_once_with(mock_task)
        db.flush.assert_awaited_once()

    async def test_assignee_can_delete(self, db):
        assignee_id = uuid.uuid4()
        mock_task = MagicMock()
        mock_task.created_by_id = uuid.uuid4()
        mock_task.assignee_id = assignee_id
        db.execute.return_value = make_execute_result(scalar=mock_task)

        await task_service.delete_task(db, uuid.uuid4(), assignee_id)

        db.delete.assert_called_once_with(mock_task)

    async def test_third_party_cannot_delete(self, db):
        mock_task = MagicMock()
        mock_task.created_by_id = uuid.uuid4()
        mock_task.assignee_id = None
        db.execute.return_value = make_execute_result(scalar=mock_task)

        with pytest.raises(ForbiddenError):
            await task_service.delete_task(db, uuid.uuid4(), uuid.uuid4())

    async def test_not_found(self, db):
        db.execute.return_value = make_execute_result(scalar=None)

        with pytest.raises(NotFoundError):
            await task_service.delete_task(db, uuid.uuid4(), uuid.uuid4())
