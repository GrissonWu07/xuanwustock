# AGENTS.md

This project uses Codex, Superpower-style workflow skills, and OpenSpec.

Superpower-style skills are the workflow layer. OpenSpec is the source of truth for approved change artifacts. Project rules, standards, and wiki snapshots are context inputs for spec, design, implementation, and review.

Always open `openspec/AGENTS.md` when a request mentions planning, proposals, specs, changes, design, tasks, implementation of an OpenSpec change, or `/sp-*` workflow commands.

The default baseline project implementation rules live in `docs/rules/project-implementation-standards.md` when present. This template also includes default Java, Python, configuration, and testing rule files derived from reference projects:

- `docs/rules/java-code-standards.md`
- `docs/rules/python-code-standards.md`
- `docs/rules/configuration-standards.md`
- `docs/rules/testing-standards.md`

Additional project-specific rule files may be added under `docs/rules/`.

## Required Workflow

Use this workflow for feature work and behavior changes:

1. `/sp-brainstorm <requirement>`
2. `/sp-spec <change-id>`
3. `/sp-tasks <change-id>`
4. `/sp-impl <change-id>`
5. `/sp-complete <change-id>`

Commands may generate multiple artifacts, but artifact responsibilities must remain separate.

## Skill Location

This template stores skills in:

```text
skills/
```

For real project use, copy or sync these skills into the user-level skill directory used by Codex, such as:

```text
~/.agent/skills/
~/.agents/skills/
$CODEX_HOME/skills/
```

## /sp-brainstorm

Use `sp-brainstorm`.

Create or update:

- `openspec/changes/<change-id>/brainstorm.md`
- `openspec/changes/<change-id>/context.md`
- `openspec/changes/<change-id>/brainstorm-review.md`

Rules:

- Read `docs/ai-context/source-index.md` first when it exists.
- Read relevant project-defined rules under `docs/rules/*.md`, standards, wiki snapshots, existing specs, and similar code.
- Read the default language, configuration, and testing rules when they match the requested technology or artifact type.
- Do not write code.
- Do not create proposal, specs, design, or tasks.
- Record conflicts and context gaps instead of guessing.
- Review brainstorm/context alignment before `/sp-spec`.
- Do not proceed to `/sp-spec` with unresolved blocking gaps in `brainstorm-review.md`.

## /sp-spec

Use `sp-spec`.

Create or update:

- `openspec/changes/<change-id>/proposal.md`
- `openspec/changes/<change-id>/specs/<capability>/spec.md`
- `openspec/changes/<change-id>/spec-review.md`

Rules:

- Base output on `brainstorm.md`, `context.md`, `openspec/project.md`, and relevant existing specs.
- Read relevant project-defined rules under `docs/rules/*.md` and encode behavior-affecting rules as observable requirements or scenarios.
- Read the default language, configuration, and testing rules when they affect observable behavior, validation, security, or delivery constraints.
- Specs must describe observable behavior only.
- Use OpenSpec Requirement and Scenario format.
- Do not create design or tasks.
- Do not write code.
- Review proposal/spec alignment before `/sp-tasks`.
- Do not proceed to `/sp-tasks` with unresolved blocking gaps in `spec-review.md`.

## /sp-tasks

Use `sp-tasks`.

Create or update:

- `openspec/changes/<change-id>/design.md`
- `openspec/changes/<change-id>/tasks.md`
- `openspec/changes/<change-id>/tasks-review.md`

Rules:

- Read `context.md`, `proposal.md`, `specs/`, relevant project-defined rules under `docs/rules/*.md`, relevant docs, and similar implementation before writing design.
- Apply the default Java, Python, configuration, and testing rules when the change touches those areas.
- Include Source Mapping in `design.md`.
- Include Rules Compliance in `design.md`.
- Include Spec Gaps when behavior is needed but not covered by specs.
- `design.md` must recommend generated/modified code paths by feature point.
- `design.md` and `tasks.md` must keep generated/modified code files <= 1000 lines or split them before implementation.
- `design.md` must explicitly decide whether a database is required. If required, use SQLite for development-stage local behavior, MySQL for implementation/deployment-stage behavior, and a connection pool with maximum size <= 100.
- Backend API design must use OpenAPI and separate at least Controller and Service.
- Every API must document IO behavior; very time-consuming work must be async.
- Every task must reference a requirement, applicable rules, target code paths, implementation-standard impact, and validation.
- Every task must specify independent test parameter files under `openspec/changes/<change-id>/test-params/`.
- Every task must require at least 90% coverage for changed/affected code.
- Every task must include two implementation review gates: Alignment Review and Security Review.
- `tasks-review.md` must confirm each task has those gates and finding closure requirements.
- Do not write code.
- Review design/task alignment before `/sp-impl`.
- Do not proceed to `/sp-impl` with unresolved blocking gaps in `tasks-review.md`.

