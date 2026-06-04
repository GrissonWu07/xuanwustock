# AGENTS.md

This project uses Codex, Superpower-style workflow skills, and OpenSpec.

Superpower-style skills are the workflow layer. OpenSpec is the source of truth for approved change artifacts. Keep durable OpenSpec contracts limited to `proposal.md`, `design.md`, `tasks.md`, and `specs/<capability>/spec.md`; write process evidence to `.agent/workdir/sp-openspec/<change-id>/`. Project rules, standards, and wiki snapshots are context inputs for spec, design, implementation, and review.

Always open `openspec/AGENTS.md` when a request mentions planning, proposals, specs, changes, design, tasks, implementation of an OpenSpec change, or `/sp-*` workflow commands.

The default baseline project implementation rules live in `docs/rules/project-implementation-standards.md` when present. This template also includes default AI workflow quality, logging, encoding, Java, Python, configuration, and testing rule files:

- `docs/rules/ai-workflow-quality-standards.md`
- `docs/rules/logging-standards.md`
- `docs/rules/encoding-standards.md`
- `docs/rules/java-code-standards.md`
- `docs/rules/python-code-standards.md`
- `docs/rules/configuration-standards.md`
- `docs/rules/testing-standards.md`

Additional project-specific rule files may be added under `docs/rules/`.

## Required Workflow

Use this workflow for feature work and behavior changes:

Generated workflow documents default to Chinese. Use English only when the user explicitly asks for English, and record that request in the relevant artifact.

Automatic goal mode:

1. `/sp-goal <requirement-or-change-id>`

Manual phase mode:

1. `/sp-brainstorm <requirement>`
2. `/sp-spec <change-id>`
3. `/sp-tasks <change-id>`
4. `/sp-impl <change-id>`
5. `/sp-complete <change-id>`

Commands may generate multiple artifacts, but artifact responsibilities must remain separate.

## Artifact Storage

- Durable contracts: `openspec/changes/<change-id>/proposal.md`, `design.md`, `tasks.md`, and `specs/<capability>/spec.md`.
- Process evidence: `.agent/workdir/sp-openspec/<change-id>/brainstorm.md`, `context.md`, review logs, mockups, workflow test-parameter records, and `completion.md`.
- Final documentation: `docs/wiki/<feature-or-story-title>.md`.

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

## /sp-goal

Use `sp-goal`.

Purpose:

- Detect the earliest incomplete phase for the requested or active change.
- Start from that phase and run all remaining phases through `/sp-complete`.
- Never skip phase artifacts, tests, coverage, reviews, finding closure, wiki generation, or archive gates.
- Never skip required independent review threads. `/sp-brainstorm`, `/sp-spec`, and `/sp-tasks` require one independent review thread; `/sp-impl` requires one main-thread full review and two independent final review threads.
- Never skip main-process comprehensive review or cross-validation between main-process findings and read-only independent review thread findings.

Rules:

- If no change exists and the user provides a requirement, derive a change ID and start from `/sp-brainstorm`.
- If exactly one active change exists and no change ID is provided, continue that change.
- If multiple active changes exist and no change ID is provided, ask which change to finish.
- If `brainstorm.md`, `context.md`, or `brainstorm-review.md` is missing, blocked, or lacks customer/user confirmation of the reviewed final brainstorm output, start at `/sp-brainstorm`.
- During `/sp-goal` brainstorm recovery, draft brainstorm/context content in the conversation, complete main-process review, independent read-only review, cross-validation, and required revisions, then wait for customer/user confirmation of the reviewed final draft before creating or updating brainstorm files.
- If proposal/spec/design artifacts, `spec-review.md`, or `design-review.md` are missing or blocked, start at `/sp-spec`.
- If `tasks.md` or `tasks-review.md` is missing or blocked, start at `/sp-tasks`.
- If `design.md` exists but lacks customer/user confirmation for backend logic, UI mockup/function description, API paths/parameters, configuration parameter names/values, or E2E required/not-required decision, treat spec/design as incomplete; re-enter `/sp-spec` to review the pending design confirmation package first, then confirm it with the customer/user and update `design.md` plus `design-review.md` before task creation.
- If tasks, tests, per-task reviews, coverage, or final `review.md` are incomplete, start at `/sp-impl`.
- If implementation review is complete but completion/wiki/archive is missing, start at `/sp-complete`.
- Do not mark tasks complete without implementation and review evidence.
- Do not mark tasks complete without standalone full verification evidence when relevant.
- Do not mark spec/design complete without required customer/user confirmation evidence in `design.md` and zero unresolved blocking gaps in `design-review.md`.
- Stop when progress requires user input or approved OpenSpec scope changes.

