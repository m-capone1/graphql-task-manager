"""Seed the database with sample users, projects, and tasks for manual testing."""

import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.project import Project
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.user import User

# Fixed UUIDs so re-running the script is idempotent
ALICE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
BOB_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
PROJ_BACKEND_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
PROJ_MOBILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000011")


async def seed() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        await _seed(db)
        await db.commit()

    await engine.dispose()
    print("Seed complete.")


async def _seed(db: AsyncSession) -> None:
    # Users
    await db.execute(
        text(
            "INSERT INTO users (id, email, name) VALUES (:id, :email, :name) ON CONFLICT DO NOTHING"
        ),
        [
            {"id": str(ALICE_ID), "email": "alice@example.com", "name": "Alice"},
            {"id": str(BOB_ID), "email": "bob@example.com", "name": "Bob"},
        ],
    )

    # Projects
    await db.execute(
        text(
            "INSERT INTO projects (id, name, description) VALUES (:id, :name, :desc) ON CONFLICT DO NOTHING"
        ),
        [
            {"id": str(PROJ_BACKEND_ID), "name": "Backend API", "desc": "GraphQL task management API"},
            {"id": str(PROJ_MOBILE_ID), "name": "Mobile App", "desc": "iOS and Android client"},
        ],
    )

    # Tasks — only insert if they don't already exist
    tasks = [
        Task(
            id=uuid.UUID("00000000-0000-0000-0001-000000000001"),
            title="Set up CI pipeline",
            description="Configure GitHub Actions for lint, test, and build.",
            status=TaskStatus.DONE,
            priority=TaskPriority.HIGH,
            project_id=PROJ_BACKEND_ID,
            assignee_id=ALICE_ID,
            created_by_id=ALICE_ID,
        ),
        Task(
            id=uuid.UUID("00000000-0000-0000-0001-000000000002"),
            title="Implement cursor pagination",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            project_id=PROJ_BACKEND_ID,
            assignee_id=BOB_ID,
            created_by_id=ALICE_ID,
        ),
        Task(
            id=uuid.UUID("00000000-0000-0000-0001-000000000003"),
            title="Write API documentation",
            status=TaskStatus.TODO,
            priority=TaskPriority.MEDIUM,
            project_id=PROJ_BACKEND_ID,
            created_by_id=BOB_ID,
        ),
        Task(
            id=uuid.UUID("00000000-0000-0000-0001-000000000004"),
            title="Design login screen",
            description="Figma mockups for the auth flow.",
            status=TaskStatus.IN_REVIEW,
            priority=TaskPriority.CRITICAL,
            project_id=PROJ_MOBILE_ID,
            assignee_id=ALICE_ID,
            created_by_id=BOB_ID,
        ),
        Task(
            id=uuid.UUID("00000000-0000-0000-0001-000000000005"),
            title="Fix push notification bug",
            status=TaskStatus.TODO,
            priority=TaskPriority.CRITICAL,
            project_id=PROJ_MOBILE_ID,
            created_by_id=BOB_ID,
        ),
    ]

    for task in tasks:
        result = await db.execute(
            text("SELECT 1 FROM tasks WHERE id = :id"), {"id": str(task.id)}
        )
        if result.scalar() is None:
            db.add(task)

    print(f"Seeded 2 users, 2 projects, {len(tasks)} tasks.")
    print(f"\nUseful IDs for testing:")
    print(f"  Alice (X-User-Id):  {ALICE_ID}")
    print(f"  Bob   (X-User-Id):  {BOB_ID}")
    print(f"  Backend API project: {PROJ_BACKEND_ID}")
    print(f"  Mobile App project:  {PROJ_MOBILE_ID}")


if __name__ == "__main__":
    asyncio.run(seed())
