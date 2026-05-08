# Shared DB Runtime and Persistence Standard Design

Date: 2026-05-08
Status: Baseline implemented; repository migration ongoing

Supersedes:

1. `docs/superpowers/specs/2026-05-03-quant-replay-db-isolation-design.md`

## Current Implementation Snapshot

As of `2026-05-08`, the runtime baseline has been introduced and is now the current persistence standard:

1. `app/db/runtime` owns backend configuration, SQLAlchemy engine creation, process-scoped engine caching, session factories, read/write unit-of-work helpers, and health checks.
2. Backend selection is configurable with `APP_DB_BACKEND=sqlite|mysql`.
3. The two named relational stores are `primary` and `replay`.
4. SQLite defaults are `data/xuanwu_stock.db` and `data/xuanwu_stock_replay.db`.
5. MySQL URLs can be supplied directly through `APP_DB_PRIMARY_URL` and `APP_DB_REPLAY_URL`, or assembled from `APP_DB_MYSQL_*` settings.
6. Domain services are being wired through `DatabaseRuntime`; compatibility wrappers remain where existing DB classes still expose sqlite-style methods.
7. Local market data remains a separate non-relational parquet/cache path under `data/local_sources/`.

Remaining migration work is repository-level cleanup, not a change in persistence direction: old direct-DB wrappers should keep moving behind runtime-owned connections and explicit read/write boundaries.

## Background

The product has already outgrown the current pattern of ad hoc SQLite access:

1. Live quant, portfolio diagnosis, monitoring, research, settings, and replay all persist through different DB wrappers.
2. The replay path is especially sensitive because it runs in a worker process, writes frequently, and is polled by HTTP reads at the same time.
3. SQLite itself is not the only issue. The combination of per-call connections, implicit schema creation, mixed read/write behavior in request paths, and unsafe deployment storage surfaces creates avoidable operational risk.
4. The next persistence standard must support both `sqlite` and `mysql` from configuration, without requiring different business logic for each backend.
5. Old data compatibility is not required. We can define a new clean schema and reset environments.

## Goals

1. Introduce a shared DB runtime layer that supports `sqlite` and `mysql` through configuration.
2. Replace direct `sqlite3.connect(...)` usage in application code with a standard runtime, unit-of-work, and repository model.
3. Standardize all relational persistence behind two named stores:
   - `primary`: operational application data
   - `replay`: high-write historical replay data
4. Make engine and connection lifecycle process-scoped rather than method-scoped.
5. Make GET/snapshot/query HTTP paths strictly read-only at the DB layer.
6. Make write behavior explicit through command handlers, workers, schedulers, and write unit-of-work contexts.
7. Move schema ownership to `SQLAlchemy` metadata plus `Alembic` migrations.
8. Support fresh deployments for both SQLite and MySQL with no legacy schema fallback and no old data migration.
9. Establish one persistence standard for all relational modules in `app/`.

## Non-Goals

1. No migration of existing SQLite data to the new schema.
2. No compatibility layer that reads old tables or old DB files.
3. No attempt to move parquet/local-source caches into MySQL or SQLite.
4. No requirement to convert every query into SQLAlchemy ORM syntax; `SQLAlchemy Core` is acceptable where it keeps code simpler.
5. No support for unsafe SQLite deployment topologies such as Docker Desktop `grpcfuse` bind mounts for write-heavy stores.
6. No mixed old/new persistence model where some modules still create tables lazily and others use migrations.

## Target Topology

The new persistence system is split into four layers.

### 1. `app/db/runtime`

Owns:

1. backend selection
2. engine creation
3. connection/session policies
4. transaction helpers
5. read-only vs read-write access modes
6. worker-pinned write sessions
7. health checks
8. backend capability flags

Target files:

1. `app/db/runtime/config.py`
2. `app/db/runtime/types.py`
3. `app/db/runtime/registry.py`
4. `app/db/runtime/engine_factory.py`
5. `app/db/runtime/session.py`
6. `app/db/runtime/uow.py`
7. `app/db/runtime/health.py`

### 2. `app/db/schema`

Owns:

1. SQLAlchemy metadata
2. table definitions
3. common column mixins
4. naming conventions
5. store-specific metadata groupings

