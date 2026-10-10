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
  --output D:\APPROVED_EVIDENCE\manifest.json `
  --evidence-output D:\APPROVED_EVIDENCE\provider-acquisition `
  --acknowledge-provider-access

.\.venv\Scripts\python.exe .\scripts\recover_mlb_historical_results.py diagnose-evidence `
  --evidence D:\APPROVED_EVIDENCE\provider-acquisition

.\.venv\Scripts\python.exe .\scripts\recover_mlb_historical_results.py execute `
  --manifest D:\APPROVED_EVIDENCE\manifest.json `
  --approved-manifest-sha256 APPROVED_SHA256 --acknowledge-production-writes
```

Preview performs SELECT-only database work in read-only sessions. It verifies
capabilities and existing raw MLB mappings before provider requests. It fetches
the schedule, identified live feeds and standalone boxscores, and only the
missing players' people payloads. It never calls synchronization or persistence.
Manifest and provider-evidence outputs are created exclusively; existing evidence
is not overwritten. The explicit provider-evidence directory must be outside the
repository.

Provider acquisition evidence is written locally before planning begins. It
contains the schedule, per-game live feeds and standalone boxscores, any fetched
people payload, safe endpoint/gamePk/query metadata, observation timestamps and
deterministic payload hashes. It does not retain HTTP request objects, headers,
credentials, database configuration or environment data. MLB Stats requests use
public HTTPS endpoints without an API key. The maintained clients send only the
documented schedule date/sport ID, gamePk path, or people IDs/hydration parameters.

`acquisition_complete.json` is created only after the complete payload bundle and
hash index are durable. An acquisition failure can leave explicitly incomplete
evidence without that marker. A planning failure leaves the completed provider
evidence on disk and reports its path, while the manifest remains absent. Manifest
write failure and success are recorded separately in `preview_status.json`.
These artifacts are local files, never database writes. A failed preview remains
zero-write, and retained provider payloads do not authorize recovery execution.
Execution still requires separate review and approval of an exact manifest hash.

The `diagnose-evidence` mode performs no provider or database access. It compares
each retained live-feed `liveData.boxscore` with its standalone boxscore without
normalizing or modifying either payload, reporting deterministic differing paths
and bounded values. It is diagnostic only; preview validation separately compares
a recovery-relevant semantic projection while the raw diagnostic remains intact.

## Version 3 championship eligibility and identity contract

`final-championship-or-explicit-exclusion-v3` requires every allowlisted event to be
returned exactly once. Final confirmed R/F/D/L/W events are eligible. Preview/live
events, conditional/unresolved postseason events, explicit postponed/suspended/
cancelled states, and known non-model S/E/A/I games have retained exclusions.
Unknown/malformed types, including generic P/C, are errors. Shared confirmation
policy is documented in [the postseason candidate contract](mlb_postseason_canonical_schedule.md).
Policy bytes are pinned in the implementation fingerprint; v2 manifests are
refused rather than reinterpreted. This local candidate does not authorize recovery.
Explicit non-played terminal detail takes
precedence over a contradictory abstract `Final` state. Unknown states/types,
malformed final games and
absent allowlisted events fail closed. Eligible outside events fail before writes;
other outside events are reported, never persisted.

Every allowlisted event, including exclusions, requires exactly one raw
`mlb_stats` mapping, an existing canonical target, existing authoritative team
sources and matching orientation. Canonical Pacific date must match the requested
schedule date unless the disposition is exactly an explicit postponed, suspended
or cancelled zero-write terminal exclusion. Preview/live and
ineligible-game-type exclusions do not receive this exception and must retain the
approved schedule date. A permitted terminal exclusion may refer to the same exact
canonical identity after normal schedule reconciliation moved that game to its
later completion date; terminal exclusions never produce result/stat writes.
Eligible cross-date recovery is still refused until the canonical schedule date
is reconciled.
The existing-only MLB resolver accepts no source-name argument and never delegates
to generic matching/creation. Ordinary Odds/cross-source matching is unchanged.

Standalone MLB boxscores have no native gamePk. Their requested gamePk is pinned
and their content must agree with the boxscore embedded in the identified live
feed on every recovery-relevant value. The positive comparison projection covers
oriented team IDs; boxscore player keys and person IDs; ordered pitcher identities;
every team batting, pitching and fielding value persisted by the parser; and every
per-pitcher value that affects an appearance, decision or persisted statistic.
Copyright, display-only `person.boxscoreName` and hydrated team descriptors are
not recovery inputs and do not cause disagreement. Missing or differing required
identity/statistical values still fail closed; this is not a general missing-field
or path-ignore rule.
Schedule/feed start, official date, game type, finality, participants and scores
are validated. Positive game numbers and N/Y/S doubleheader flags must agree with
schedule metadata when supplied. MLB `S` is the split-doubleheader source flag;
the existing schema preserves its supported semantics as `doubleheader` plus the
positive game number. Other flags require a separately reviewed contract.
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
MLB IDs must agree when present. Every eligible target must have no existing
historical result, team statistics or pitching statistics. The guarded recovery
path inserts absent targets; it is not a populated/partial-history upsert repair.
Serializable execution protects
absent result-key predicates against concurrent conflicting inserts; serialization
failures are reported, never automatically retried against a changed observation.

## Transaction and failure contract

One approved date/manifest executes in one all-or-zero SERIALIZABLE transaction:
all eligible results, boxscores, enumerated missing players/source rows and result
metadata commit together. Canonical UPDATE and source SHARE row locks remain held
through that commit; the absent-target and approval bindings are revalidated
before mutation. There is no advisory lock in this path. Serializable predicate
protection and uniqueness constraints can refuse concurrent conflicting inserts;
they are not an exhaustive stress-test or global maintenance interlock. Different
date manifests are not one transaction. Normal ingestion is unchanged.

Structured output reports committed result gamePks, committed boxscore gamePks,
performed player synchronization, failed gamePks, phase and approved hash:

- `complete`: all planned eligible operations committed; explicit exclusions remain.
- `rolled-back`: writes started, but the transaction is known to have rolled back.
- `unknown-commit-state`: commit acknowledgement or rollback outcome is uncertain.
- `failed-before-write`: no recovery transaction is known to have committed;
  failed SQL may have rolled back and consumed sequence values.

Incomplete execution returns nonzero. `uncertain_commits` requires checking actual
database state before retry; connection loss at commit is not confirmed rollback.
Repeated complete execution is safely refused by the populated-target guard,
not silently rewritten. An eligible populated or partially populated date scope
requires a separately reviewed amendment; never remove/filter rows to satisfy
that guard. Verify the exact expected appearance set, all protected identities
and card/run fingerprints,
required result/stat coverage, older unresolved gaps and current production health.

Recovered history was not available to predictions made before recovery. Never
regenerate/relabel their point-in-time evidence. Freshness/provenance guards,
orchestration defects, migrations and scheduler changes are separate patches.

## Development operator preparation

The existing-only pinned schedule preview/execute and read-only feature-history
operator tools are described in [MLB operator tooling](mlb_postseason_operator_tools.md).
Their separate identity mutation envelope does not broaden this result/statistics
recovery contract. Preview is mandatory and active provider acquisition is not
part of those tools. INFERENCE_PUBLICATION_HOLD remains in force; Preview/Early
Entry is not a proven safe shadow mode. Late Night stderr truncation is a separate
post-recovery observability item, untouched by this tooling.
