# Lush Task Management API

A GraphQL API for managing tasks within projects. Built with Python, Strawberry GraphQL, FastAPI, and PostgreSQL.

---

## Quick Start

**Requirements:** Docker and Docker Compose.

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000/graphql` with the interactive GraphiQL explorer at the same URL in a browser.

Migrations run automatically on startup via `alembic upgrade head`.

A Makefile is included for common tasks:

| Command | Description |
|---|---|
| `make up` | Start containers in the background |
| `make build` | Start containers with a fresh build |
| `make restart` | Tear down and rebuild from scratch |
| `make down` | Stop containers and remove volumes |
| `make test` | Run the test suite inside the container |
| `make lint` | Run `ruff` linting inside the container |

---

## Local Development (without Docker)

**Requirements:** Python 3.11+, a running PostgreSQL instance.

```bash
# Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your database URL

# Run migrations
alembic upgrade head

# Start the server
uvicorn app.main:app --reload
```

---

## Authentication

This API uses a stub auth mechanism: pass a valid user UUID in the `X-User-Id` header. Write mutations (`createTask`, `updateTask`, `changeTaskStatus`, `assignTask`, `deleteTask`) return `ForbiddenError` if the header is missing or doesn't match a known user.

```http
X-User-Id: <user-uuid>
```

In production this would be swapped for a real identity provider like Auth0 — the header becomes a JWT bearer token, verified against the provider's JWKS endpoint, with the user ID pulled from the token claims.

---

## API Reference

The full interactive schema is available via GraphiQL at `/graphql`. Below are the key operations.

### Queries

#### Fetch a single task

```graphql
query {
  task(id: "<task-uuid>") {
    ... on Task {
      id
      title
      status
      priority
      version
      project { id name }
      assignee { id name email }
    }
    ... on NotFoundError { message }
  }
}
```

#### List tasks with filtering and pagination

```graphql
query {
  tasks(
    filter: { projectId: "<project-uuid>", status: IN_PROGRESS }
    sort: { field: CREATED_AT, direction: DESC }
    first: 20
    after: "<cursor>"
  ) {
    totalCount
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      cursor
      node {
        id
        title
        status
        priority
      }
    }
  }
}
```

### Mutations

#### Create a task

```graphql
mutation {
  createTask(input: {
    title: "Implement login page"
    projectId: "<project-uuid>"
    priority: HIGH
    description: "Use the existing design system components"
  }) {
    ... on Task { id title status version }
    ... on NotFoundError { message }
    ... on ValidationError { message field }
    ... on ForbiddenError { message }
  }
}
```

#### Update a task

```graphql
mutation {
  updateTask(id: "<task-uuid>", input: {
    title: "Updated title"
    priority: CRITICAL
  }) {
    ... on Task { id title priority }
    ... on NotFoundError { message }
    ... on ValidationError { message field }
    ... on ForbiddenError { message }
  }
}
```

#### Change task status (with optimistic locking)

```graphql
mutation {
  changeTaskStatus(id: "<task-uuid>", status: IN_REVIEW, version: 2) {
    ... on Task { id status version }
    ... on ConflictError { message currentVersion }
    ... on NotFoundError { message }
    ... on ForbiddenError { message }
  }
}
```

The `version` field must match the task's current version in the database. If another client has modified the task concurrently, a `ConflictError` is returned with the latest version so the client can retry.

Valid status transitions:

```
TODO → IN_PROGRESS → IN_REVIEW → DONE
                               → CANCELLED
```

`DONE` and `CANCELLED` are terminal — no further transitions are allowed.

#### Assign / unassign a task

```graphql
# Assign
mutation { assignTask(id: "<task-uuid>", userId: "<user-uuid>") {
  ... on Task { id assignee { name } }
  ... on NotFoundError { message }
}}