## /sp-brainstorm

Use `sp-brainstorm`.

Create or update only after customer/user confirmation of the reviewed final brainstorm/context draft:

- `.agent/workdir/sp-openspec/<change-id>/brainstorm.md`
- `.agent/workdir/sp-openspec/<change-id>/context.md`
- `.agent/workdir/sp-openspec/<change-id>/brainstorm-review.md`

Rules:

- Draft the proposed `brainstorm.md` and `context.md` content in the conversation first.
- Read `docs/ai-context/source-index.md` first when it exists.
- Read relevant project-defined rules under `docs/rules/*.md`, standards, wiki snapshots, existing specs, and similar code.
- Read the default language, configuration, and testing rules when they match the requested technology or artifact type.
- Challenge product scope before spec: real user, pain, outcome, smallest useful slice, rejected scope, alternatives, and open questions.
- Do not write code.
- Do not create proposal, specs, design, or tasks.
- Record conflicts and context gaps instead of guessing.
- Run main-process comprehensive review on the draft before asking for customer/user confirmation.
- Start one read-only independent review thread for the drafted brainstorm/context content. Findings return to the main thread; the main thread cross-validates against its own findings, confirms issue status, revises the draft, and re-runs affected review until zero unresolved blocking findings.
- Cross-validate main-process findings and independent-thread findings; record valid, duplicate, false-positive, already-fixed, and user-decision findings in `brainstorm-review.md` after file creation.
- Confirm the reviewed final brainstorm/context draft with the customer/user before file creation and `/sp-spec`; record the confirmation in `brainstorm-review.md` after file creation.
- If review findings or customer/user requested changes alter the draft materially, re-run the affected review before asking for confirmation again.
- Do not create or update `brainstorm.md`, `context.md`, or `brainstorm-review.md` until the reviewed final draft is confirmed.
- Do not proceed to `/sp-spec` with unresolved blocking gaps in `brainstorm-review.md`.
- Do not proceed to `/sp-spec` without customer/user confirmation of the reviewed final brainstorm output.

## /sp-spec

Use `sp-spec`.

Create or update:

- `openspec/changes/<change-id>/proposal.md`
- `openspec/changes/<change-id>/specs/<capability>/spec.md`
- `.agent/workdir/sp-openspec/<change-id>/spec-review.md`
- `openspec/changes/<change-id>/design.md`
- `.agent/workdir/sp-openspec/<change-id>/design-review.md`
- `.agent/workdir/sp-openspec/<change-id>/mockups/` when UI changes require mockups

Rules:

