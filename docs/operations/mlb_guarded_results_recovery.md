# Guarded MLB historical-results recovery

This dedicated tool recovers historical result sources independently of an
expired betting card. It does not repair predictions, evaluations, candidates,
settlements, Early Entry cohorts, or workflow state. Normal scheduled ingestion
and its canonical matcher are unchanged.

## Approval workflow

Implementation/review approval is not production/provider execution approval.
Obtain separate explicit authorization for the provider-backed preview, retain
and independently review its manifest, then obtain explicit authorization for
the exact manifest hash and mutation envelope before execution. CLI acknowledgements
are mandatory safety interlocks, not grants of authority.

Use one explicit schedule date and nonempty unique positive MLB gamePk allowlist
per recovery. Do not infer the allowlist from the date. Example placeholders:

```powershell
.\.venv\Scripts\python.exe .\scripts\recover_mlb_historical_results.py preview `
  --date YYYY-MM-DD --game-pks APPROVED_PK_1 APPROVED_PK_2 `
  --output D:\APPROVED_EVIDENCE\manifest.json --acknowledge-provider-access

.\.venv\Scripts\python.exe .\scripts\recover_mlb_historical_results.py execute `
  --manifest D:\APPROVED_EVIDENCE\manifest.json `
  --approved-manifest-sha256 APPROVED_SHA256 --acknowledge-production-writes
```

Preview performs SELECT-only database work in read-only sessions. It verifies
capabilities and existing raw MLB mappings before provider requests. It fetches
the schedule, identified live feeds and standalone boxscores, and only the
missing players' people payloads. It never calls synchronization or persistence.
Output is created exclusively; existing evidence is not overwritten.

## Version 1 eligibility and identity contract

`final-regular-or-explicit-exclusion-v1` requires every allowlisted event to be
returned exactly once. Final regular-season events are recoverable. Preview/live
events, postponed/suspended games and recognized non-regular game types have
explicit retained exclusions. Unknown states/types, malformed final games and
absent allowlisted events fail closed. Eligible outside events fail before writes;
other outside events are reported, never persisted.

Every allowlisted event, including exclusions, requires exactly one raw
`mlb_stats` mapping, an existing canonical target, existing authoritative team
sources and matching orientation. Canonical Pacific date must match the requested
schedule date. Cross-date rescheduling is refused, not automatically reconciled.
The existing-only MLB resolver accepts no source-name argument and never delegates
to generic matching/creation. Ordinary Odds/cross-source matching is unchanged.

Standalone MLB boxscores have no native gamePk. Their requested gamePk is pinned
and their content must agree with the boxscore embedded in the identified live
feed. Disagreeing responses are refused even when the difference seems incidental.
Schedule/feed start, official date, game type, finality, participants and scores
are validated. Positive game numbers and N/Y doubleheader flags must agree with
schedule metadata when supplied; other flags require a separately reviewed contract.
Exactly two oriented teams, one starter per team, unique pitcher
identities and consistent team/pitcher outs are required.

## Manifest and pinning

Canonical JSON uses sorted keys, compact separators, ordered game records and
no nonfinite numbers. SHA-256 covers the entire canonical manifest except its
own `manifest_sha256` field (not the literal file bytes or trailing newline).
Retain the exact output/hash, not a prose summary. Scope, schema/eligibility version,
full Git revision, implementation file hashes, observation timestamps, pinned
payloads/hashes, identity snapshot, every result/stat row, exclusions, player
synchronization and mutation classes are included. Payload list order is preserved
as observed evidence; reordering provider arrays changes that evidence hash.
Protected references are optional approval-context references, not SQL commands
or automatically evaluated assertions. Compare protected betting/card baselines
externally before/after authorized execution.

Pitching plans label MLB person IDs `mlb_player_id`; they are transport identities,
not canonical player IDs. Execution resolves canonical source mappings before
writing statistics. Missing-player metadata/source creation is enumerated using
the maintained MLB normalization contract.

Execution makes no provider calls. It validates the exact approval hash, revision
and implementation fingerprint, reconstructs the plan from pinned inputs and
refuses material differences before writes. No silent re-fetch/scope expansion.

## Mutation and concurrency envelope

Only approved canonical results, team statistics, pitcher appearances,
`game_number`/doubleheader metadata and explicitly enumerated missing players and
their MLB player-source rows may be written, with normal timestamps/sequences.
Existing player metadata is not refreshed. Team assignments, teams, canonical
game identities, game-source mappings and betting evidence are never written.

Existing mappings, targets, participants, retained sources and team/player source
identities are revalidated in each write transaction. Canonical rows use UPDATE
locks and source rows SHARE locks. A formerly missing player acquiring an equivalent
normalized MLB mapping can be reused for idempotency; conflicting metadata/mappings
refuse execution. Unique constraints remain intact. Concurrent player-source
insertion can fail/roll back that transaction; it does not remap or commit an orphan.
Distinct allowlisted MLB identities must not share a canonical target, and legacy
MLB IDs must agree when present. Existing historical result keys/dates must match
the approved identity before the maintained upsert. Serializable execution protects
absent result-key predicates against concurrent conflicting inserts; serialization
failures are reported, never automatically retried against a changed observation.

## Transaction and failure contract

Results commit once for the requested date; boxscores commit independently per
game. Whole recovery is NOT atomic. For recovery only, missing players and their
sources are created in the associated boxscore transaction. This deliberate
tightening prevents orphan metadata after a failed guarded boxscore and keeps
identity locks on the caller-owned transaction. Normal ingestion is unchanged.

Structured output reports committed result gamePks, committed boxscore gamePks,
performed player synchronization, failed gamePks, phase and approved hash:

- `complete`: all planned eligible operations committed; explicit exclusions remain.
- `partial`: an earlier transaction committed, or a commit acknowledgement is uncertain.
- `failed-before-write`: no recovery transaction is known to have committed;
  failed SQL may have rolled back and consumed sequence values.

Incomplete execution returns nonzero. `uncertain_commits` requires checking actual
database state before retry; connection loss at commit is not confirmed rollback.
Upserts preserve maintained identities/counts, not update timestamps. Extraneous
old pitcher rows are not silently deleted; verify the exact expected appearance
set after recovery. Verify all protected identities and card/run fingerprints,
required result/stat coverage, older unresolved gaps and current production health.

Recovered history was not available to predictions made before recovery. Never
regenerate/relabel their point-in-time evidence. Freshness/provenance guards,
orchestration defects, migrations and scheduler changes are separate patches.
