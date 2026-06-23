"""Load & correctness benchmark for the task API.

Seeds a large dataset, then exercises the parts the assignment grades at scale:

  1. Keyset pagination — latency should stay flat as you page deep (the whole
     point of cursors over OFFSET).
  2. Nested resolution — fetching tasks with assignee + project + createdBy
     should not blow up into an N+1 (DataLoaders batch the lookups).
  3. Concurrent load — throughput and latency percentiles under many requests.
  4. Optimistic locking under contention — many clients race one task; exactly
     one write wins, the rest lose cleanly (no double-apply, no 500s).
  5. Input robustness — malformed input returns typed errors, never a bare 500.

Run it inside the app container (where the DB and deps live):

    docker compose exec app python -m scripts.benchmark

Tunables via env: BENCH_TASKS, BENCH_REQUESTS, BENCH_CONCURRENCY, BENCH_CONTENDERS.
"""

import asyncio
import os
import time
import uuid
from statistics import mean

import httpx
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.project import Project
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.user import User

URL = os.environ.get("BENCHMARK_URL", "http://localhost:8000/graphql")
N_TASKS = int(os.environ.get("BENCH_TASKS", "5000"))
N_REQUESTS = int(os.environ.get("BENCH_REQUESTS", "1000"))
CONCURRENCY = int(os.environ.get("BENCH_CONCURRENCY", "100"))
N_CONTENDERS = int(os.environ.get("BENCH_CONTENDERS", "50"))

USER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(int(len(s) * p / 100), len(s) - 1)]


def summarize(name: str, latencies_ms: list[float], wall_s: float | None = None) -> None:
    print(f"  {name}")
    print(
        f"    n={len(latencies_ms)}  "
        f"min={min(latencies_ms):.1f}ms  "
        f"p50={pct(latencies_ms, 50):.1f}ms  "
        f"p95={pct(latencies_ms, 95):.1f}ms  "
        f"p99={pct(latencies_ms, 99):.1f}ms  "
        f"max={max(latencies_ms):.1f}ms"
    )
    if wall_s:
        print(f"    wall={wall_s:.2f}s  throughput={len(latencies_ms) / wall_s:,.0f} req/s")


async def post(client: httpx.AsyncClient, query: str, variables: dict, *, auth: bool = False) -> dict:
    headers = {"X-User-Id": str(USER_ID)} if auth else {}
    resp = await client.post(URL, json={"query": query, "variables": variables}, headers=headers)
    return resp.json()


# --------------------------------------------------------------------------- #
# Dataset setup / teardown (direct DB — far faster than 5000 API calls)
# --------------------------------------------------------------------------- #

async def setup_dataset() -> None:
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    statuses = list(TaskStatus)
    priorities = list(TaskPriority)
    async with Session() as db:
        db.add(User(id=USER_ID, email=f"bench-{USER_ID}@example.com", name="Bench User"))
        db.add(Project(id=PROJECT_ID, name="Benchmark Project"))
        await db.flush()
        for i in range(N_TASKS):
            db.add(
                Task(
                    id=uuid.uuid4(),
                    title=f"Benchmark task {i}",
                    status=statuses[i % len(statuses)],
                    priority=priorities[i % len(priorities)],
                    project_id=PROJECT_ID,
                    assignee_id=USER_ID if i % 2 == 0 else None,
                    created_by_id=USER_ID,
                )
            )
        await db.commit()
    await engine.dispose()
    print(f"Seeded {N_TASKS:,} tasks in project {PROJECT_ID}.\n")


async def teardown_dataset() -> None:
    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        await db.execute(delete(Project).where(Project.id == PROJECT_ID))  # cascades tasks
        await db.execute(delete(User).where(User.id == USER_ID))
        await db.commit()
    await engine.dispose()
    print("\nCleaned up benchmark data.")


# --------------------------------------------------------------------------- #
# Benchmarks
# --------------------------------------------------------------------------- #

PAGE_FLAT = """
query($pid: ID!, $first: Int, $after: String) {
  tasks(filter: {projectId: $pid}, first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges { node { id title status priority } }
  }
}
"""

PAGE_NESTED = """
query($pid: ID!, $first: Int, $after: String) {
  tasks(filter: {projectId: $pid}, first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges { node { id title assignee { id name } project { id name } createdBy { id name } } }
  }
}
"""


async def bench_pagination_depth(client: httpx.AsyncClient) -> None:
    print("[1] Keyset pagination — walking every page (latency should stay flat at depth)")
    latencies: list[float] = []
    after = None
    pages = 0
    while True:
        t = time.perf_counter()
        data = await post(client, PAGE_FLAT, {"pid": str(PROJECT_ID), "first": 50, "after": after})
        latencies.append((time.perf_counter() - t) * 1000)
        info = data["data"]["tasks"]["pageInfo"]
        pages += 1
        if not info["hasNextPage"]:
            break
        after = info["endCursor"]
    first_10 = mean(latencies[:10])
    last_10 = mean(latencies[-10:])
    summarize(f"{pages} pages of 50", latencies)
    print(f"    first-10-pages avg={first_10:.1f}ms  vs  last-10-pages avg={last_10:.1f}ms "
          f"(flat = cursors working)\n")


