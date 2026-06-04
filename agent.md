# agent.md

This is the lower-case compatibility template for agent runtimes that expect `agent.md`.

For Codex projects, prefer the same content in `AGENTS.md`. Keep this file and `AGENTS.md` logically aligned if your tooling reads both names.

## Project Workflow

This project uses Codex, Superpower-style workflow skills, and OpenSpec.

Always open `openspec/AGENTS.md` when a request mentions planning, proposals, specs, changes, design, tasks, implementation of an OpenSpec change, or `/sp-*` workflow commands.

Keep durable OpenSpec contracts limited to `proposal.md`, `design.md`, `tasks.md`, and `specs/<capability>/spec.md` under `openspec/changes/<change-id>/`. Write brainstorm, context, mockups, review logs, test-parameter records, and completion evidence to `.agent/workdir/sp-openspec/<change-id>/`.

Read `docs/rules/project-implementation-standards.md` when present. It defines baseline design, task, implementation, and review requirements for code paths, requirement scope, fallback control, parameter data objects, standalone verification, logic reuse, code comments, logging, encoding/no-mojibake, file size, database runtime, OpenAPI, backend layering, API IO, and async work.

Also read these default rule files when the change touches the matching area:

- `docs/rules/ai-workflow-quality-standards.md` for product challenge, planning review lenses, browser QA, security threat review, and project learning notes.
- `docs/rules/logging-standards.md` for unified log format, `trace_id`, log levels, safe parameters, exception stack traces, sensitive-data masking, async logging, structured logs, and monitoring support.
- `docs/rules/encoding-standards.md` for UTF-8, parser-compatible config encoding, readable comments/code/config, and no mojibake.
- `docs/rules/java-code-standards.md` for Java/Spring code.
- `docs/rules/python-code-standards.md` for Python code.
- `docs/rules/configuration-standards.md` for config, packaging, database, OpenAPI, async, queues, and migrations.
- `docs/rules/testing-standards.md` for tests, fixtures, coverage, and test parameter files.

Required command flow:

Generated workflow documents default to Chinese. Use English only when the user explicitly asks for English, and record that request in the relevant artifact.

Automatic goal mode:

1. `/sp-goal <requirement-or-change-id>`

Manual phase mode:

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

- `sp-goal`
- `sp-brainstorm`
- `sp-spec`
- `sp-tasks`
- `sp-impl`
- `sp-complete`

## Artifact Rules

`/sp-goal` detects the earliest incomplete phase for an active or requested change and runs all remaining workflow phases through `/sp-complete`. It must not skip phase reviews, task reviews, tests, coverage, finding closure, wiki generation, archive gates, or required independent review threads.

If `/sp-goal` finds an existing `brainstorm-review.md` without customer/user confirmation of the reviewed final brainstorm output, treat brainstorm as incomplete. Re-enter the brainstorm workflow: draft or recover the content in the conversation, complete main-process review, independent read-only review, cross-validation, and required draft revisions, then confirm the reviewed final draft with the customer/user before updating `brainstorm.md`, `context.md`, and `brainstorm-review.md`.

During `/sp-brainstorm` or `/sp-goal` brainstorm recovery, draft the proposed `brainstorm.md` and `context.md` content in the conversation first. Review the draft with the main process and one independent read-only thread, cross-validate findings, revise and re-review until no unresolved blocking finding remains, then ask the customer/user to confirm the reviewed final draft. Do not create or update `brainstorm.md`, `context.md`, or `brainstorm-review.md` until that confirmation exists.

If `/sp-goal` finds an existing `design.md` without customer/user confirmation for backend logic, UI mockup/function description, API paths/parameters, configuration parameter names/values, or E2E required/not-required decision, treat spec/design as incomplete. Re-enter `/sp-spec` to review the pending design confirmation package first, then confirm it with the customer/user and update `design.md` plus `design-review.md` before task creation.

If `/sp-goal` finds missing or blocked `design-review.md`, treat spec/design as incomplete and return to `/sp-spec`.

`/sp-brainstorm` creates only:

