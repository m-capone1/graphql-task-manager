import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.exceptions import ConflictError, NotFoundError, ValidationError
from tests.conftest import make_mock_task

GQL_URL = "/graphql"


async def gql(client, query: str, variables: dict | None = None) -> dict:
    resp = await client.post(GQL_URL, json={"query": query, "variables": variables or {}})
    resp.raise_for_status()
    return resp.json()


class TestTaskQuery:
    QUERY = """
    query GetTask($id: ID!) {
        task(id: $id) {
            ... on TaskType { id title status version }
            ... on NotFoundError { message }
        }
    }
    """

    async def test_returns_task_by_id(self, client):
        mock_task = make_mock_task(title="Found It")

        with patch("app.services.task_service.get_task", AsyncMock(return_value=mock_task)):
            data = await gql(client, self.QUERY, {"id": str(mock_task.id)})

        result = data["data"]["task"]
        assert result["title"] == "Found It"
        assert result["status"] == "TODO"

    async def test_not_found_returns_error_type(self, client):
        with patch("app.services.task_service.get_task", AsyncMock(return_value=None)):
            data = await gql(client, self.QUERY, {"id": str(uuid.uuid4())})

        assert "message" in data["data"]["task"]


class TestTasksQuery:
    QUERY = """
    query Tasks($first: Int, $after: String) {
        tasks(first: $first, after: $after) {
            edges {
                node { id title status }
                cursor
            }
            pageInfo {
                hasNextPage
                hasPreviousPage
                startCursor
                endCursor
            }
            totalCount
        }
    }
    """

    async def test_returns_task_list(self, client):
        mock_task = make_mock_task(title="First Task")

        with patch("app.services.task_service.list_tasks", AsyncMock(return_value=([mock_task], False, 1))):
            data = await gql(client, self.QUERY, {"first": 10})

        result = data["data"]["tasks"]
        assert result["totalCount"] == 1
        assert len(result["edges"]) == 1
        assert result["edges"][0]["node"]["title"] == "First Task"
        assert result["pageInfo"]["hasNextPage"] is False
        assert result["pageInfo"]["hasPreviousPage"] is False

    async def test_empty_list(self, client):
        with patch("app.services.task_service.list_tasks", AsyncMock(return_value=([], False, 0))):
            data = await gql(client, self.QUERY)

        result = data["data"]["tasks"]
        assert result["totalCount"] == 0
        assert result["edges"] == []
        assert result["pageInfo"]["startCursor"] is None
        assert result["pageInfo"]["endCursor"] is None

    async def test_has_next_page(self, client):
        tasks = [make_mock_task() for _ in range(2)]

        with patch("app.services.task_service.list_tasks", AsyncMock(return_value=(tasks, True, 10))):
            data = await gql(client, self.QUERY, {"first": 2})

        result = data["data"]["tasks"]
        assert result["pageInfo"]["hasNextPage"] is True
        assert result["totalCount"] == 10
        assert result["pageInfo"]["startCursor"] is not None
        assert result["pageInfo"]["endCursor"] is not None

    async def test_after_cursor_sets_has_previous_page(self, client):
        mock_task = make_mock_task()
        fake_cursor = "somecursor"

        with patch("app.services.task_service.list_tasks", AsyncMock(return_value=([mock_task], False, 5))):
            data = await gql(client, self.QUERY, {"after": fake_cursor})

        assert data["data"]["tasks"]["pageInfo"]["hasPreviousPage"] is True


class TestCreateTaskMutation:
    MUTATION = """
    mutation CreateTask($input: CreateTaskInput!) {
        createTask(input: $input) {
            ... on TaskType { id title status version }
            ... on ValidationError { message field }
            ... on ForbiddenError { message }
            ... on NotFoundError { message }
        }
    }
    """

    def _input(self, title="New Task", project_id=None):
        return {"title": title, "projectId": str(project_id or uuid.uuid4())}

    async def test_creates_task(self, client):
        mock_task = make_mock_task(title="New Task")

        with patch("app.services.task_service.create_task", AsyncMock(return_value=mock_task)):
            data = await gql(client, self.MUTATION, {"input": self._input()})

        result = data["data"]["createTask"]
        assert result["title"] == "New Task"
        assert result["status"] == "TODO"
        assert result["version"] == 1

    async def test_requires_auth(self, unauthed_client):
        data = await gql(unauthed_client, self.MUTATION, {"input": self._input()})
        assert data["data"]["createTask"]["message"] == "Authentication required"

    async def test_validation_error_from_service(self, client):
        err = ValidationError("Title cannot be empty", field="title")
        with patch("app.services.task_service.create_task", AsyncMock(side_effect=err)):
            data = await gql(client, self.MUTATION, {"input": self._input(title="   ")})

        result = data["data"]["createTask"]
        assert result["field"] == "title"

    async def test_project_not_found(self, client):
        err = NotFoundError("Project", str(uuid.uuid4()))
        with patch("app.services.task_service.create_task", AsyncMock(side_effect=err)):
            data = await gql(client, self.MUTATION, {"input": self._input()})

        assert "message" in data["data"]["createTask"]