# Unassign
mutation { assignTask(id: "<task-uuid>", userId: null) {
  ... on Task { id assignee { name } }
}}
```

#### Delete a task

Only the task creator or current assignee can delete a task.

```graphql
mutation {
  deleteTask(id: "<task-uuid>") {
    ... on DeleteSuccess { id }
    ... on NotFoundError { message }
    ... on ForbiddenError { message }
  }
}
```

### Error types

All mutations return a union type. Clients should always inline-fragment on `__typename`:

| Type | When |
|---|---|
| `NotFoundError` | Task, project, or user UUID not found |
| `ValidationError` | Input fails validation (includes `field`) |
| `ConflictError` | Optimistic lock mismatch on status change (includes `currentVersion`) |
| `ForbiddenError` | Auth header missing, or permission denied |

---

## Key Engineering Decisions

### Cursor-based pagination
`tasks` uses keyset pagination on `(sort_col, id)` rather than `OFFSET`. Offset pagination falls apart at scale — `OFFSET 5000` still scans 5000 rows regardless. Keyset cursors encode the last-seen position, so each page is a bounded index seek. `first` is clamped to 1–100.

The downside is that cursors are opaque and forward-only. You can't jump to page 5 or seek to an arbitrary position, which rules out traditional page number controls. That's a fine tradeoff for infinite scroll or load-more UIs, which is the common pattern for task lists.

### Optimistic locking
Tasks carry a `version` integer. `changeTaskStatus` requires the client to pass the current version — if it doesn't match what's in the database, the mutation returns a `ConflictError` with the actual current version so the client can retry. No locks are held; the check is a single conditional update.

Locking is intentionally scoped to status changes. Status is where concurrent conflicts actually matter — two people closing the same ticket simultaneously is a real problem. For metadata like title or priority, last-write-wins is acceptable; the cost of a concurrent rename is low and forcing clients to send `version` on every field edit makes the API worse for little gain.

### DataLoaders (N+1 prevention)
Without DataLoaders, fetching 50 tasks and their assignees and projects would fire 100+ queries. A `UserDataLoader` and `ProjectDataLoader` batch all ID lookups within a request into a single query per type.

The cost is a small latency tick — the loader waits to collect all IDs before firing. In practice it's unmeasurable compared to the queries it eliminates.

### Typed error unions
Errors are typed GraphQL members, not HTTP error codes or generic `errors[]` strings. Clients inline-fragment on `__typename` and get structured fields — `field` on `ValidationError`, `currentVersion` on `ConflictError` — rather than parsing an error message.

One thing to be aware of: GraphQL always returns HTTP 200, so monitoring tools that alert on status codes won't catch application errors. Structured logging picks up the slack here, and in production you'd want metrics that track error `__typename` counts from the response body.

### Auth stub
`X-User-Id` stands in for real authentication. The stub is enough to test auth enforcement without the infrastructure overhead of a real identity provider.

In practice the auth context does two things: it stamps `created_by_id` on new tasks, and it restricts deletion to the task's creator or current assignee. Any authenticated user can edit or transition a task — that's how most team tools work, and it's a reasonable default. Locking edits down to the creator/assignee is a straightforward extension if the requirements called for it.

---

## What Was Left Out

- **Real authentication** — JWT/OAuth integration is hours of additional scope. The `X-User-Id` stub exercises the same authorization paths.
- **Project CRUD** — Projects can be seeded directly into the database. The assessment focus is task management.
- **GraphQL subscriptions** — Requires a persistent transport (WebSockets, SSE); out of scope.
- **Full test coverage** — Tests cover the service logic, concurrency paths, and error cases. Happy-path integration coverage for every mutation is not exhaustive.

---

## With More Time

- **Rate limiting** — since everything goes through a single endpoint, per-IP HTTP rate limiting doesn't get you far. What you actually want is per-user limits on mutations and query depth/complexity limits to stop someone crafting an expensive nested query. Strawberry has extension hooks for this.
- **Broader test coverage** — I'd add integration tests for every mutation's happy path, pagination edge cases (empty pages, single-item pages, cursor stability when rows are inserted mid-browse), and the full set of invalid status transitions.

---

## Testing

```bash
# Requires a running PostgreSQL instance (or use the Docker db service)
pytest tests/ -v
```

The test suite uses a separate test database, rolls back each test in a transaction, and covers:
- Task service unit tests (create, update, status transitions, conflict detection, permissions)
- GraphQL integration tests (queries, mutations, error union responses)

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://lush:lush_secret@localhost:5432/lush_tasks` | Async PostgreSQL connection string |
| `DEBUG` | `false` | Enable debug mode |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