- `.agent/workdir/sp-openspec/<change-id>/brainstorm.md`
- `.agent/workdir/sp-openspec/<change-id>/context.md`
- `.agent/workdir/sp-openspec/<change-id>/brainstorm-review.md`

Before `/sp-spec`, `brainstorm-review.md` must record main-process comprehensive review, one independent brainstorm/context review thread, cross-validation/finding confirmation, main-thread responses and fixes, customer/user confirmation, and zero unresolved blocking findings.

`/sp-spec` creates only:

- `openspec/changes/<change-id>/proposal.md`
- `openspec/changes/<change-id>/specs/<capability>/spec.md`
- `.agent/workdir/sp-openspec/<change-id>/spec-review.md`
- `openspec/changes/<change-id>/design.md`
- `.agent/workdir/sp-openspec/<change-id>/design-review.md`
- `.agent/workdir/sp-openspec/<change-id>/mockups/` when UI changes require mockups

Before `/sp-tasks`, `spec-review.md` and/or `design-review.md` must record main-process comprehensive review, one independent spec/design review thread, cross-validation/finding confirmation, main-thread responses and fixes, required customer/user confirmations collected after reviewed design draft closure, and zero unresolved blocking findings.

`/sp-tasks` creates only:

- `openspec/changes/<change-id>/tasks.md`
- `.agent/workdir/sp-openspec/<change-id>/tasks-review.md`

Before `/sp-impl`, `tasks-review.md` must record main-process comprehensive task review, one independent read-only task review thread, cross-validation/finding confirmation, main-thread responses and fixes, and zero unresolved blocking findings.

`/sp-impl` may change code and must update:

- `openspec/changes/<change-id>/tasks.md`
- `.agent/workdir/sp-openspec/<change-id>/test-params/`
- `.agent/workdir/sp-openspec/<change-id>/task-reviews.md`
- `.agent/workdir/sp-openspec/<change-id>/review.md`

Before `/sp-complete`, `review.md` must record one main-thread full implementation review, two independent final review threads, and cross-validation/finding confirmation across all review sources. Independent Review Thread 1 checks requirement/spec/design/code alignment and adversarial evidence. Independent Review Thread 2 checks security, implementation standards, regressions, logging, data/API/async/config, test quality, and file-size gates.

`/sp-complete` must verify completion, generate wiki documentation, and archive:

- `.agent/workdir/sp-openspec/<change-id>/completion.md`
- `docs/wiki/<feature-or-story-title>.md`
- `openspec/changes/archive/<YYYY-MM-DD>-<change-id>/`
- local git commit

## Source Priority

When sources conflict, use this priority:

1. `AGENTS.md` or `agent.md`
2. Current OpenSpec change files and `.agent/workdir/sp-openspec/<change-id>/` evidence
3. `openspec/project.md`
4. `docs/rules/*.md`
5. `docs/standards/*.md`
6. active `docs/wiki/*.md`
7. existing implementation patterns
8. user prompt

Record conflicts in `context.md`, `design.md`, or `review.md`. Do not guess.

## Implementation Guardrails

