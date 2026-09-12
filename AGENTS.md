# SportsModel Repository Instructions

## Scope and sources of truth

- These instructions apply to the entire repository unless a more specific `AGENTS.md` exists below a working directory.
- Treat the current working tree, executable code, database migrations, tests, and maintained repository documentation as the sources of truth. Verify behavior in the repository instead of relying on stale task summaries or assumptions.
- Follow the existing `src/sportsmodel` package layout, database boundary, scripts, and documented architecture. Prefer the smallest change that satisfies the request; do not introduce unrelated redesigns, refactors, formatting churn, or line-ending normalization.
- Inspect the working tree before editing. Preserve unrelated and user-owned changes, including untracked files, and do not overwrite or discard them.
- Keep this file limited to durable operating rules. Do not add phase numbers, commit hashes, live row counts, current deployment status, temporary plans, or one-time debugging and incident details.

## Git safety

- Do not commit, push, merge, tag, reset, rebase, rewrite history, or otherwise mutate repository history unless the user explicitly requests that operation.
- Do not stage or discard unrelated changes. Before completion, report the branch/status and the files changed for the task, and review the relevant diff.
- Run `git diff --check` after modifying tracked files and report any whitespace errors. Check new untracked files for the same problems before handing them off.

## Work classification and authorization

- Distinguish investigation, implementation, and production verification before acting. Investigation is read-only diagnosis and evidence gathering; implementation may change repository files within the requested scope; production verification observes the effective live system and does not authorize production writes, provider calls, task changes, or configuration changes unless the user separately and explicitly authorizes them.
- Do not treat a request to inspect, review, diagnose, verify, or report as authorization to implement a fix or mutate external state. If investigation reveals that implementation or a consequential production action is required, stop and report the evidence and required authorization rather than silently broadening the task.
- For mixed requests, identify the boundary between each class of work and apply the strictest applicable safety rules to every production-facing step.
- Authorization is action-specific. Permission to inspect repository state does not authorize production access; permission for read-only production verification does not authorize writes; permission for a preflight or dry run does not authorize provider calls or persistence; and implementation approval does not authorize staging, commit, push, deployment, or production execution. Later safety rules add conditions but never grant authority by themselves.
- Discussion, planning, and independent review are non-executing work. ChatGPT planning or review output is advisory evidence, not authorization for Codex to edit files, stage, commit, push, access production, call providers, or change tasks/services. Codex execution requires a current explicit instruction identifying the authorized action and scope. Approval of a patch or review package authorizes only the separately stated next action.

## Architecture and data integrity

- Preserve the established separation between domain models, analytics, services, persistence, and operational entry points. Keep database access isolated at the repository/service boundary and keep analytical transformations pure and deterministic where the existing design does so.
- Point-in-time correctness and prevention of data leakage are first-class requirements. Every prediction input must have been available at its prediction cutoff. Check joins, aggregates, rolling windows, corrections, market observations, labels, and derived features for accidental future information.
- Apply the same leakage discipline to research, policy design, thresholds, model selection, and operational decision rules. Evidence already observed from a forward or holdout period is exposed and must not be reused as if it were independent confirmation. Declare any future confirmation cohort, evaluation boundary, decision rule, and permitted analyses prospectively before observing its outcomes; keep exploratory findings clearly separated from confirmatory claims.
- Before inspecting historical odds joined to model outputs, outcomes, or derived betting performance for policy design, preregister and preserve the research question, source snapshot, eligible population, PIT cutoff, exclusions, transformations, missing-data rules, metrics, baselines, multiplicity handling, decision thresholds, and confirmation cohort. Provider feasibility research such as coverage, timestamp cadence, licensing, and cost may occur before this join. Any methodology or threshold changed after observing joined performance data is exploratory and must not be presented as confirmatory. A revised confirmatory analysis requires a new prospectively declared cohort or untouched evidence boundary.
- Use explicit timezone-aware timestamps and the repository's documented interval semantics. Where a workflow defines a UTC half-open window, preserve `[start, end)` behavior and do not substitute descriptive labels such as week numbers for the authoritative selector.
- Preserve canonical identity and source provenance. Validate provider/source identity and canonical mappings, and fail clearly on missing, ambiguous, or conflicting mappings. Do not use an odds or market feed to invent canonical teams or games when the workflow requires existing canonical records.
- Distinguish complete loaded context, evidence actually used, and per-record trace scope. Do not label an observation as a contributor merely because it falls within a broad season, date, ingestion run, or development-era range. Derive dependency provenance from the actual reconstruction/dataflow graph, including upstream feature inputs, and record contribution counts and timestamps at the scope they describe.
- Preserve deterministic ordering, hashes, fingerprints, version identifiers, and immutable evidence contracts where present. Do not mutate frozen model artifacts or versioned protocols in place; make any authorized successor explicit and separately identifiable.
- Do not manually rewrite immutable prediction, odds, settlement, or audit evidence. Use the repository's idempotent operational path and retain the source/run lineage required to reproduce a result.

## MLB/NFL shared-system safety

- Preserve existing MLB and shared production behavior when extending NFL functionality, and preserve NFL behavior when changing shared components.
- Scope sport-specific reads and writes explicitly with the repository's canonical sport identity. Do not assume uniqueness, provider identity, event identity, or role semantics are sport-agnostic unless both the schema and code make that contract explicit.
- Changes to shared odds, ingestion, database, scheduling, settlement, or market-layer code require regression consideration for every supported sport that uses the changed path.

## Database, migrations, and production safety