## /sp-impl

Use `sp-impl`.

Before implementation, read:

- `AGENTS.md`
- `openspec/changes/<change-id>/proposal.md`
- `openspec/changes/<change-id>/specs/`
- `openspec/changes/<change-id>/design.md`
- `openspec/changes/<change-id>/tasks.md`
- `openspec/changes/<change-id>/spec-review.md`
- `openspec/changes/<change-id>/tasks-review.md`
- `openspec/changes/<change-id>/task-reviews.md`
- `openspec/changes/<change-id>/test-params/`
- relevant `docs/rules/*.md`

Rules:

- Implement only unchecked tasks in `tasks.md`.
- Stop before coding if prior phase reviews contain unresolved blocking gaps.
- Load applicable Java, Python, configuration, and testing rules before editing code, config, or tests.
- Complete tasks one at a time.
- Create or update explicit test parameter files under `openspec/changes/<change-id>/test-params/`.
- Tests must use explicit parameters and assert meaningful behavior from specs/design.
- Changed/affected code must reach at least 90% coverage.
- Generated/modified code files must stay <= 1000 lines.
- Database, OpenAPI, Controller/Service, API IO, and async rules must be implemented and evidenced when relevant.
- Do not write tests for empty/no-op code.
- Do not count tests that only verify class or method initialization.
- After each task, run Alignment Review against spec, design, task, rules, and changed code.
- After each task, run Security Review against security-sensitive behavior and project-defined security rules.
- Fix every finding from both reviews and re-review before starting the next task.
- Record all per-task review rounds and closure evidence in `task-reviews.md`.
- Do not add behavior outside specs.
- Do not modify unrelated files.
- Do not introduce new dependencies unless required by `design.md`.
- Reuse existing code patterns.
- Follow applicable project-defined rules.
- Update `tasks.md` after completing and verifying tasks.
- Run relevant tests and coverage checks.
- Create or update `review.md`, including Rules Compliance.
- Final completion requires `task-reviews.md` and `review.md` to show zero unresolved findings.

Final response must include:

- Completed tasks
- Files changed
- Tests run
- Review result
- Any deviation from OpenSpec
- Remaining issues

## /sp-complete

Use `sp-complete`.

Before completion, read:

- `AGENTS.md`
- `openspec/changes/<change-id>/proposal.md`
- `openspec/changes/<change-id>/specs/`
- `openspec/changes/<change-id>/design.md`
- `openspec/changes/<change-id>/tasks.md`
- `openspec/changes/<change-id>/task-reviews.md`
- `openspec/changes/<change-id>/review.md`
- relevant `docs/rules/*.md`
- relevant implementation files referenced by the change artifacts

Rules:

- Do not complete if any task in `tasks.md` is unchecked.
- Confirm applicable Java, Python, configuration, and testing rules were considered in review evidence.
- Do not complete if `task-reviews.md` has any open Alignment Review or Security Review finding.
- Do not complete if `review.md` has unresolved findings.
- Do not complete if coverage evidence is below 90% for changed/affected code.
- Do not complete if required test parameter files are missing.
- Generate or update a semantic `docs/wiki/<feature-or-story-title>.md` file from specs, design, code, rules, and review evidence.
- Derive the wiki title and filename from the completed feature/story, not from the raw change ID.
- Create `completion.md` with completion gate results and archive target.
- Review the generated wiki against specs, design, and implemented code before archiving.
- Archive the change by moving `openspec/changes/<change-id>/` to `openspec/changes/archive/<YYYY-MM-DD>-<change-id>/`.
- Do not overwrite an existing archive folder.

Final response must include:

- Archived change path
- Wiki page path
- Completion gates result
- Review/finding status
- Any skipped or blocked item

## Source Priority

When sources conflict, use this priority:

1. `AGENTS.md`
2. Current OpenSpec change files
3. `openspec/project.md`
4. `docs/rules/*.md`
5. `docs/standards/*.md`
6. active `docs/wiki/*.md`
7. existing implementation patterns
8. user prompt

If there is a conflict, report it in `context.md`, `design.md`, or `review.md`. Do not guess.
