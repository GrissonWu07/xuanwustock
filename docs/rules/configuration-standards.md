# Configuration Standards

These rules are derived from the reference projects:

- Java: `C:\Projects\cmps\smartcmp`
- Python: `C:\Projects\cmps\smartcmp-python`

Use them for application properties, YAML, XML, packaging config, test config, and integration config.

## CFG-001: Configuration Ownership

Configuration files MUST have a clear owner and runtime scope.

- Runtime config belongs under runtime resource folders or deployment config folders.
- Test config belongs under test resources or ignored local test config.
- Packaging config belongs at the package/module root.
- Integration catalog/config files belong with their owning integration or component.
- Do not mix production credentials with sample config.

## CFG-002: File Formats

Use the target project's existing format before introducing a new format.

- Java/Spring runtime config commonly uses `application.properties` or profile-specific `application-<profile>.properties`.
- Java logging config commonly uses `log4j2.xml`.
- Java OpenAPI metadata can use a dedicated properties file.
- Java database migrations use Liquibase YAML under DB changelog folders.
- Python package config uses `setup.py`, `setup.cfg`, `pyproject.toml`, `requirements*.txt`, or `tox.ini` according to the package.
- Cloud component and blueprint config commonly uses YAML.
- JSON is acceptable for static seed data, test fixtures, and catalog metadata.

## CFG-003: Naming

Configuration keys MUST be namespaced and descriptive.

- Spring property keys SHOULD use dotted lowercase names, for example `spring.datasource.hikari.maximum-pool-size`.
- Custom service keys SHOULD start with the product or component namespace.
- Queue, exchange, and channel names MUST be explicit and stable.
- YAML top-level keys MUST describe the domain object, for example `Service`, `ResourceTypes`, `Integration`, or the target project's existing domain term.
- Python environment variables MUST use UPPER_SNAKE_CASE.

## CFG-004: Secrets

Secrets MUST not be stored as plaintext.

- Use encrypted placeholders, secret references, or environment variables.
- If the project uses encrypted values such as `ENC(...)`, new secret config MUST follow that mechanism.
- Sample files MUST use fake values.
- Real integration test credentials MUST be in ignored local files or external secret stores.
- Do not include access keys, private URLs, tokens, passwords, or signed requests in committed test config.

## CFG-005: Database Config

Database configuration MUST follow the baseline implementation rules.

- `design.md` MUST state whether a database is required.
- Development-stage local database behavior uses SQLite when database access is required.
- Implementation/deployment-stage behavior uses MySQL when database access is required.
- Java MySQL config SHOULD use Hikari when the project uses Spring Boot.
- Maximum database connection pool size MUST NOT exceed 100.
- Database type and dialect MUST be explicit.
- Schema changes MUST be represented as migrations.

## CFG-006: Migration Config

Database migrations MUST be traceable and reviewable.

- Use Liquibase YAML for Java projects that already use Liquibase.
- Place migrations under the target project's changelog module/version folder.
- Name migration files with a ticket, story, or change identifier when available.
- Migration changes MUST be idempotent or guarded where possible.
- Destructive schema or data changes MUST include rollback or recovery notes in design and review.
- Generated SQL files MUST be stored under a clear `sql/` folder and referenced by the migration or design.

## CFG-007: OpenAPI Config

API documentation config MUST be explicit.

- Enable or disable API docs with an explicit property.
- Scan only intended API packages.
- Store API title, description, contact, and version in a dedicated config source when the project follows that pattern.
- Do not expose internal-only endpoints unless the design marks them as documented internal APIs.

## CFG-008: Async and Queue Config

Async and messaging configuration MUST be bounded.

- Thread pools MUST define core size, max size when applicable, queue capacity, rejection behavior when needed, and thread name prefix.
- Very large queues require design justification.
- RabbitMQ exchanges, queues, and channels MUST use stable names and clear ownership.
- Long-running API work MUST use async execution rather than blocking request threads.

## CFG-009: Test Config

Test configuration MUST be isolated from production config.

- Test resources belong under `src/test/resources` for Java.
- Python test config belongs under `tests/` or ignored local files.
- Integration tests that require real services MUST be disabled by default or gated by explicit environment variables.
- Test fixtures SHOULD use JSON or YAML files when inputs are non-trivial.
- Test parameters required by the OpenSpec workflow MUST be saved under `openspec/changes/<change-id>/test-params/`.

## CFG-010: Dependency and Tool Config

Tooling config MUST be part of review evidence when it changes.

- Maven compiler, surefire, jacoco, checkstyle, and dependency management changes require design/task references.
- Python tox, flake8, coverage, setup, and requirements changes require design/task references.
- Dependency versions MUST be pinned or centrally managed according to the target project's pattern.
- Build config MUST not depend on network-only behavior unless the project already requires it and the task documents it.