- Base output on `brainstorm.md`, `context.md`, `openspec/project.md`, and relevant existing specs.
- Read relevant docs, rules, and similar implementation before writing design.
- Do not start proposal/spec work until `brainstorm-review.md` records customer/user confirmation of the reviewed final brainstorm output.
- Read relevant project-defined rules under `docs/rules/*.md` and encode behavior-affecting rules as observable requirements or scenarios.
- Read the default language, configuration, and testing rules when they affect observable behavior, validation, security, or delivery constraints.
- Specs must describe observable behavior only.
- Specs must define behavior so it can be verified from a real user/API/job/system entry point.
- Specs must describe enough external behavior for design to decide whether real E2E is required: external entry point, actor/client, trigger, expected observable result, and side effects.
- The E2E required/not-required decision is made in design and must be confirmed with the user after reviewed design draft closure and before tasks or implementation.
- Unit tests, mock-only tests, class initialization tests, and isolated method tests must not be accepted as E2E evidence when E2E is required.
- Tests must focus on project-owned behavior; do not design tests whose primary target is dependency package behavior, SDK internals, framework behavior, or third-party API/provider correctness.
- Backend behavior must allow later real API request/response verification; UI behavior must allow UI test verification; bug fixes must identify the bug entry point; external service behavior must identify observable effects when relevant.
- Use OpenSpec Requirement and Scenario format.
- Review proposal/spec alignment before design.
- Do not create design until `spec-review.md` has zero unresolved blocking gaps.
- `design.md` must include Source Mapping, Rules Compliance, Spec Gaps, code path planning, reuse/common logic planning, requirement-scope/fallback decisions, parameter/data-object planning, comments/logging/traceability planning, encoding/no-mojibake planning, standalone verification, E2E design, and customer/user confirmation evidence.
- `design.md` must prepare a pending confirmation package for backend logic decisions, UI mockup/function description, API paths/parameters, configuration parameter names/values, and E2E required/not-required decisions.
- Before asking the customer/user to confirm design decisions, the main process must review the spec/design draft, start one read-only independent review thread, cross-validate findings, revise, and re-run affected review until there are no unresolved blocking findings except explicit pending customer/user decisions.
- After review closure, `design.md` must record customer/user confirmation for backend logic decisions, UI mockup/function description when applicable, API paths/parameters when applicable, configuration parameter names/values when applicable, and E2E required/not-required decision.
- If E2E is confirmed as required, `design.md` must define command/tool, runtime target, test data, request/UI flow/job trigger, assertions, and evidence.
- `design.md` must define the project-code test boundary and require mocks, stubs, contract fixtures, local fakes, or explicitly approved sandbox/test endpoints for third-party integrations unless a real provider call is explicitly approved.
- If the confirmed design decision reveals missing or incorrect spec behavior, update specs and `spec-review.md` before task creation.
- Create `design-review.md` during draft review and resolve all design review blocking gaps before `/sp-tasks`.
- Start one read-only independent review thread for proposal/spec/design draft artifacts before design customer/user confirmation. Findings return to the main thread; the main thread cross-validates against its own findings, confirms issue status, fixes, replies, re-runs affected review, and records closure in `spec-review.md` and/or `design-review.md`.
- Cross-validate main-process spec/design findings and independent-thread findings; record valid, duplicate, false-positive, already-fixed, and user-decision findings before `/sp-tasks`.
- Do not create tasks.
- Do not write code.
- Do not proceed to `/sp-tasks` with unresolved blocking gaps in `spec-review.md` or `design-review.md`.

## /sp-tasks

Use `sp-tasks`.

Create or update:

- `openspec/changes/<change-id>/tasks.md`
- `.agent/workdir/sp-openspec/<change-id>/tasks-review.md`

Rules:

- Read `proposal.md`, `specs/`, `spec-review.md`, `design.md`, `design-review.md`, applicable mockups, relevant project-defined rules, and source references from the approved design.
- Do not create or modify `design.md`, `design-review.md`, `proposal.md`, or `specs/`.
- If a design decision, customer/user confirmation, API/config detail, E2E decision, mockup, or spec update is missing, return to `/sp-spec` instead of inventing it in tasks.
- Every task must reference a requirement, approved design decision, closed design-review evidence, applicable rules, target code paths, reuse/common logic impact, implementation-standard impact, and validation.
- Every task must include requirement-scope/fallback instructions and method/function parameter constraints.
- Every task must include code comment and logging requirements, including `trace_id`, log levels, structured fields, and sensitive-data exclusion when relevant.
- Every task must include encoding/mojibake validation requirements when it changes comments, code, configuration, test data, or text-bearing behavior.
- Every task must include standalone full verification from the relevant entry point.
- Every task must include applicable customer/user confirmation evidence for backend logic, UI mockups/function descriptions, API paths/parameters, configuration parameters, and E2E decisions, or a clear not-applicable reason.
- Every task must include the user-confirmed real E2E requirement or a design-confirmed not-applicable reason.
- Specs, tasks, and implementation must follow the user-confirmed E2E decision recorded in `design.md`.
- Backend service tasks must require real API request/response verification.
- UI tasks must require UI test cases and real browser QA or the project-approved UI runner when a runnable target exists.
- Bug fix tasks must identify and verify through the bug entry point.
- Database, Redis, Elasticsearch, queue, cache, or integration tasks must verify against project-provided connections/test environments when available; otherwise record skip reasons.
- External integration verification must prove project-owned integration behavior, not third-party provider correctness or availability.
- Every task must specify independent test parameter files under `.agent/workdir/sp-openspec/<change-id>/test-params/`.
- Every task must require at least 85% coverage for changed/affected code.
- Every task must state the project-owned code/behavior under test and prohibit tests dedicated to dependency packages or third-party API/provider correctness.
- Every task must require requirement-to-test mapping, a Requirement Counterexample Matrix for broad requirements, Masked-Test Analysis for gate/decision chains, Broad-Qualifier Audit for spec-vs-code qualifier mismatches, Decision Chain Trace for applicable gate/filter/sort/score/state-transition behavior, Evidence Capture Timing Audit for semantic evidence fields, and Deterministic Sort Audit for sort/rank/order behavior.
- Coverage percentage must not substitute scenario coverage or requirement-to-test mapping.
- Every task must include two implementation review gates: Alignment Review and Security Review.
- `tasks-review.md` must confirm each task has those gates and finding closure requirements.
- The main process must run a comprehensive task review, then start one read-only independent task review thread. Findings return to the main thread; the main thread cross-validates against its own findings, confirms issue status, fixes, replies, and records closure in `tasks-review.md`.
- Do not proceed to `/sp-impl` until `tasks-review.md` records main-process review, independent task review thread findings, cross-validation/finding confirmation, main-thread responses, and zero unresolved blocking findings.
- Do not write code.
- Review task alignment with specs, approved design, and design-review before `/sp-impl`.
- Do not proceed to `/sp-impl` with unresolved blocking gaps in `tasks-review.md`.
- Do not proceed to `/sp-impl` when required customer/user confirmations are missing.