Target files:

1. `app/db/schema/base.py`
2. `app/db/schema/common.py`
3. `app/db/schema/primary/*.py`
4. `app/db/schema/replay/*.py`

### 3. `app/db/migrations`

Owns:

1. Alembic environment
2. baseline migrations
3. future schema revisions
4. store bootstrap entrypoints

Target files:

1. `app/db/migrations/alembic.ini`
2. `app/db/migrations/env.py`
3. `app/db/migrations/versions/*.py`
4. `app/db/bootstrap.py`

### 4. `app/db/repositories`

Owns:

1. all relational query and write behavior
2. row-to-domain mapping
3. backend-neutral persistence operations

Business services, gateway handlers, schedulers, and workers may only access relational data through repositories and unit-of-work objects.

Target files:

1. `app/db/repositories/settings_repo.py`
2. `app/db/repositories/stock_universe_repo.py`
3. `app/db/repositories/live_sim_repo.py`
4. `app/db/repositories/strategy_profile_repo.py`
5. `app/db/repositories/replay_repo.py`
6. `app/db/repositories/portfolio_repo.py`
7. `app/db/repositories/monitor_repo.py`
8. `app/db/repositories/smart_monitor_repo.py`
9. `app/db/repositories/research_repo.py`
10. `app/db/repositories/selector_repo.py`
11. `app/db/repositories/analysis_repo.py`
12. `app/db/repositories/ui_cache_repo.py`

## Store Model

The runtime standard defines exactly two relational stores.

### `primary`

Owns all operational application data:

1. stock universe
2. live simulation state
3. strategy profiles
4. portfolio diagnosis state
5. monitor rules and monitor snapshots
6. research outputs persisted in SQL
7. settings and environment-facing preferences
8. analysis context
9. UI cache tables

### `replay`

Owns high-write historical replay artifacts only:

1. replay runs
2. replay checkpoints
3. replay events
4. replay trades
5. replay snapshots
6. replay positions
7. replay signals
8. replay signal details

This keeps replay I/O isolated from the operational app path even when the backend is SQLite.

### Backend Mapping

For SQLite:

1. `primary` -> `data/xuanwu_stock.db`
2. `replay` -> `data/xuanwu_stock_replay.db`

For MySQL:

1. `primary` -> database/schema `xuanwu`
2. `replay` -> database/schema `xuanwu_stock_replay`

The runtime may allow explicit URL overrides, but the logical store names remain `primary` and `replay`.

## Configuration Model

The runtime must be configured by environment variables or equivalent settings, with a single backend switch.

Configuration invariant:

1. `APP_DB_BACKEND` selects one backend family for the entire process
2. explicit store URL overrides are allowed only if both URLs belong to that same backend family
3. mixed backend operation such as `primary=mysql` and `replay=sqlite` is not supported
4. invalid mixed configuration must fail at startup before any migration or request handling begins

### Required top-level switch

1. `APP_DB_BACKEND=sqlite|mysql`

### SQLite configuration

1. `APP_DB_SQLITE_DIR`
2. optional explicit overrides:
   - `APP_DB_PRIMARY_URL`
   - `APP_DB_REPLAY_URL`

Default URL derivation:

1. `sqlite:///.../xuanwu_stock.db`
2. `sqlite:///.../xuanwu_stock_replay.db`

### MySQL configuration

1. `APP_DB_MYSQL_HOST`
2. `APP_DB_MYSQL_PORT`
3. `APP_DB_MYSQL_USER`
4. `APP_DB_MYSQL_PASSWORD`
5. `APP_DB_MYSQL_PRIMARY_DB`
6. `APP_DB_MYSQL_REPLAY_DB`
7. optional explicit overrides:
   - `APP_DB_PRIMARY_URL`
   - `APP_DB_REPLAY_URL`

Default URL derivation:

1. `mysql+pymysql://user:pass@host:port/xuanwu?charset=utf8mb4`
2. `mysql+pymysql://user:pass@host:port/xuanwu_stock_replay?charset=utf8mb4`

Schema bootstrap rule:

1. bootstrap attempts `CREATE DATABASE IF NOT EXISTS <primary_db>` and `CREATE DATABASE IF NOT EXISTS <replay_db>` using the configured MySQL credentials before running Alembic migrations
2. if the configured credentials do not have permission to create schemas, startup must fail with a clear error naming the missing schemas
3. no manual pre-creation step is required in the happy path

### Runtime tuning

Standard tunables:

1. `APP_DB_POOL_SIZE`
2. `APP_DB_MAX_OVERFLOW`
3. `APP_DB_POOL_TIMEOUT_SECONDS`
4. `APP_DB_POOL_RECYCLE_SECONDS`
5. `APP_DB_SQLITE_BUSY_TIMEOUT_MS`
6. `APP_DB_ECHO_SQL`

These settings are runtime-owned. Business modules must not hard-code DB pool or timeout behavior.

## Runtime Contracts

### Engine registry

Each process owns one `DatabaseRuntime` instance. The runtime lazily creates and caches engines keyed by:

1. store name: `primary` or `replay`
2. access mode: `readonly`, `readwrite`, or `worker_write`

The registry is process-scoped. Connection objects are never shared across processes.

### Session profiles

The runtime exposes three session profiles.

1. `readonly`
   - query-only
   - used by GET endpoints, snapshot builders, report loaders, and polling paths
   - commit is forbidden

2. `readwrite`
   - short-lived transaction scope
   - used by POST actions, command handlers, and schedulers

3. `worker_write`
   - long-lived pinned session/connection for background workers
   - used by replay workers or other long-running write-heavy jobs
   - one worker process gets one pinned unit-of-work per target store

### Unit-of-work API

The runtime standard should look like this at the business layer:

```python
with db_runtime.read_uow("primary") as uow:
    repo = StockUniverseRepo(uow.session)
    rows = repo.list_active()

with db_runtime.write_uow("primary") as uow:
    repo = MonitorRepo(uow.session)
    repo.save_rule(payload)
    uow.commit()

with db_runtime.worker_uow("replay") as uow:
    repo = ReplayRepo(uow.session)
    repo.append_checkpoint(...)
    repo.update_progress(...)
    uow.commit()
```

Rules:

1. repositories receive an existing session; they never create one
2. only unit-of-work objects may commit or rollback
3. session lifetime is controlled by the runtime, not by repository methods
4. GET handlers may only use `read_uow`
5. POST handlers may use `write_uow`
6. workers must use `worker_uow`

### Read-only HTTP rule

The current codebase allows GET paths such as replay progress loaders to run code that can mutate state while answering reads. That behavior must end.

New standard:

1. `GET` endpoints are DB read-only.
2. Snapshot builders may derive transient in-memory output but may not write reconciliation rows, progress rows, or cleanup rows.
3. Any state repair or stale-run reconciliation becomes an explicit command or background maintenance task.
4. `POST` endpoints are the only HTTP write paths.

This is especially important for replay, where polling a progress page must not race with a worker by performing writes in the read path.

### Transaction rule

The runtime standard is:

1. one unit-of-work defines one transaction boundary
2. repository methods do not independently commit
3. write-heavy loops should batch related updates into a single transaction per logical step
4. replay checkpoint persistence must be one transaction per checkpoint, not one transaction per row family

That means the current replay pattern of separate commits for progress, signals, runtime trade snapshots, checkpoint rows, and events must be replaced by one checkpoint write transaction owned by `ReplayRepo`.

## Backend-Specific Policy

### SQLite policy

SQLite remains supported, but only under strict operational rules.

#### Engine/session policy

1. `readonly` uses a small stable connection pool with read-only URI mode where supported.
2. `readwrite` uses a constrained pool.
3. `worker_write` uses a single pinned connection per worker process with pool size `1` and no overflow.

#### Required pragmas

For every SQLite write engine:

1. `PRAGMA journal_mode = WAL`
2. `PRAGMA synchronous = NORMAL`
3. `PRAGMA foreign_keys = ON`
4. `PRAGMA busy_timeout = <configured>`

#### Deployment rule

SQLite write stores are only supported on local filesystems or Docker named volumes. They are explicitly not supported on:

1. Docker Desktop `grpcfuse`
2. `osxfs`
3. network shares such as NFS or SMB
4. any mount where SQLite file locking semantics are not reliable

