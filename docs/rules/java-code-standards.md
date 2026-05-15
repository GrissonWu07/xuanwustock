# Java Code Standards

These rules are derived from the reference Java project at `C:\Projects\cmps\smartcmp`.
Use them for Java and Spring Boot code unless a target project has stricter local rules.

Google Java Style is also used as a default reference for common Java formatting, naming, and programming practices:

- Source: `https://google.github.io/styleguide/javaguide.html`
- If Google Java Style conflicts with the target project's Checkstyle, formatter, or build configuration, the target project's checked-in configuration wins.

## JAVA-001: Source Layout

Java code MUST follow the Maven module layout used by the target project.

- Main code goes under `src/main/java`.
- Test code goes under `src/test/java`.
- Runtime resources go under `src/main/resources`.
- Test resources go under `src/test/resources`.
- Multi-module projects MUST keep module-specific code inside the owning module.
- Package names MUST match directory paths.

## JAVA-002: Package and Type Names

Package names MUST be lowercase dot-separated names.

- Packages MUST match `^[a-z]+(\.[a-z][a-z0-9]*)*$`.
- Classes, interfaces, and enums MUST use PascalCase.
- Methods and fields MUST use lowerCamelCase.
- Constants MUST use UPPER_SNAKE_CASE.
- One public top-level type MUST match the file name.

Common suffixes:

- REST/controller boundary: `*Controller` or project-approved REST interface.
- Service contract: `*Service`.
- Service implementation: `*ServiceImpl`.
- Persistence repository: `*Repository`.
- Configuration: `*Config` or `*Configuration`.
- Request DTO: `*Request`, `*Req`, or existing project suffix.
- Response DTO: `*Response`, `*Resp`, or existing project suffix.
- Value object: `*VO`.
- Data transfer object: `*DTO`.
- Enum: `*Type`, `*State`, `*Status`, or `*Enum`.

## JAVA-003: Formatting and Imports

Java code MUST follow the reference Checkstyle rules.

- Use UTF-8.
- Use 4 spaces for indentation.
- Use the target project's formatter indentation. Google Java Style uses 2-space block indentation; the reference project Checkstyle uses 4 spaces, so project Checkstyle wins for this template.
- Do not use tabs.
- Do not leave trailing whitespace.
- Do not use star imports.
- Do not use module imports in normal Java source.
- Remove unused imports.
- Keep import groups ordered and separated.
- Keep static imports and non-static imports in separate groups.
- Sort imports consistently according to the target formatter.
- Use braces for control flow, even for single-line branches.
- Use K&R brace placement for non-empty blocks unless the target formatter requires otherwise.
- Use one statement per line.
- Keep Java lines at or below 100 columns unless the target project config has a different limit or the line is an unavoidable exception such as a long URL or import.
- Avoid multiple variable declarations in one statement.
- Use Java array type style consistently, for example `String[] args`.
- Use uppercase `L` for long literals.
- Include a default branch for switch statements unless the switch is exhaustive and documented.

## JAVA-004: Spring Layering

New backend API work MUST separate transport and business behavior.

- Controllers handle HTTP transport, request parsing, response mapping, status codes, and OpenAPI annotations.
- Services handle business behavior, transactions, orchestration, validation, and ACL/business rules.
- Repositories handle persistence only.
- Configuration classes contain `@Configuration` and `@Bean` definitions only.
- Do not put business logic into controllers.
- Do not put HTTP request/response objects into persistence repositories.
- Do not call repositories directly from controllers unless the design explicitly approves a read-only shortcut.

The reference project sometimes exposes REST annotations on service interfaces. New projects SHOULD prefer explicit Controller classes when creating new APIs, because the baseline workflow requires Controller and Service separation.

## JAVA-005: OpenAPI API Design

Backend APIs MUST be documented through OpenAPI.

- Use springdoc/OpenAPI conventions already present in the project.
- Use `@Tag` on API boundary types.
- Use `@Operation` on API methods.
- Use `@Parameter` for important query/path parameters.
- Keep OpenAPI package scanning explicit so generated schema output does not accidentally scan large entity graphs.
- Every new or changed API MUST have a corresponding OpenAPI path/operation in design and review evidence.

## JAVA-006: Request and Validation Rules

API methods MUST make input expectations explicit.

- Mark required request parameters explicitly.
- Use request DTOs when the payload has multiple fields or nested structure.
- Validate blank strings, missing IDs, invalid enum values, duplicated names, and illegal state transitions before changing data.
- Prefer project exception types for business errors.
- Do not expose raw stack traces, credentials, tokens, or internal connection details in API responses.

## JAVA-007: Persistence Rules

Database-backed entities MUST use the project's persistence conventions.

- JPA entities use `@Entity`.
- Table names SHOULD be explicit with `@Table(name = "...")` and SHOULD use snake_case.
- Repository interfaces SHOULD extend the project's base repository type when one exists.
- Tenant-aware data MUST use the target project's tenant-aware annotation or base class.
- Database schema changes MUST be represented as migrations, not only entity changes.
- Migration files SHOULD live under the project's DB changelog folder, for example `src/main/resources/db/changelog/module/<version>/`.
- Migration file names SHOULD include the story or ticket identifier when available.

## JAVA-008: Configuration Classes

Java configuration MUST be explicit and bounded.

- Put Spring configuration in `config` packages.
- Use `@Configuration` for configuration classes.
- Use `@ConditionalOnProperty` for optional features.
- Use `@Value` or typed configuration properties for externalized values.
- Thread pools MUST use named prefixes and bounded pool sizes.
- Very time-consuming operations MUST use an approved async executor instead of blocking request threads.

## JAVA-009: Dependency Management

Maven dependencies MUST be managed at the appropriate parent or module level.

- Centralize dependency versions in parent properties or dependency management when the project has a parent POM.
- Do not introduce a dependency only for small utility behavior that the JDK or existing libraries already cover.
- Exclusions MUST be documented when used to avoid logging, security, classpath, or version conflicts.
- New dependencies MUST be referenced by design and tasks before implementation.

## JAVA-010: Logging and Errors

Java code MUST use the project's logging framework.

- Use class-level loggers or Lombok `@Slf4j` when the project uses Lombok.
- Log enough context to diagnose failures, but do not log secrets.
- Do not swallow exceptions silently.
- For external API failures, log provider, operation, status/error code, and safe request identifiers.
- Use business exceptions for expected domain failures and technical exceptions for infrastructure failures.

## JAVA-011: Google Java Practices

Java code SHOULD follow these common Google Java practices unless the target project has a stricter rule.

- A source file contains one public top-level type whose name matches the file name.
- File sections appear in this order: license/copyright if present, package declaration, imports, top-level type.
- Separate present file sections with exactly one blank line.
- Group overloads contiguously; do not split overloaded methods or constructors with unrelated members.
- Use UpperCamelCase for classes, interfaces, enums, records, and annotations.
- Use lowerCamelCase for methods, fields, parameters, and local variables.
- Use UPPER_SNAKE_CASE only for deeply immutable constants.
- Do not use special member prefixes or suffixes such as `mName`, `s_name`, `name_`, or `kName`.
- Add `@Override` whenever it is legal, except where a target project explicitly documents an exception.
- Do not ignore caught exceptions. Log, rethrow, map to a domain exception, or explain the intentionally ignored case in a short comment.
- Qualify static members with the declaring class name, not an instance expression.
- Do not override or depend on `Object.finalize`.