- Do not implement directly from brainstorm output.
- During brainstorm, challenge product scope before spec: real user, pain, outcome, smallest useful slice, rejected scope, alternatives, and open questions.
- During brainstorm, review and cross-validate the drafted brainstorm/context content before presenting the reviewed final draft to the customer/user for confirmation; wait for confirmation before writing it to files.
- Do not skip OpenSpec artifacts for feature work.
- Do not skip phase review artifacts.
- Do not skip required independent review threads. `/sp-brainstorm`, `/sp-spec`, and `/sp-tasks` each require one independent review thread; `/sp-impl` requires one main-thread full review and two independent final review threads.
- Do not skip main-process comprehensive review or cross-validation between main-process findings and read-only independent-thread findings.
- Do not proceed to the next phase with unresolved blocking gaps in the current phase review.
- During `/sp-spec` design and `/sp-tasks` planning, require target code paths and keep generated/modified code files <= 1000 lines.
- During `/sp-spec` design and `/sp-tasks` planning, identify same or equivalent existing logic and require reuse, shared abstraction extraction/extension, or documented isolation justification.
- During `/sp-spec` design and `/sp-tasks` planning, apply product, design, engineering, developer-experience, security, and QA review lenses when relevant.
- During `/sp-spec` design and `/sp-tasks` planning, declare the browser/API/job QA plan before implementation.
- During design and implementation, existing-code changes must implement only approved requirements. Do not add fallback, compatibility, degraded-mode, dual-path, or silent default behavior unless specs/design/tasks explicitly require it.
- During design and implementation, methods/functions must have no more than 5 input parameters, or use explicit named data objects instead of vague maps/dicts/objects/key-value bags.
- During design and implementation, define and implement useful comments for non-obvious behavior plus behavior logs with `trace_id`, safe structured fields, correct log levels, exception stack traces, and sensitive-data exclusion.
- During design and implementation, prevent mojibake in generated or modified comments, code, configuration, test data, and workflow artifacts.
- During spec, design, task, and implementation work, require standalone full verification from the relevant entry point.
- During spec, design, task, and implementation work, tests must focus on project-owned code and behavior. Do not test dependency packages, framework behavior, SDK internals, or third-party API/provider correctness as the primary subject.
- Before `/sp-spec`, require customer/user confirmation of the reviewed final brainstorm output recorded in `brainstorm-review.md`.
- Before `/sp-spec`, require evidence that `brainstorm.md` and `context.md` were created from customer/user-confirmed draft content.
- Before `/sp-spec`, require main-process comprehensive review, independent brainstorm/context review thread evidence, cross-validation/finding confirmation, main-thread responses and fixes, and zero unresolved findings in `brainstorm-review.md`.
- During `/sp-spec`, generate `design.md` and `design-review.md` after proposal/spec/spec-review; do not leave design for `/sp-tasks`.
- During `/sp-spec`, after proposal/spec/design/design-review drafts are present and before design customer/user confirmation, start one independent spec/design review thread, cross-validate it with main-process findings, revise and re-review affected artifacts, then confirm the reviewed design confirmation package with the customer/user and record findings, confirmation decisions, main-thread responses, fixes, and closure in `spec-review.md` and/or `design-review.md`.
- During `/sp-tasks`, do not create or modify `design.md` or `design-review.md`; return to `/sp-spec` if design decisions or confirmations are missing.
- During design, prepare backend logic decisions, UI mockup/function description, API paths/parameters, configuration names/values, and E2E required/not-required decisions as a pending confirmation package; review and cross-validate the draft before asking the customer/user to confirm it.
- During `/sp-tasks`, run main-process task review and one independent read-only task review thread; cross-validate findings and close all confirmed findings in `tasks-review.md` before `/sp-impl`.
- If E2E is confirmed as required, require runtime target, command/tool, test data, assertions, and evidence in design and tasks.
- For third-party integrations, require mocks, stubs, contract fixtures, local fakes, or explicitly approved sandbox/test endpoints, with assertions focused on project-owned request construction, response mapping, error handling, persistence, and user/API/UI-visible results.
- During implementation, user-confirmed required real E2E tests must run against the designed runtime target. Unit tests, mock-only tests, class initialization tests, isolated method tests, and static screenshots do not count as E2E.
- Backend service work must verify real API request/response behavior; UI work must include UI tests; bug fixes must verify through the bug entry point; external service changes must verify project-provided database/Redis/Elasticsearch/queue/cache/integration connections when available.
- UI work must use real browser QA or the project-approved UI runner when a runnable target exists.
- During design, explicitly decide database need. If database is required, use SQLite for development-stage local behavior and MySQL for implementation/deployment-stage behavior with a connection pool max <= 100.
- Backend APIs must use OpenAPI and separate at least Controller and Service.
- Every API must document IO behavior, and very time-consuming work must be async.
- During implementation, complete one task at a time and run both Alignment Review and Security Review before starting the next task.
- During implementation, do not mark a task complete without standalone verification evidence or an allowed external-service skip reason.
- During implementation, do not mark a task complete without user-confirmed required real E2E evidence or a documented environment blocker and fallback evidence.
- During implementation, do not introduce avoidable duplicate same/equivalent logic.
- During implementation, do not introduce unrequested fallback/compatibility behavior.
- During implementation, require at least 85% changed/affected code coverage.
- Coverage percentage must not substitute requirement coverage, scenario coverage, or requirement-to-test mapping.
- During implementation, build and record a Requirement Counterexample Matrix before marking each task complete.
- Alignment Review must actively try to disprove broad requirements with non-default and adversarial variants.
- Masked tests do not prove later decision semantics; review evidence must explain why each proving test is not masked by an earlier gate, filter, sort, or transform.
- During implementation, record Decision Chain Trace for gate, filter, admission, eligibility, validation, sort, score, rank, selection, state transition, workflow transition, or decision-chain behavior.
- During implementation, record Evidence Capture Timing Audit for fields whose semantics represent order/rank/position, snapshot, readiness/eligibility, confidence, score, timestamp, provenance/source/lineage, status/state/stage, audit trail, or decision reason.
- During implementation, record Deterministic Sort Audit for sorting, ranking, ordering, priority, first/last selection, top-N selection, pagination order, or display order.
- Review must explicitly answer whether an earlier gate, filter, sort, or transform can let a test pass without proving the target semantic behavior.
- Checklist presence is not evidence; audits must map to actual code paths, inputs, outputs, transforms, evidence fields, tests, and closure.
- If code uses a narrower qualifier than the spec, record a finding unless specs/design/tasks explicitly approve the exception.
- Save explicit test parameters independently under `.agent/workdir/sp-openspec/<change-id>/test-params/`.
- Do not write tests for empty/no-op code or tests limited to class/method initialization.
- Resolve and re-review every finding before proceeding.
- After all implementation tasks are complete, run one main-thread full implementation review across requirements, specs, design, tasks, code, tests, verification, and rules.
- After the main-thread implementation review, start two independent final review threads: Thread 1 for requirement/spec/design/code alignment and adversarial evidence, and Thread 2 for security, implementation standards, regressions, logging, data/API/async/config, test quality, and file-size gates.
- Cross-validate main-thread full review findings and both independent-thread findings before confirming issues, fixing, or closing implementation review.
- Independent review threads must not edit files. Findings return to the main thread; the main thread cross-validates against its own findings, confirms issue status, fixes, replies, verifies, and re-runs the relevant review until zero unresolved findings remain.
- Security review must check concrete authentication, authorization, validation, data exposure, logging, dependency, configuration, API IO, async, and external-service risks when relevant.
- Review must reject logs without required `trace_id` context, logs missing exception stack traces, unclear log levels, noisy or unstructured behavior logs, and logs that expose sensitive information.
- Review must reject garbled comments, code strings, configuration values, test parameters, non-ASCII text, broken escaping, and parser-incompatible encoding.
- Final completion requires zero unresolved findings.
- Final completion requires required main-process review evidence, independent review thread evidence, cross-validation/finding confirmation, main-thread responses, fixes, and closure in `brainstorm-review.md`, `spec-review.md`, `design-review.md`, `tasks-review.md`, and `review.md`.
- Do not start implementation while required customer/user confirmation evidence is missing.
- Do not archive a change until every task is marked complete and wiki documentation is generated from spec, design, design-review, customer/user confirmations, and code with a semantic feature/story filename.
- After the completed change, tests, reviews, workdir completion evidence, wiki, and durable archive are finished, create a local git commit for the completed change.
- Do not commit `.agent/workdir/` process evidence unless the project explicitly requires retaining it.
- The commit message must include the complete requirement, completed changes, solution/design approach, customer/user confirmation evidence, workflow/completion evidence, and frontend/backend completion content when relevant.
- After `/sp-complete`, final response must report what was actually done in user-facing terms: solution, code changes, tests/verification, documentation, review status, and local commit. OpenSpec archive details can be brief supporting evidence.
- After `/sp-complete`, update `docs/ai-context/project-learnings.md` when reusable patterns, pitfalls, preferences, or verification notes were discovered; otherwise record that no reusable learning was found.
- Do not push unless the user explicitly asks.
- Do not add behavior outside approved specs.
- Do not create tasks without a related requirement.
- Do not create tasks without applicable rule consideration.
- Do not mark tasks complete before verification.