If the runtime detects SQLite URLs pointing at an unsupported mount pattern in deployment configuration, startup should fail loudly.

#### Replay rule

For SQLite, replay writes must remain isolated in the `replay` store and use a single worker writer session. API polling uses read-only sessions against the replay store.

### MySQL policy

MySQL is the scale and concurrency backend.

#### Driver

Use:

1. `SQLAlchemy>=2.x`
2. `PyMySQL`

Reason:

1. pure Python install path
2. predictable container behavior
3. no native build toolchain dependency

#### Engine/session policy

1. use `QueuePool`
2. enable `pool_pre_ping`
3. set `pool_recycle`
4. use `READ COMMITTED` isolation unless a tighter transactional need is proven

#### SQL type standard

1. booleans use SQLAlchemy `Boolean`
2. large structured payloads use `JSON`
3. timestamps use UTC `DateTime`
4. text identifiers remain explicit `String(length)`

MySQL-specific SQL must not leak into repositories unless isolated behind dialect helpers.

## Schema Standard

### Baseline

Schema definition moves out of constructors and into SQLAlchemy metadata plus Alembic migrations.

New rules:

1. no `CREATE TABLE IF NOT EXISTS` inside repository constructors
2. no lazy schema creation on first request
3. no table ownership spread across arbitrary service objects
4. startup/bootstrap applies migrations explicitly before the app serves traffic

### Naming conventions

All tables, indexes, unique constraints, and foreign keys must use one naming convention owned by `app/db/schema/base.py` so Alembic diffs stay deterministic.

### Timestamp rule

All persisted timestamps are stored as UTC database timestamp columns, not as free-form text fields. Repository serializers convert them to API strings at the boundary.

### JSON rule

Structured metadata that is still legitimately semi-structured may live in JSON columns. It should not be used as a substitute for first-class relational columns when the field is part of query/filter/order behavior.

### Replay schema

The replay schema remains separate from primary operational tables. The previous replay isolation goal stays valid, but its implementation moves from ad hoc SQLite wrappers to the shared runtime and migration system.

## Repository Standard

Every relational domain gets an explicit repository surface. The runtime only solves engine/session concerns; repository boundaries solve code ownership.

### Required repository rules

1. repository methods accept a session in the constructor or call signature
2. repository methods do not open connections
3. repository methods do not commit
4. repository methods return domain payloads or typed row mappings, not raw DB cursors
5. all query SQL lives in repositories, not in gateways or services

### Domain repository map

| Current module | Replacement repository/module | Store |
| --- | --- | --- |
| `app/quant_sim/db.py` | `stock_universe_repo.py`, `live_sim_repo.py`, `strategy_profile_repo.py`, `replay_repo.py` | `primary`, `replay` |
| `app/database.py` | `analysis_repo.py` | `primary` |
| `app/data/analysis_context/repository.py` | `analysis_repo.py` | `primary` |
| `app/monitor_db.py` | `monitor_repo.py` | `primary` |
| `app/smart_monitor_db.py` | `smart_monitor_repo.py` | `primary` |
| `app/main_force_batch_db.py` | `selector_repo.py` | `primary` |
| `app/longhubang_db.py` | `research_repo.py` | `primary` |
| `app/news_flow_db.py` | `research_repo.py` | `primary` |
| `app/sector_strategy_db.py` | `research_repo.py` | `primary` |
| `app/low_price_bull_monitor.py` | `selector_repo.py` | `primary` |
| `app/profit_growth_monitor.py` | `selector_repo.py` | `primary` |
| `app/portfolio_db.py` | `portfolio_repo.py` | `primary` |
| `app/config_manager.py` | `settings_repo.py` | `primary` |
| `app/config.py` | `settings_repo.py` | `primary` |
| `app/ui_table_cache_db.py` | `ui_cache_repo.py` | `primary` |

`UIApiContext` must stop vending raw DB-wrapper classes and instead vend a shared `DatabaseRuntime`, repository factories, or service objects already wired to repositories.

## Gateway and Worker Standards

### Gateway standard

1. request handling receives `DatabaseRuntime` through context/dependency injection
2. GET paths call read-side services backed by `read_uow`
3. POST paths call command services backed by `write_uow`
4. gateway code does not import backend-specific DB modules directly

