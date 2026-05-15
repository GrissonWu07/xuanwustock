# Python Code Standards

These rules are derived from the reference Python project at `C:\Projects\cmps\smartcmp-python`.
Use them for Python services, plugins, external integrations, exporters, and scripts unless a target project has stricter local rules.

Google Python Style is also used as a default reference for common Python formatting, naming, imports, docstrings, and runtime safety:

- Source: `https://google.github.io/styleguide/pyguide.html`
- If Google Python Style conflicts with the target project's formatter, lint, or packaging configuration, the target project's checked-in configuration wins.

## PY-001: Source Layout

Python code MUST follow the package layout used by the target project.

- Runtime packages use lowercase package directories.
- Tests live under `tests/` or package-local test folders.
- External integration packages SHOULD separate transport clients, authentication/session setup, parameter validation, response mapping, parsing, and constants when those concerns are non-trivial.
- Build and packaging files stay at the package root.
- Generated or copied vendor code MUST be isolated from first-party code.

## PY-002: Naming

Python names MUST be readable and consistent.

- Packages and modules use `snake_case`.
- Python filenames use the `.py` extension and MUST NOT contain dashes.
- Functions and methods use `snake_case`.
- Variables use `snake_case`.
- Classes use `PascalCase`.
- Constants use `UPPER_SNAKE_CASE`.
- Client classes SHOULD use a clear subject suffix such as `Client`, `ApiClient`, or the target project's existing convention.
- Collector classes SHOULD use a clear subject suffix such as `Collector` when the package collects metrics or inventory.
- Parser functions SHOULD include the parsed subject or format in the function name.
- Test files use `test_*.py`.
- Test classes use `Test<Subject>`.
- Test methods use `test_<behavior>`.

## PY-003: Imports and Formatting

Python code MUST be compatible with the target package's lint settings.

- Prefer standard library imports, third-party imports, then local imports.
- Prefer importing packages and modules instead of individual classes or functions, unless the target project has an established different pattern.
- New code SHOULD use absolute imports with full package paths instead of relying on the script directory being on `sys.path`.
- Avoid wildcard imports in new code.
- Remove unused imports.
- Keep files UTF-8 encoded.
- Use 4 spaces for indentation.
- Do not use tabs.
- Do not use semicolons to put multiple statements on one line.
- Keep line length within the target formatter limit. If no project limit exists, use Google's 80-column default for Python.
- Do not leave trailing whitespace.
- Keep public functions focused and avoid oversized modules.
- New Python code SHOULD include type hints for public functions and complex data structures.
- Use docstrings for public classes, public functions, complex parsers, and non-obvious integration behavior.
- Module docstrings SHOULD summarize purpose and usage when the module exposes reusable behavior.

## PY-004: Packaging

Python packages MUST declare runtime requirements explicitly.

- Use `setup.py`, `setup.cfg`, `pyproject.toml`, or the target project's existing packaging style.
- Pin dependency versions when the project already pins dependencies.
- Keep runtime dependencies separate from test/dev dependencies.
- Console entry points MUST be declared through package metadata.
- Cython or obfuscation build steps MUST be optional or guarded when the dependency is optional.
- Do not add packaging side effects that require network or production credentials at install time.

## PY-005: Async and External IO

External IO MUST be explicit and bounded.

- Async HTTP clients SHOULD use `aiohttp` or the project's existing async client.
- `aiohttp.ClientSession` MUST be closed with `async with` or an explicit `close`.
- TCP connector limits SHOULD be bounded.
- HTTP calls MUST use timeouts.
- Very time-consuming operations MUST be async or run through a bounded executor.
- Do not call `asyncio.run` from inside an already running event loop.
- Synchronous SDK calls inside async flows MUST run through a bounded executor.

## PY-006: External Integration Client Pattern

External service integrations SHOULD separate connection/session setup, client operations, parameter conversion, response conversion, and parser logic when those concerns are non-trivial.

- `connection.py` handles low-level authentication and HTTP/session behavior.
- `client.py` exposes external operations and maps high-level calls to external endpoints.
- `params.py` validates or converts request parameters.
- `response.py` converts external responses to project-standard responses.
- `constants.py` holds integration-specific constants.
- Parser functions convert raw external data into stable internal metrics or response objects.
- If a target project has a domain-specific plugin layout, use that local layout instead of inventing a cross-project folder structure.

## PY-007: Error Handling and Logging

Python code MUST not hide important failures.

- Use module-level loggers.
- Log integration name, operation, endpoint or safe resource identifier, and exception message.
- Do not log secrets, decrypted passwords, tokens, access keys, or signed URLs.
- Return empty collections only when the calling contract treats missing external data as non-fatal.
- Raise or map exceptions when the caller must distinguish failure from empty data.
- Use explicit fallback values for missing metrics or labels.

## PY-008: Security and Secrets

Secrets MUST not be committed in Python config or tests.

- Do not commit real access keys, secret keys, passwords, tokens, or private endpoints.
- Use `.example`, `.template`, environment variables, or local ignored files for sample config.
- If a test needs credentials, gate it behind an explicit environment variable or skip flag.
- Decryption helpers MUST be covered by tests using fake keys or fake ciphertext only.
- HTTP clients MUST not disable TLS verification unless the design documents why and the code scopes it to a known private integration.

## PY-009: Metrics and Exporter Rules

Exporter code MUST produce stable metric names and labels.

- Metric names use lowercase snake_case.
- Integration-specific metric names SHOULD use a stable namespace prefix.
- Parser functions MUST handle missing labels, empty external data, and `None` metric values.
- Metric values MUST be numeric before exporting.
- Collector success/failure metrics SHOULD be emitted when collection can fail per integration or resource.
- Labels MUST be stable and must not include secrets or high-cardinality transient values unless explicitly designed.

## PY-010: Script Rules

Operational scripts MUST be safe and repeatable.

- Use `argparse`, `click`, or the target project's CLI pattern for parameters.
- Do not hardcode production paths, credentials, or network endpoints.
- Log actions before destructive operations.
- Support dry-run behavior for destructive or bulk operations when feasible.
- Keep build and packaging scripts separate from runtime business logic.

## PY-011: Google Python Practices

Python code SHOULD follow these common Google Python practices unless the target project has a stricter rule.

- Names MUST be descriptive and avoid unfamiliar abbreviations.
- Avoid single-character names except for short counters, iterators, exception aliases, file handles, and established mathematical notation.
- Prefer a single leading underscore for internal module members and protected class members.
- Avoid double-leading-and-trailing names except Python-defined special methods.
- Avoid mutable default argument values such as `[]` or `{}`; use `None` and initialize inside the function, or use an immutable default.
- Do not use `assert` for runtime validation or business preconditions; raise an explicit exception.
- Use built-in exception classes when they clearly fit, such as `ValueError` for invalid arguments.
- Use context managers for files, sockets, clients, and other stateful resources when available.
- Keep top-level executable behavior behind `main()` and `if __name__ == '__main__':`.
- Document side effects, raised exceptions, and non-obvious arguments in docstrings for public functions.