## /sp-impl

Use `sp-impl`.

Before implementation, read:

- `AGENTS.md`
- `.agent/workdir/sp-openspec/<change-id>/brainstorm-review.md`
- `openspec/changes/<change-id>/proposal.md`
- `openspec/changes/<change-id>/specs/`
- `openspec/changes/<change-id>/design.md`
- `.agent/workdir/sp-openspec/<change-id>/design-review.md`
- `.agent/workdir/sp-openspec/<change-id>/mockups/` when UI changes require mockups
- `openspec/changes/<change-id>/tasks.md`
- `.agent/workdir/sp-openspec/<change-id>/spec-review.md`
- `.agent/workdir/sp-openspec/<change-id>/tasks-review.md`
- `.agent/workdir/sp-openspec/<change-id>/task-reviews.md`
- `.agent/workdir/sp-openspec/<change-id>/test-params/`
- relevant `docs/rules/*.md`

Rules:

- Implement only unchecked tasks in `tasks.md`.
- Stop before coding if prior phase reviews contain unresolved blocking gaps.
- Stop before coding if `design-review.md` is missing or has unresolved blocking gaps.
- Stop before coding if required customer/user confirmation evidence is missing in `brainstorm-review.md`, `design.md`, or `tasks.md`.
- Stop before coding if the task's required QA plan is missing.
- Load applicable Java, Python, configuration, and testing rules before editing code, config, or tests.
- Complete tasks one at a time.
- Create or update explicit test parameter files under `.agent/workdir/sp-openspec/<change-id>/test-params/`.
- Tests must use explicit parameters and assert meaningful behavior from specs/design.
- Changed/affected code must reach at least 85% coverage.
- Coverage cannot substitute requirement coverage, scenario coverage, or requirement-to-test mapping.
- Build and record a Requirement Counterexample Matrix before marking each task complete.
- Alignment Review must actively try to disprove each broad requirement with non-default and adversarial variants.
- Masked tests do not prove later decision semantics; review evidence must explain why each proving test is not masked by an earlier gate, filter, sort, or transform.
- Record Decision Chain Trace when code includes gate, filter, admission, eligibility, validation, sort, score, rank, selection, state transition, workflow transition, or decision-chain behavior.
- Record Evidence Capture Timing Audit when fields semantically represent order/rank/position, snapshot, readiness/eligibility, confidence, score, timestamp, provenance/source/lineage, status/state/stage, audit trail, or decision reason.
- Record Deterministic Sort Audit when requirements involve sorting, ranking, ordering, priority, first/last selection, top-N selection, pagination order, or display order.
- Reviewers must answer whether an earlier gate, filter, sort, or transform can let a test pass without proving the target semantic behavior.
- Checklist presence is not evidence; audits must map to actual code paths, inputs, outputs, transforms, evidence fields, tests, and closure.
- If code uses a narrower qualifier than the spec, record a finding unless specs/design/tasks explicitly approve the exception.
- Standalone full verification must be completed for backend API, UI, bug-entry, and external-service behavior when relevant.
- User-confirmed required real E2E tests must be run against the designed runtime target and recorded with command, test data, assertions, and evidence.
- Unit tests, mock-only tests, class initialization tests, isolated method tests, and static screenshots do not count as real E2E evidence.
- Same or equivalent logic must be reused or generalized; avoidable duplicate logic must be fixed before task completion.
- Existing-code changes must implement only approved requirements. Do not add fallback, compatibility, degraded-mode, dual-path, or silent default behavior unless specs/design/tasks explicitly require it.
- Methods/functions must have no more than 5 input parameters, or use explicit named data objects instead of vague maps/dicts/objects/key-value bags.
- Code implementation must include useful comments for non-obvious behavior and logs that trace key behavior with `trace_id` when context exists.
- Logs must not include secrets, credentials, tokens, session identifiers, raw personal data, or sensitive request/response bodies.
- Generated or modified comments, code, configuration, test parameters, and workflow artifacts must not contain mojibake, wrong transcoding, or unreadable characters.
- Generated/modified code files must stay <= 1000 lines.
- Database, OpenAPI, Controller/Service, API IO, and async rules must be implemented and evidenced when relevant.
- Do not write tests for empty/no-op code.
- Do not count tests that only verify class or method initialization.
- Do not write or count tests dedicated to dependency packages, SDK internals, framework behavior, or third-party API/provider correctness.
- After each task, run Alignment Review against spec, design, design-review, task, rules, requirement-to-test mapping, counterexample evidence, masked-test analysis, broad-qualifier audit, and changed code.
- After each task, run Security Review against concrete authentication, authorization, tenant/user isolation, validation, data exposure, logging, dependency, configuration, database/API IO, async, and external-service risks when relevant.
- Security Review must check concrete authentication, authorization, validation, data exposure, logging, `trace_id`, sensitive-data exposure, dependency, configuration, API IO, async, and external-service risks when relevant.
- Fix every finding from both reviews and re-review before starting the next task.
- Record all per-task review rounds and closure evidence in `task-reviews.md`.
- Do not add behavior outside specs.
- Do not modify unrelated files.
- Do not introduce new dependencies unless required by `design.md`.
- Reuse existing code patterns.
- Follow applicable project-defined rules.
- Update `tasks.md` after completing and verifying tasks.
- Run relevant tests and coverage checks; reject test evidence that targets dependency packages or third-party APIs instead of project code.
- Create or update `review.md`, including Rules Compliance.
- After all tasks are complete, run one main-thread full implementation review against every requirement, spec, design decision, changed code path, test, verification result, and rule.
- Start two independent final review threads: Thread 1 for requirement/spec/design/code alignment, and Thread 2 for security, implementation standards, regressions, logging, data/API/async/config, test quality, and file-size gates.
- Cross-validate main-thread full review findings and both independent-thread findings before fixing or closing implementation review.
- Independent review threads must not edit files. Findings return to the main thread; the main thread cross-validates against its own findings, confirms issue status, fixes, replies, verifies, and re-runs the relevant review until zero unresolved findings remain.
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
- `.agent/workdir/sp-openspec/<change-id>/brainstorm-review.md`
- `openspec/changes/<change-id>/proposal.md`
- `openspec/changes/<change-id>/specs/`
- `openspec/changes/<change-id>/design.md`
- `.agent/workdir/sp-openspec/<change-id>/design-review.md`
- `.agent/workdir/sp-openspec/<change-id>/mockups/` when UI changes require mockups
- `openspec/changes/<change-id>/tasks.md`
- `.agent/workdir/sp-openspec/<change-id>/task-reviews.md`
- `.agent/workdir/sp-openspec/<change-id>/review.md`
- relevant `docs/rules/*.md`
- relevant implementation files referenced by the change artifacts

