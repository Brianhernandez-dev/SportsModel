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

## Architecture and data integrity

- Preserve the established separation between domain models, analytics, services, persistence, and operational entry points. Keep database access isolated at the repository/service boundary and keep analytical transformations pure and deterministic where the existing design does so.
- Point-in-time correctness and prevention of data leakage are first-class requirements. Every prediction input must have been available at its prediction cutoff. Check joins, aggregates, rolling windows, corrections, market observations, labels, and derived features for accidental future information.
- Use explicit timezone-aware timestamps and the repository's documented interval semantics. Where a workflow defines a UTC half-open window, preserve `[start, end)` behavior and do not substitute descriptive labels such as week numbers for the authoritative selector.
- Preserve canonical identity and source provenance. Validate provider/source identity and canonical mappings, and fail clearly on missing, ambiguous, or conflicting mappings. Do not use an odds or market feed to invent canonical teams or games when the workflow requires existing canonical records.
- Preserve deterministic ordering, hashes, fingerprints, version identifiers, and immutable evidence contracts where present. Do not mutate frozen model artifacts or versioned protocols in place; make any authorized successor explicit and separately identifiable.
- Do not manually rewrite immutable prediction, odds, settlement, or audit evidence. Use the repository's idempotent operational path and retain the source/run lineage required to reproduce a result.

## MLB/NFL shared-system safety

- Preserve existing MLB and shared production behavior when extending NFL functionality, and preserve NFL behavior when changing shared components.
- Scope sport-specific reads and writes explicitly with the repository's canonical sport identity. Do not assume uniqueness, provider identity, event identity, or role semantics are sport-agnostic unless both the schema and code make that contract explicit.
- Changes to shared odds, ingestion, database, scheduling, settlement, or market-layer code require regression consideration for every supported sport that uses the changed path.

## Database, migrations, and production safety

- Treat production databases, live provider calls, and scheduled-task changes as consequential. Perform them only when explicitly authorized and only within the approved boundary. Do not modify production scheduled tasks or run destructive production database operations without an explicit instruction that identifies the intended operation.
- Audit actual production state before work that depends on it. Verify the database target, applied migration state, required columns/tables/indexes/triggers, and other prerequisites; running-code expectations are not proof that production is compatible.
- The standard migration runner discovers and applies all pending migration files. When authorization is limited to a specific migration boundary, first enumerate the discovered and applied versions, then use a controlled/version-capped path that cannot cross that boundary. Do not blindly run the standard all-pending path.
- Never edit the meaning of an already-applied migration. Add a new ordered migration, preserve existing data and unrelated protections, use transactional behavior where supported, and verify safe rerun/idempotency behavior where the migration or operational procedure requires it.
- When implementing or modifying a production workflow that depends on a minimum schema version, require a clear schema-compatibility preflight before live ingestion or processing. If the required version is absent, the workflow must fail before performing live work. Do not assume existing workflows already provide this protection; verify the implementation.
- Run destructive database tests only against the repository's disposable test-database fixture with all required safety acknowledgements. The test database URL must be explicitly configured, must differ from the production URL, and must never resolve to production.
- Prefer offline fixtures and mocked clients for provider testing. Do not make a live Odds API or other provider request unless explicitly authorized; live odds calls consume quota and must not be repeated merely as a test or casual retry.
- Use the documented preflight/dry-run mode before consequential production workflows when one exists. After an authorized write, validate transaction outcome, idempotency, audit lineage, and the absence of partial state.

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

## Completion report

At the end of a Codex task, report:

1. What changed.
2. Files changed.
3. Tests and validation run, with exact results and any skips.
4. Final Git branch/status and relevant diff checks.
5. Production impact, including whether any database, provider, evidence, or scheduled-task state changed.
6. Unresolved risks and work intentionally left incomplete.