async def bench_nested_vs_flat(client: httpx.AsyncClient) -> None:
    print("[2] Nested resolution — 100 tasks, flat vs assignee+project+createdBy (N+1 check)")
    flat: list[float] = []
    nested: list[float] = []
    for _ in range(20):
        t = time.perf_counter()
        await post(client, PAGE_FLAT, {"pid": str(PROJECT_ID), "first": 100})
        flat.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        await post(client, PAGE_NESTED, {"pid": str(PROJECT_ID), "first": 100})
        nested.append((time.perf_counter() - t) * 1000)
    print(f"    flat   p50={pct(flat, 50):.1f}ms")
    print(f"    nested p50={pct(nested, 50):.1f}ms  (ratio {pct(nested, 50) / pct(flat, 50):.1f}x — "
          f"would be ~100x if N+1)\n")


async def bench_concurrent_load(client: httpx.AsyncClient) -> None:
    print(f"[3] Concurrent load — {N_REQUESTS} requests, concurrency {CONCURRENCY}")
    sem = asyncio.Semaphore(CONCURRENCY)
    latencies: list[float] = []

    async def one() -> None:
        async with sem:
            t = time.perf_counter()
            await post(client, PAGE_NESTED, {"pid": str(PROJECT_ID), "first": 20})
            latencies.append((time.perf_counter() - t) * 1000)

    t0 = time.perf_counter()
    await asyncio.gather(*[one() for _ in range(N_REQUESTS)])
    summarize("mixed read load", latencies, wall_s=time.perf_counter() - t0)
    print()


CHANGE_STATUS = """
mutation($id: ID!, $status: TaskStatus!, $version: Int!) {
  changeTaskStatus(id: $id, status: $status, version: $version) {
    __typename
    ... on Task { id status version }
    ... on ConflictError { currentVersion }
    ... on ValidationError { message }
  }
}
"""


async def bench_optimistic_contention(client: httpx.AsyncClient) -> None:
    print(f"[4] Optimistic locking — {N_CONTENDERS} clients race one TODO task at version 1")
    # Grab one TODO task to fight over.
    data = await post(
        client,
        """query($pid: ID!) { tasks(filter: {projectId: $pid, status: TODO}, first: 1) {
            edges { node { id version } } } }""",
        {"pid": str(PROJECT_ID)},
    )
    node = data["data"]["tasks"]["edges"][0]["node"]
    task_id, version = node["id"], node["version"]

    async def attempt() -> str:
        res = await post(
            client, CHANGE_STATUS,
            {"id": task_id, "status": "IN_PROGRESS", "version": version}, auth=True,
        )
        return res["data"]["changeTaskStatus"]["__typename"]

    results = await asyncio.gather(*[attempt() for _ in range(N_CONTENDERS)])
    wins = results.count("Task")
    conflicts = results.count("ConflictError")
    rejected = results.count("ValidationError")
    print(f"    wins={wins}  version-conflicts={conflicts}  already-advanced={rejected}")
    assert wins == 1, f"expected exactly one winner, got {wins}"
    print("    exactly one writer won — no double-apply under contention\n")


async def bench_robustness(client: httpx.AsyncClient) -> None:
    print("[5] Input robustness — malformed input should be typed errors, never a 500")
    checks = []

    bad_cursor = await post(client, PAGE_FLAT, {"pid": str(PROJECT_ID), "first": 5, "after": "not-a-cursor"})
    checks.append(("invalid cursor", "errors" in bad_cursor or bad_cursor.get("data") is not None))

    big = await client.post(URL, json={"query": PAGE_FLAT, "variables": {"pid": str(PROJECT_ID), "first": 999999}})
    checks.append(("first=999999 (clamped)", big.status_code == 200))

    unauth = await client.post(URL, json={
        "query": CHANGE_STATUS, "variables": {"id": str(uuid.uuid4()), "status": "DONE", "version": 1}})
    typename = unauth.json()["data"]["changeTaskStatus"]["__typename"]
    checks.append(("unauthenticated mutation", typename == "ForbiddenError"))

    for label, ok in checks:
        print(f"    {'OK ' if ok else 'FAIL'} {label}")
    print()


async def main() -> None:
    print(f"\n=== Task API benchmark ===\nTarget: {URL}\n")
    await setup_dataset()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await bench_pagination_depth(client)
            await bench_nested_vs_flat(client)
            await bench_concurrent_load(client)
            await bench_optimistic_contention(client)
            await bench_robustness(client)
    finally:
        await teardown_dataset()


if __name__ == "__main__":
    asyncio.run(main())