Rules:

- Do not complete if `design-review.md` is missing or has unresolved blocking gaps.
- Do not complete if required main-process comprehensive review, independent review thread evidence, cross-validation/finding confirmation, main-thread responses, or closure is missing from `brainstorm-review.md`, `spec-review.md`, `design-review.md`, `tasks-review.md`, or `review.md`.
- Do not complete if `review.md` lacks one main-thread full implementation review, two independent final review threads, and cross-validation between them.
- Do not complete if any task in `tasks.md` is unchecked.
- Confirm applicable Java, Python, configuration, and testing rules were considered in review evidence.
- Do not complete if `task-reviews.md` has any open Alignment Review or Security Review finding.
- Do not complete if `review.md` has unresolved findings.
- Do not complete if coverage evidence is below 85% for changed/affected code.
- Do not complete if review evidence relies on coverage percentage without scenario-to-test mapping.
- Do not complete if `task-reviews.md` or `review.md` lacks a Requirement Counterexample Matrix for broad requirements.
- Do not complete if tests can be masked by earlier gates, filters, sorts, or transforms and no unmasked adversarial test is recorded.
- Do not complete if applicable Decision Chain Trace, Evidence Capture Timing Audit, or Deterministic Sort Audit evidence is missing or checklist-only.
- Do not complete if implementation has a narrower code qualifier than the spec qualifier unless explicitly approved in specs/design/tasks.
- Do not complete if any implementation-standard violation is merely explained but not fixed or explicitly approved as an exception.
- Do not complete if required customer/user confirmation evidence is missing or not followed.
- Do not complete if standalone full verification evidence is missing for relevant changed behavior.
- Do not complete if user-confirmed required real E2E test evidence is missing.
- Do not complete if avoidable same/equivalent logic duplication remains.
- Do not complete if unrequested fallback/compatibility behavior was added.
- Do not complete if methods/functions exceed 5 input parameters without explicit named data objects.
- Do not complete if required test parameter files are missing.
- Generate or update a semantic `docs/wiki/<feature-or-story-title>.md` file from specs, design, design-review, customer/user confirmations, code, rules, review evidence, and applicable Decision Chain Trace/Evidence Capture Timing Audit/Deterministic Sort Audit evidence.
- Update `docs/ai-context/project-learnings.md` when the completed change reveals reusable patterns, pitfalls, preferences, or verification notes; otherwise record that no reusable learning was found.
- Derive the wiki title and filename from the completed feature/story, not from the raw change ID.
- Create `.agent/workdir/sp-openspec/<change-id>/completion.md` with completion gate results and archive target.
- Review the generated wiki against specs, design, design-review, and implemented code before archiving.
- Archive the durable contract folder by moving `openspec/changes/<change-id>/` to `openspec/changes/archive/<YYYY-MM-DD>-<change-id>/`.
- Create a local git commit only after the completed change, tests, reviews, workdir completion evidence, wiki, and durable archive are finished.
- Do not commit `.agent/workdir/` process evidence unless the project explicitly requires retaining it.
- Do not overwrite an existing archive folder.
- Do not push unless the user explicitly asks.
- Commit only files belonging to the completed change; leave unrelated local changes unstaged.
- Commit message must include the complete requirement, completed changes, solution/design approach, workflow/completion evidence, and frontend/backend completion content when relevant.

Final response must include:

- Requirement / outcome summary
- Solution summary: design decisions, architecture choices, data/API/UI flow, and important tradeoffs
- Code changes: concrete changed areas and important file paths; include backend/API/data work and frontend/UI work when relevant, or state none
- Test and verification evidence: commands, real API/UI/E2E evidence when required, coverage result, and any accepted skip reason
- Documentation changes: wiki/user docs/README/API docs or other non-OpenSpec documentation created or updated
- Review and finding status
- Local git commit hash, or git skip reason
- Any skipped or blocked item

OpenSpec-related paths such as archive path, `completion.md`, or internal review artifacts may be included only as supporting evidence when useful. Do not lead the final report with OpenSpec bookkeeping.

## Source Priority

When sources conflict, use this priority:

1. `AGENTS.md`
2. Current OpenSpec change files and `.agent/workdir/sp-openspec/<change-id>/` evidence
3. `openspec/project.md`
4. `docs/rules/*.md`
5. `docs/standards/*.md`
6. active `docs/wiki/*.md`
7. existing implementation patterns
8. user prompt

If there is a conflict, report it in `context.md`, `design.md`, or `review.md`. Do not guess.