class TestUpdateTaskMutation:
    MUTATION = """
    mutation UpdateTask($id: ID!, $input: UpdateTaskInput!) {
        updateTask(id: $id, input: $input) {
            ... on TaskType { id title priority }
            ... on ValidationError { message field }
            ... on NotFoundError { message }
            ... on ForbiddenError { message }
        }
    }
    """

    def _vars(self, task_id=None, **input_fields):
        return {"id": str(task_id or uuid.uuid4()), "input": input_fields}

    async def test_updates_task(self, client):
        mock_task = make_mock_task(title="Updated Title")

        with patch("app.services.task_service.update_task", AsyncMock(return_value=mock_task)):
            data = await gql(client, self.MUTATION, self._vars(title="Updated Title"))

        assert data["data"]["updateTask"]["title"] == "Updated Title"

    async def test_requires_auth(self, unauthed_client):
        data = await gql(unauthed_client, self.MUTATION, self._vars(title="Anything"))
        assert data["data"]["updateTask"]["message"] == "Authentication required"

    async def test_not_found(self, client):
        err = NotFoundError("Task", str(uuid.uuid4()))
        with patch("app.services.task_service.update_task", AsyncMock(side_effect=err)):
            data = await gql(client, self.MUTATION, self._vars(title="New Title"))

        assert "message" in data["data"]["updateTask"]

    async def test_validation_error(self, client):
        err = ValidationError("Title cannot be empty", field="title")
        with patch("app.services.task_service.update_task", AsyncMock(side_effect=err)):
            data = await gql(client, self.MUTATION, self._vars(title=""))

        result = data["data"]["updateTask"]
        assert result["field"] == "title"


class TestAssignTaskMutation:
    MUTATION = """
    mutation AssignTask($id: ID!, $userId: ID) {
        assignTask(id: $id, userId: $userId) {
            ... on TaskType { id assigneeId }
            ... on NotFoundError { message }
            ... on ForbiddenError { message }
        }
    }
    """

    async def test_assigns_user(self, client):
        user_id = uuid.uuid4()
        mock_task = make_mock_task(assignee_id=user_id)

        with patch("app.services.task_service.update_task", AsyncMock(return_value=mock_task)):
            data = await gql(client, self.MUTATION, {"id": str(uuid.uuid4()), "userId": str(user_id)})

        assert data["data"]["assignTask"]["assigneeId"] == str(user_id)

    async def test_unassigns_user(self, client):
        mock_task = make_mock_task(assignee_id=None)

        with patch("app.services.task_service.update_task", AsyncMock(return_value=mock_task)):
            data = await gql(client, self.MUTATION, {"id": str(uuid.uuid4()), "userId": None})

        assert data["data"]["assignTask"]["assigneeId"] is None

    async def test_requires_auth(self, unauthed_client):
        data = await gql(unauthed_client, self.MUTATION, {"id": str(uuid.uuid4()), "userId": str(uuid.uuid4())})
        assert data["data"]["assignTask"]["message"] == "Authentication required"

    async def test_not_found(self, client):
        err = NotFoundError("Task", str(uuid.uuid4()))
        with patch("app.services.task_service.update_task", AsyncMock(side_effect=err)):
            data = await gql(client, self.MUTATION, {"id": str(uuid.uuid4()), "userId": str(uuid.uuid4())})

        assert "message" in data["data"]["assignTask"]


class TestChangeTaskStatusMutation:
    MUTATION = """
    mutation ChangeStatus($id: ID!, $status: TaskStatus!, $version: Int!) {
        changeTaskStatus(id: $id, status: $status, version: $version) {
            ... on TaskType { id status version }
            ... on ConflictError { message currentVersion }
            ... on NotFoundError { message }
        }
    }
    """

    def _vars(self, task_id=None, status="IN_PROGRESS", version=1):
        return {"id": str(task_id or uuid.uuid4()), "status": status, "version": version}

    async def test_advances_status(self, client):
        from app.models.task import TaskStatus as ORMStatus

        mock_task = make_mock_task(version=2, status=ORMStatus.IN_PROGRESS)

        with patch(
            "app.services.task_service.change_task_status", AsyncMock(return_value=mock_task)
        ):
            data = await gql(client, self.MUTATION, self._vars())

        result = data["data"]["changeTaskStatus"]
        assert result["status"] == "IN_PROGRESS"
        assert result["version"] == 2

    async def test_conflict_returns_error_type(self, client):
        err = ConflictError("Concurrent modification", current_version=3)
        with patch(
            "app.services.task_service.change_task_status", AsyncMock(side_effect=err)
        ):
            data = await gql(client, self.MUTATION, self._vars(version=99))

        result = data["data"]["changeTaskStatus"]
        assert result["currentVersion"] == 3

    async def test_not_found(self, client):
        err = NotFoundError("Task", str(uuid.uuid4()))
        with patch(
            "app.services.task_service.change_task_status", AsyncMock(side_effect=err)
        ):
            data = await gql(client, self.MUTATION, self._vars())

        assert "message" in data["data"]["changeTaskStatus"]


class TestDeleteTaskMutation:
    MUTATION = """
    mutation DeleteTask($id: ID!) {
        deleteTask(id: $id) {
            ... on DeleteSuccess { id }
            ... on ForbiddenError { message }
            ... on NotFoundError { message }
        }
    }
    """

    async def test_creator_can_delete(self, client):
        task_id = uuid.uuid4()
        with patch("app.services.task_service.delete_task", AsyncMock(return_value=None)):
            data = await gql(client, self.MUTATION, {"id": str(task_id)})

        assert data["data"]["deleteTask"]["id"] == str(task_id)

    async def test_requires_auth(self, unauthed_client):
        data = await gql(unauthed_client, self.MUTATION, {"id": str(uuid.uuid4())})
        assert data["data"]["deleteTask"]["message"] == "Authentication required"

    async def test_not_found(self, client):
        err = NotFoundError("Task", str(uuid.uuid4()))
        with patch("app.services.task_service.delete_task", AsyncMock(side_effect=err)):
            data = await gql(client, self.MUTATION, {"id": str(uuid.uuid4())})

        assert "message" in data["data"]["deleteTask"]
