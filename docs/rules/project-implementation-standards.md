# Project Implementation Standards

These baseline rules are mandatory for design, task planning, implementation, and review.
Projects may add more rule files under `docs/rules/`, but they must not weaken these rules unless `AGENTS.md` explicitly overrides them.

## PIR-001: Code Path Planning

Design and task artifacts MUST identify the generated or modified code paths for each feature point and task point.

- `design.md` MUST include recommended code paths grouped by feature area.
- `tasks.md` MUST include target code paths for every implementation task.
- Path suggestions MUST be based on the feature scope, task scope, and existing project structure.

## PIR-002: File Length Limit

Generated or modified code files MUST stay at or below 1000 lines.

- If a planned file would exceed 1000 lines, the design and tasks MUST split it into smaller modules before implementation.
- Implementation review MUST check changed code file lengths.
- A task cannot be marked complete while any generated or modified code file exceeds 1000 lines.

## PIR-003: Database Runtime and Connection Pool

Design MUST explicitly state whether the change requires a database.

- If no database is required, `design.md` MUST say so.
- If a database is required, development-stage local behavior MUST use SQLite.
- If a database is required, implementation/deployment-stage behavior MUST use MySQL.
- Database access MUST configure a connection pool.
- The maximum connection pool size MUST NOT exceed 100.

## PIR-004: Backend API Contract and Layers

Backend APIs MUST be designed from an OpenAPI contract.

- `design.md` MUST identify the OpenAPI operation or schema changes for every backend API.
- Backend implementation MUST separate at least Controller and Service responsibilities.
- Controllers handle transport, request parsing, response mapping, and status codes.
- Services handle business behavior and orchestration.

## PIR-005: API IO and Async Execution

Every API design MUST describe IO behavior.

- `design.md` MUST identify database, file, network, queue, cache, or external service IO for each API.
- If an API operation can be very time-consuming, it MUST be designed and implemented asynchronously.
- Tasks MUST include validation for async behavior when async execution is required.
