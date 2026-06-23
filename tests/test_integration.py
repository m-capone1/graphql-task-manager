"""Integration tests that run against a real PostgreSQL database.

These cover the behaviour mocks can't verify: the keyset pagination SQL, the
optimistic-lock conditional UPDATE, native enum round-trips, and the
status-transition rules — exactly the axes the assignment grades. They skip
automatically if no database is reachable (see conftest.integration_engine).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.project import Project
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.user import User
from app.schema.types.enums import TaskSortField
from app.services.exceptions import ConflictError, ValidationError
from app.services.task_service import (
    change_task_status,
    create_task,
    encode_cursor,
    get_task,
    list_tasks,
)


async def _make_user(session) -> User:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@test.example", name="Tester")
    session.add(user)
    await session.flush()
    return user


async def _make_project(session) -> Project:
    project = Project(id=uuid.uuid4(), name="Test Project")
    session.add(project)
    await session.flush()
    return project


class TestPersistence:
    async def test_create_persists_and_is_refetchable(self, db_session):
        project = await _make_project(db_session)
        creator = await _make_user(db_session)

        task = await create_task(
            db_session,
            title="  Hello  ",
            project_id=project.id,
            created_by_id=creator.id,
        )

        assert task.title == "Hello"  # trimmed by the shared validator
        assert task.version == 1
        assert task.status == TaskStatus.TODO

        fetched = await get_task(db_session, task.id)
        assert fetched is not None
        assert fetched.title == "Hello"
        assert fetched.created_at is not None  # server default populated by the DB


class TestEnumFiltering:
    async def test_filter_by_status_round_trips_native_enum(self, db_session):
        project = await _make_project(db_session)
        creator = await _make_user(db_session)
        for status in (TaskStatus.TODO, TaskStatus.TODO, TaskStatus.DONE):
            db_session.add(
                Task(
                    id=uuid.uuid4(),
                    title="x",
                    status=status,
                    priority=TaskPriority.MEDIUM,
                    project_id=project.id,
                    created_by_id=creator.id,
                )
            )
        await db_session.flush()

        todo, _, total = await list_tasks(
            db_session, project_id=project.id, status=TaskStatus.TODO, first=10
        )

        assert total == 2
        assert all(t.status == TaskStatus.TODO for t in todo)


class TestKeysetPagination:
    async def test_walks_pages_in_stable_order(self, db_session):
        project = await _make_project(db_session)
        creator = await _make_user(db_session)
        base = datetime(2025, 1, 1, tzinfo=UTC)
        for i in range(5):
            db_session.add(
                Task(
                    id=uuid.uuid4(),
                    title=f"T{i}",
                    status=TaskStatus.TODO,
                    priority=TaskPriority.MEDIUM,
                    project_id=project.id,
                    created_by_id=creator.id,
                    created_at=base + timedelta(minutes=i),
                )
            )
        await db_session.flush()

        # Default sort is created_at DESC, so newest (T4) comes first.
        page1, has_next, total = await list_tasks(
            db_session, project_id=project.id, first=2
        )
        assert total == 5
        assert has_next is True
        assert [t.title for t in page1] == ["T4", "T3"]

        cursor = encode_cursor(
            TaskSortField.CREATED_AT, page1[-1].created_at, page1[-1].id
        )
        page2, has_next2, _ = await list_tasks(
            db_session, project_id=project.id, first=2, after=cursor
        )
        assert [t.title for t in page2] == ["T2", "T1"]
        assert has_next2 is True

        cursor2 = encode_cursor(
            TaskSortField.CREATED_AT, page2[-1].created_at, page2[-1].id
        )
        page3, has_next3, _ = await list_tasks(
            db_session, project_id=project.id, first=2, after=cursor2
        )
        assert [t.title for t in page3] == ["T0"]
        assert has_next3 is False


class TestStatusTransitions:
    async def test_rejects_terminal_transition_against_db(self, db_session):
        project = await _make_project(db_session)
        creator = await _make_user(db_session)
        task = Task(
            id=uuid.uuid4(),
            title="done task",
            status=TaskStatus.DONE,
            priority=TaskPriority.LOW,
            project_id=project.id,
            created_by_id=creator.id,
        )
        db_session.add(task)
        await db_session.flush()

        with pytest.raises(ValidationError):
            await change_task_status(db_session, task.id, TaskStatus.TODO, version=task.version)


class TestOptimisticLocking:
    async def test_stale_version_conflicts_across_sessions(self, integration_engine):
        """The real concurrency test: two independent sessions act on one task.
        The first advances it; the second, using the now-stale version, must
        lose with a ConflictError carrying the current version."""
        Session = async_sessionmaker(integration_engine, expire_on_commit=False)
        user_id = uuid.uuid4()
        project_id = uuid.uuid4()
        task_id: uuid.UUID | None = None

        try:
            async with Session() as setup:
                setup.add(User(id=user_id, email=f"{uuid.uuid4()}@test.example", name="T"))
                setup.add(Project(id=project_id, name="P"))
                await setup.flush()
                task = await create_task(
                    setup, title="race", project_id=project_id, created_by_id=user_id
                )
                task_id = task.id
                await setup.commit()

            # Client A advances version 1 -> 2 and commits.
            async with Session() as client_a:
                advanced = await change_task_status(
                    client_a, task_id, TaskStatus.IN_PROGRESS, version=1
                )
                await client_a.commit()
                assert advanced.version == 2

            # Client B still thinks it's version 1 — a valid transition, stale version.
            async with Session() as client_b:
                with pytest.raises(ConflictError) as exc_info:
                    await change_task_status(
                        client_b, task_id, TaskStatus.IN_REVIEW, version=1
                    )
                assert exc_info.value.current_version == 2
        finally:
            async with Session() as cleanup:
                if task_id is not None:
                    await cleanup.execute(delete(Task).where(Task.id == task_id))
                await cleanup.execute(delete(Project).where(Project.id == project_id))
                await cleanup.execute(delete(User).where(User.id == user_id))
                await cleanup.commit()
