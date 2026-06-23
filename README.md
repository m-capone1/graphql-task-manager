# Lush Task Management API

A GraphQL API for managing tasks within projects. Built with Python, Strawberry GraphQL, FastAPI, and PostgreSQL.

---

## Quick Start

**Requirements:** Docker and Docker Compose.

First, create a `.env` file in the project root. Use [`.env.example`](.env.example) as a reference.

```bash
docker compose up --build -d
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
| `make seed` | Load sample users, projects, and tasks |
| `make test` | Run the test suite inside the container |
| `make lint` | Run `ruff` linting inside the container |

### Seed data

Run `make seed` after startup to load sample data for manual testing. It is idempotent — safe to run multiple times.

| Entity | ID | Details |
|---|---|---|
| User: Alice | `00000000-0000-0000-0000-000000000001` | Use as `X-User-Id` header |
| User: Bob | `00000000-0000-0000-0000-000000000002` | Use as `X-User-Id` header |
| Project: Backend API | `00000000-0000-0000-0000-000000000010` | Has 3 tasks |
| Project: Mobile App | `00000000-0000-0000-0000-000000000011` | Has 2 tasks |

Tasks are seeded across all statuses (`TODO`, `IN_PROGRESS`, `IN_REVIEW`, `DONE`) so pagination, filtering, and status transitions can be tested immediately.

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

For example, with `curl`:

```bash
curl -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "X-User-Id: 00000000-0000-0000-0000-000000000001" \
  -d '{"query": "{ tasks(first: 5) { totalCount edges { node { id title status } } } }"}'
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
    ... on ValidationError { message field }
    ... on NotFoundError { message }
    ... on ForbiddenError { message }
  }
}
```

The `version` field must match the task's current version in the database. If another client has modified the task concurrently, a `ConflictError` is returned with the latest version so the client can retry.

Status changes are also constrained to valid workflow transitions (see below). An illegal transition returns a `ValidationError` rather than silently applying.

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

### Status transitions
Status changes are validated against an explicit workflow, not free-form. A task moves `TODO → IN_PROGRESS → IN_REVIEW → DONE`, can be kicked back a step (e.g. a failed review returns `IN_REVIEW → IN_PROGRESS`), and can be `CANCELLED` from any active state. `DONE` and `CANCELLED` are terminal. An illegal transition returns a `ValidationError`.

This is separate from optimistic locking: the version check guards against *concurrent* writes, while the transition rules guard against *invalid* ones. The allowed map lives next to the `TaskStatus` enum so the domain rule sits with the entity it governs.

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
- **Lazy `totalCount`** — `tasks` always runs a `COUNT(*)` over the filtered set for `totalCount`, even when the client doesn't select that field. Under load (see `scripts/benchmark.py`) that's a wasted scan on every request. I'd make `totalCount` a lazily-resolved field so the count only runs when it's actually requested.
- **Request-level transaction boundary** — currently each mutation commits its own work. GraphQL allows several mutations in one document, executed serially, so an early mutation can persist while a later one fails, leaving the request half-applied. I'd move the commit to a single point after the operation completes (e.g. the session dependency or a schema extension) so the whole request succeeds or rolls back together.

---

## Testing

```bash
make test           # runs the whole suite inside the app container
# or, against your own database:
pytest tests/ -v
```

The suite has two layers:

- **Contract tests** (`test_task_service.py`, `test_graphql.py`) mock the database so they run fast and in isolation. They pin down the service-layer branching (validation, permissions, conflict handling) and the GraphQL wiring (error unions resolve to the right `__typename`, auth is enforced).
- **Integration tests** (`test_integration.py`) run against a **real PostgreSQL** database — the part mocks can't prove. They exercise the keyset pagination SQL across multiple pages, the native enum round-trip through a filter, the status-transition rules, and the headline concurrency case: two independent sessions racing on one task, where the stale writer loses with a `ConflictError`.

The integration tests run against the `db` container (already migrated on startup) when invoked via `make test`. If no database is reachable they **skip** rather than fail, so the contract tests still run anywhere. Each test rolls its work back — the database is never polluted. In a real CI pipeline you'd run these against a dedicated throwaway test database rather than the app's own; that's a config change, not a code one (set `TEST_DATABASE_URL`).

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://lush:lush_secret@localhost:5432/lush_tasks` | Async PostgreSQL connection string |
| `DEBUG` | `false` | Enable debug mode |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
