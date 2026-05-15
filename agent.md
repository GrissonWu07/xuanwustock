# agent.md

This is the lower-case compatibility template for agent runtimes that expect `agent.md`.

For Codex projects, prefer the same content in `AGENTS.md`. Keep this file and `AGENTS.md` logically aligned if your tooling reads both names.

## Project Workflow

This project uses Codex, Superpower-style workflow skills, and OpenSpec.

Always open `openspec/AGENTS.md` when a request mentions planning, proposals, specs, changes, design, tasks, implementation of an OpenSpec change, or `/sp-*` workflow commands.

Read `docs/rules/project-implementation-standards.md` when present. It defines baseline design, task, implementation, and review requirements for code paths, file size, database runtime, OpenAPI, backend layering, API IO, and async work.

Also read these default rule files when the change touches the matching area:

- `docs/rules/java-code-standards.md` for Java/Spring code.
- `docs/rules/python-code-standards.md` for Python code.
- `docs/rules/configuration-standards.md` for config, packaging, database, OpenAPI, async, queues, and migrations.
- `docs/rules/testing-standards.md` for tests, fixtures, coverage, and test parameter files.

Required command flow:

1. `/sp-brainstorm <requirement>`
2. `/sp-spec <change-id>`
3. `/sp-tasks <change-id>`
4. `/sp-impl <change-id>`
5. `/sp-complete <change-id>`

## Skills

Template skills are stored in:

```text
skills/
```

For real use, copy or sync them into the user-level skill directory used by the local agent runtime, such as:

```text
~/.agent/skills/
~/.agents/skills/
$CODEX_HOME/skills/
```

Required skills:

- `sp-brainstorm`
- `sp-spec`
- `sp-tasks`
- `sp-impl`
- `sp-complete`

## Artifact Rules

`/sp-brainstorm` creates only:

- `openspec/changes/<change-id>/brainstorm.md`
- `openspec/changes/<change-id>/context.md`
- `openspec/changes/<change-id>/brainstorm-review.md`

`/sp-spec` creates only:

- `openspec/changes/<change-id>/proposal.md`
- `openspec/changes/<change-id>/specs/<capability>/spec.md`
- `openspec/changes/<change-id>/spec-review.md`

`/sp-tasks` creates only:

- `openspec/changes/<change-id>/design.md`
- `openspec/changes/<change-id>/tasks.md`
- `openspec/changes/<change-id>/tasks-review.md`

`/sp-impl` may change code and must update:

- `openspec/changes/<change-id>/tasks.md`
- `openspec/changes/<change-id>/test-params/`
- `openspec/changes/<change-id>/task-reviews.md`
- `openspec/changes/<change-id>/review.md`

`/sp-complete` must verify completion, generate wiki documentation, and archive:

- `openspec/changes/<change-id>/completion.md`
- `docs/wiki/<feature-or-story-title>.md`
- `openspec/changes/archive/<YYYY-MM-DD>-<change-id>/`

## Source Priority

When sources conflict, use this priority:

1. `AGENTS.md` or `agent.md`
2. Current OpenSpec change files
3. `openspec/project.md`
4. `docs/rules/*.md`
5. `docs/standards/*.md`
6. active `docs/wiki/*.md`
7. existing implementation patterns
8. user prompt

Record conflicts in `context.md`, `design.md`, or `review.md`. Do not guess.

## Implementation Guardrails

- Do not implement directly from brainstorm output.
- Do not skip OpenSpec artifacts for feature work.
- Do not skip phase review artifacts.
- Do not proceed to the next phase with unresolved blocking gaps in the current phase review.
- During design and task planning, require target code paths and keep generated/modified code files <= 1000 lines.
- During design, explicitly decide database need. If database is required, use SQLite for development-stage local behavior and MySQL for implementation/deployment-stage behavior with a connection pool max <= 100.
- Backend APIs must use OpenAPI and separate at least Controller and Service.
- Every API must document IO behavior, and very time-consuming work must be async.
- During implementation, complete one task at a time and run both Alignment Review and Security Review before starting the next task.
- During implementation, require at least 90% changed/affected code coverage.
- Save explicit test parameters independently under `openspec/changes/<change-id>/test-params/`.
- Do not write tests for empty/no-op code or tests limited to class/method initialization.
- Resolve and re-review every finding before proceeding.
- Final completion requires zero unresolved findings.
- Do not archive a change until every task is marked complete and wiki documentation is generated from spec, design, and code with a semantic feature/story filename.
- Do not add behavior outside approved specs.
- Do not create tasks without a related requirement.
- Do not create tasks without applicable rule consideration.
- Do not mark tasks complete before verification.