### Worker standard

1. each worker process creates its own runtime instance
2. each worker process pins a `worker_uow` for the target store
3. long-running jobs checkpoint within that pinned write context
4. worker exit/failure handling must not create secondary write storms by opening new ad hoc connections

Replay specifically must change from:

1. many short independent replay DB connections per checkpoint

to:

1. one worker-pinned replay session
2. one transaction per checkpoint
3. one final transaction for terminal status

## Bootstrap and Migration Flow

### Startup rule

The application no longer self-initializes schema in arbitrary constructors. Instead:

1. startup calls `app/db/bootstrap.py`
2. bootstrap builds the runtime config
3. bootstrap runs Alembic migrations for `primary`
4. bootstrap runs Alembic migrations for `replay`
5. only after both succeed does the app start serving

### Fresh deployment rule

Because old data is irrelevant, the first migration can define the entire new schema from scratch. Existing environments may simply delete old DB files or old MySQL schemas and bootstrap fresh.

## Testing Standard

The persistence standard is not complete unless both backends are tested.

### Test layers

1. unit tests for repository behavior on SQLite
2. dialect contract tests that run against both SQLite and MySQL
3. migration/bootstrap tests for fresh schema creation
4. API integration tests for read-only GET and explicit write POST paths
5. replay worker concurrency tests

### CI matrix

CI must run:

1. `sqlite` test matrix
2. `mysql` test matrix with a disposable MySQL service container

The same repository test suite should pass on both backends except for tests explicitly marked as backend-specific.

### Acceptance test themes

1. GET replay progress does not write
2. replay checkpoint persistence is one transaction per checkpoint
3. worker process uses one pinned replay write session
4. MySQL and SQLite bootstrap produce equivalent schema behavior
5. no module under `app/` still calls `sqlite3.connect(...)`

## Rollout Plan

This design should be implemented in phases.

### Phase 1: Runtime foundation

1. add `SQLAlchemy`, `Alembic`, and `PyMySQL`
2. introduce runtime config, registry, unit-of-work, and bootstrap modules
3. add backend settings and health reporting

### Phase 2: Fresh schema baseline

1. define primary metadata
2. define replay metadata
3. create initial Alembic revisions
4. wire bootstrap into startup

### Phase 3: Quant and replay first

1. move `quant_sim/db.py` behavior into repositories
2. migrate replay service and replay runner to worker-pinned runtime sessions
3. make replay GET handlers strictly read-only

### Phase 4: Remaining relational modules

1. migrate monitor, smart monitor, portfolio, analysis, settings, and research DB modules
2. remove direct file-path DB construction from `UIApiContext`

### Phase 5: Remove legacy persistence wrappers

1. delete or quarantine the old sqlite-only DB helper modules
2. ban direct `sqlite3.connect(...)` in lint/test checks

## Operational Standards

1. the runtime health payload must report backend, store URLs or redacted DSNs, pool status, and migration revision
2. startup must fail if the configured backend is invalid
3. startup must fail if migrations are not at head
4. SQLite deployment documentation must state that write stores require local disk or Docker named volumes, not Desktop bind mounts through `grpcfuse`

## Acceptance Criteria

This design is complete when all of the following are true:

1. the codebase has one shared DB runtime under `app/db/runtime`
2. schema creation is owned by SQLAlchemy metadata plus Alembic, not by service constructors
3. the app can run against `sqlite` or `mysql` by configuration
4. all relational modules use repositories plus unit-of-work contexts
5. GET endpoints are DB read-only
6. replay workers use a single pinned write session and one transaction per checkpoint
7. `app/` no longer contains direct `sqlite3.connect(...)` calls
8. both SQLite and MySQL pass the repository/integration test matrix

## Final Recommendation

Implement this as a shared runtime plus repository standard, not as a one-off replay fix.

The persistence boundary that matters is:

1. one runtime
2. two named stores
3. explicit session modes
4. explicit transaction ownership
5. explicit schema ownership

If those five rules hold, SQLite remains usable for development and controlled deployments, MySQL becomes the scalable deployment backend, and replay stops being a special-case subsystem with its own unsafe persistence behavior.