- Treat production databases, live provider calls, and scheduled-task changes as consequential. Perform them only when explicitly authorized and only within the approved boundary. Do not modify production scheduled tasks or run destructive production database operations without an explicit instruction that identifies the intended operation.
- When production verification or operation is explicitly authorized, resolve current production state from the effective live configuration, connected identity, storage/topology, logs, schema, and task/service evidence required by that scope. Repository implementation alone does not authorize production access; when live verification is not authorized, report production state as unverified rather than probing it.
- Inspect the current migration runner before use. Treat any path that discovers or applies all pending migrations as uncapped. When authorization has a migration boundary, enumerate discovered and applied versions and use a controlled path that cannot cross the approved version; stop if no such path exists.
- Never edit the meaning of an already-applied migration. Add a new ordered migration, preserve existing data and unrelated protections, use transactional behavior where supported, and verify safe rerun/idempotency behavior where the migration or operational procedure requires it.
- When implementing or modifying a production workflow that depends on a minimum schema version, require a clear schema-compatibility preflight before live ingestion or processing. If the required version is absent, the workflow must fail before performing live work. Do not assume existing workflows already provide this protection; verify the implementation.
- A production schema guard must run before provider access, run reservation, persistence, or other side effects. Define compatibility by the minimum required version or capabilities, not by assuming the latest migration. Test incompatible, minimum-compatible, and newer-compatible states where forward compatibility is intended.
- A request to run disposable-database tests does not authorize connecting to production. Resolve the effective production identity through authorized configuration and topology evidence; connect only when production read access is separately authorized. If positive production/test separation cannot be established without unauthorized access, do not run destructive tests. Compare host, port, database, server identity, and storage/volume identity, accounting for aliases and forwarded ports, and fail closed on missing, ambiguous, or same-target evidence.
- Prefer offline fixtures and mocked clients for provider testing. Do not make a live Odds API or other provider request unless explicitly authorized; live odds calls consume quota and must not be repeated merely as a test or casual retry.
- After a live provider request may have been attempted, do not blindly retry. First determine whether the request was sent or accepted, whether local or remote state was persisted, and whether the workflow's documented retry, uniqueness, and idempotency rules permit another attempt. If that evidence is unavailable or ambiguous, fail closed and preserve the original attempt for investigation.
- A preflight, preview, or dry run may still access production, contact a provider, consume quota, acquire locks, or retain evidence. Inspect its implementation first and require authorization for every external interaction it performs. After an authorized write, validate transaction outcome, idempotency, audit lineage, and absence of partial state.
- For point-in-time-sensitive workflows, resolve the authoritative deadline from current canonical data and the workflow's trusted clock before the first attempt and before every retry. Refuse a retry that would begin or could complete outside the permitted window. If the deadline, current time, or remaining safe execution budget cannot be resolved reliably, fail closed.
- For scheduled-task changes or verification, capture the relevant task definition, identity, triggers, action, settings, and runtime state before and after the authorized operation. Verify the underlying application, database, endpoint, or service health separately; a scheduler status such as `Ready` or `Running` is not proof that the workload is healthy.
- For workloads expected to recover before interactive login, verify boot trigger, principal/logon type, credential and network limitations, working directory, process ownership, restart behavior, and retained evidence proving execution and health before login. Interactive success or scheduler state alone is insufficient.
- Treat production backup and recovery changes as consequential. Verify the actual backup artifact, manifest/integrity evidence, restore path, and source/target separation before declaring recoverability. A successful backup command alone is not proof that production data can be restored.

## Secrets and configuration

- Use the repository's existing environment and configuration-loading patterns. Do not hard-code credentials or copy secrets into source, tests, fixtures, documentation, or commits.
- Do not expose API keys, tokens, passwords, credential-bearing connection strings, or secret request parameters in commands, output, logs, persisted request context, or completion reports. Redact sensitive values while retaining enough non-secret context to audit the target and operation.

## Testing and validation

- Use the repository's Python environment and pytest configuration (`src` layout and `tests` test path). A standard local invocation is `.venv\Scripts\python.exe -m pytest` from the repository root.
- Run focused tests for the behavior changed. Run broader regression suites when a change affects shared infrastructure, cross-sport behavior, persistence, migrations, scheduling, or production-facing workflows; run the complete suite when the request or risk warrants it.
- Do not declare success based only on compilation or focused unit tests when database, migration, point-in-time, provider, or production behavior also needs validation. Use safe integration tests and read-only production validation as appropriate to the authorized scope.
- Investigate failures. Report exact commands, passed/failed/skipped results, reasons for skips, validation that could not be run, and any unresolved risk. Never present skipped or unavailable validation as a pass.

## Documentation

- Update the relevant architecture, source-contract, or operations documentation when a change alters a durable contract or runbook. Keep transient execution status and one-time plans out of durable architecture and repository instruction files.
- Make examples safe by default: use placeholders for sensitive values, clearly distinguish test from production targets, and do not present destructive or quota-consuming commands as routine validation.
- At meaningful high-impact milestones, obtain independent review before commit or production execution when the maintained workflow or user requires it. Preserve the reviewed diff or source export, validation output where required, source revision, exact path set, commands/results, redacted environment identity, manifest, byte sizes, and hashes outside the repository. Approval applies only to that reviewed revision/file set/artifact identity; substantive changes require re-review. Do not generate external evidence packages without authorization or a maintained runbook requirement.

## Completion report

At the end of a Codex task, report:

1. What changed.
2. Files changed.
3. Tests and validation run, with exact results and any skips.
4. Final Git branch/status and relevant diff checks.
5. Production impact, including whether any database, provider, evidence, or scheduled-task state changed.
6. For production-facing work, base the production-health assessment on separately verified application/service behavior, effective database readiness, endpoint or workflow health, and relevant retained logs—not merely command success, process existence, container state, or scheduler status. If live health verification was not authorized or could not be completed, state that explicitly and do not describe the work as operationally complete.
7. Unresolved risks and work intentionally left incomplete.
