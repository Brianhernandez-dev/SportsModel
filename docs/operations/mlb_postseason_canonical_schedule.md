# MLB championship-season live-path candidate

## Implemented boundary

This is a DEVELOPMENT CANDIDATE, not a production-readiness assertion or execution
authorization. The shared policy in `ingest/mlb_game_policy.py` is used by canonical
schedule, prediction/probable-starter, normal results, and guarded recovery paths.
It admits exactly these concrete championship game-object types:

| Code | Competition |
| --- | --- |
| R | Regular Season |
| F | Wild Card |
| D | Division Series |
| L | League Championship Series |
| W | World Series |

The public, anonymous [MLB Stats game-type endpoint](https://statsapi.mlb.com/api/v1/gameTypes)
was checked on 2026-10-07. It also lists `S` (Spring Training), `E` (Exhibition),
`A` (All-Star Game), `I` (Intrasquad), `C` (Championship), and `P` (Postseason).
Those codes are not admitted. The generic labels `C` and `P` do not establish a
concrete supported postseason round; this patch makes no claim that they can
never appear in provider game objects. Unknown, missing, non-string, empty,
lowercase, or padded values are errors, not normal skipped games. This includes
generic P/C. Only S/E/A/I are deliberate non-model exclusions. Schedule/results
synchronization surfaces policy errors for the affected date; prediction and
recovery fail closed rather than silently publishing an incomplete slate.

Normal schedule synchronization, prediction/probable-starter loading, and
results ingestion also share one fail-closed response-envelope policy. A
top-level mapping with `dates: []` remains the only date-less valid empty
response. Every returned date block must otherwise be a mapping with a canonical
ISO `date` equal to the requested date and a list-valued `games` field, and every
game must be a mapping. Missing, malformed, mixed-date, or partial envelopes fail
the affected workflow before schedule/result persistence; entries are never
silently filtered into an empty or partial slate.

## Conditional games and participant confirmation

Anonymous MLB Stats evidence checked on 2026-10-07:

- [October 9, 2026](https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-10-09):
  D games 849824/849821 have real clubs and fixed times but `ifNecessary=Y`.
- [October 20](https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-10-20):
  L game 849814 has `Y`, `startTimeTBD=true`, and positive-ID AL seed placeholders
  (5521/5513).
- [October 31](https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-10-31):
  W game 849800 has the same conditional/TBD pattern and champion placeholders
  (2711/2710).
- Played [October 31, 2025](https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2025-10-31)
  and [November 1, 2025](https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2025-11-01)
  World Series games 813025/813024 are Final, with `ifNecessary=N`.

Policy choice (not a claim about every provider transition): defer Y games until
Live/Final evidence establishes occurrence; otherwise require N. Defer TBD starts.
Missing/unrecognized confirmation, invalid concrete metadata, or unresolved
participants on an otherwise confirmed game are actionable errors. Never infer
confirmation solely from a fixed timestamp, positive team ID, series record,
or the existence of an Odds row.

Confirmed postseason participants must have distinct IDs in the 30-club registry
verified from [MLB Stats teams for 2026](https://statsapi.mlb.com/api/v1/teams?sportId=1&season=2026),
matching official club names (plus retained Athletics/Cleveland historical
aliases), a positive gamePk, and an aware start. Registry
changes require explicit review, not silent admission. These checks occur before
the normal name-based team resolver can create a placeholder. Deferred games
create no canonical team/game/source evidence; later confirmation uses the same
gamePk and normal reconciliation, not a replacement placeholder identity.
The shared team-normalization layer maps the historical provider name
`Cleveland Indians` to the existing `Cleveland Guardians` canonical identity,
matching the established Athletics franchise-continuity rule and preventing a
second canonical Cleveland team.

## Prediction, results, recovery, and PIT boundaries

Confirmed R/F/D/L/W games can enter the existing prediction feature pipeline.
Team history and starter history retain their prior completed-game/PIT lookups;
bullpen history retains its same-calendar-year rule. Schema 1.2.0, feature meanings,
50-start/200-game limits, imputation, frozen model hash and training cutoff remain
unchanged. No retraining or artifact replacement is included. Training was on
regular-season games: mechanical eligibility is NOT evidence of postseason
calibration/performance or a deployment recommendation.

A supported slate that yields no eligible prediction games fails; a canonical
supported slate returning zero predictions also fails the daily workflow before
linkage/provider/evaluation. An all-conditional/postponed/already-started supported
slate is not a successful empty official/preview card. A genuinely empty or
known-non-model schedule is distinct from a processed/predicted/evaluated slate
with zero qualified wagers; the latter remains a legitimate no-pick card.

Normal authoritative results/completeness parsing admits final R/F/D/L/W games,
with non-played terminal detail taking precedence over contradictory Final status.
Canonical authority, source linkage, results upsert, boxscore provenance, and PIT
availability timestamps remain unchanged. Settlement consumes these authoritative
results, not Odds API settlement authority.

Postgame completeness uses the union of retained canonical `mlb_stats` IDs for
the target Pacific date (read before and after ingestion) and provider-finalized
IDs. An empty or partial response cannot erase retained history requirements.
The date interval is UTC-converted Pacific `[midnight, next midnight)`, matching
the canonical Pregame selector. Absent events are unresolved, not proof of no game.
The current schema does not persist played/cancelled status; retained games
therefore require history unless the current date-bound response explicitly
reports Postponed/Suspended/Cancelled/Canceled. Such an exclusion must match the
canonical participants, have unambiguous MLB identity, and conflict with no
retained result or statistics. Exclusions never create teams/games or erase history.
Deferred postseason games never admitted to canonical identity create no history
requirement. Explicit nonfinal but retained games without complete history remain
unresolved and fail the Postgame gate, including a no-pick/no-card workflow.
The general empty-ID completeness contract and feature-history selector remain
unchanged. Odds-only prior history still requires the operational ordering:
canonical `mlb_stats` identity -> authoritative result/stat repair -> completeness
verification -> future official prediction. This is not structural elimination
of H-1. POSTSEASON-AWARE RETRAINING REMAINS PROHIBITED because persisted game-type
identity remains insufficient; no schema or training change is included.

Guarded recovery uses `final-championship-or-explicit-exclusion-v3`. Old v2
manifests are refused, not reinterpreted. The shared policy bytes are included in
the implementation fingerprint. Explicit allowlists, pinned payload validation,
existing-only mappings, preview zero-write behavior, concurrency checks, partial
transaction reporting, and betting-state isolation are preserved. Conditional
postseason events retain an explicit zero-write exclusion; this does not grant
cross-date or unresolved-identity exceptions.

Early Entry has no separate season-type filter: it consumes preview predictions,
retained late-night odds, and the shared probable-starter loader. Its capture,
coverage, immutability, settlement, and cutoff rules remain unchanged. PowerShell
stderr/traceback observability is explicitly outside this candidate.

The missed October 6-7, 2026 official Pregame/Early Entry capture windows are
historical facts. Future authorized identity/result/source reconciliation MUST
NOT manufacture retroactive official predictions, market evaluations, paper or
Early Entry candidates, entry prices, or any betting decision represented as
pre-first-pitch evidence. No such recovery or production execution is authorized
by this candidate.

Anonymous schedule checks returned these identities and UTC starts; all six
game objects had `gameType=D`. These are observation-time provider facts, not a
production database verification or a backfill authorization.

| Schedule date | gamePk | gameDate (UTC) |
| --- | --- | --- |
| 2026-10-06 | 849819 | 2026-10-06T22:00:00Z |
| 2026-10-06 | 849826 | 2026-10-07T01:30:00Z |
| 2026-10-07 | 849833 | 2026-10-07T20:00:00Z |
| 2026-10-07 | 849822 | 2026-10-07T22:00:00Z |
| 2026-10-07 | 849838 | 2026-10-08T00:00:00Z |
| 2026-10-07 | 849827 | 2026-10-08T02:00:00Z |

Sources: [October 6 schedule](https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-10-06)
and [October 7 schedule](https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-10-07).
All listed starts fall within the corresponding Pacific calendar date.

Accepted games use the existing canonical resolver, `mlb_stats` source mapping,
schedule updater, and per-date transaction. No schema change is required by this
admission rule: the existing path persists game identity, oriented participants,
and timezone-aware start, not a new game-type field. Matching tolerance,
same-Pacific-date reconciliation, ambiguity/orientation refusals, and retained
Odds identity semantics are unchanged. Odds API does not become authoritative.

The canonical Pregame deadline query already uses `mlb_stats` identity, non-null
participants, and a Pacific-date UTC half-open interval, without a game-type
restriction. Scheduler windows and first-pitch refusal remain unchanged. New
fixture tests exercise real matching/source-link/update code and the deadline
query/guard contract using fake connections; they do not prove PostgreSQL
execution or live readiness.

## Separate production recovery proposal — NOT EXECUTED

This section is review-only. It grants no provider, production read/write,
deployment, backfill, task, or recovery authority. Each consequential step needs
separate explicit authorization. No runnable production recovery command is
provided here.

1. **Pin scope and protect evidence.** Before authorized deployment/recovery,
   re-establish current revision, effective production identity and schema,
   recoverability, and concurrency controls for schedule writers. Obtain an
   approved date/gamePk list from authoritative schedules, initially considering
   October 6 and 7, 2026. Investigate the reported September 27 coverage cutoff
   separately; do not silently expand the date range. Capture baseline canonical
   identities, source mappings, retained odds, prediction/evaluation/settlement
   identities, workflow states, and Early Entry cohorts under read authorization.

2. **Review reconciliation before writes.** For each approved gamePk, reconcile
   existing `mlb_stats` and `odds_api` rows using oriented participants,
   authoritative UTC start, Pacific date, and retained source identity. Review
   the normal matcher's nearby and same-date candidates. Require one supported
   canonical target. Refuse duplicate MLB mappings, conflicting orientation,
   multiple candidates, or split canonical identities; preserve existing rows and
   escalate rather than remapping/deleting them. Investigate apparently unmatched
   existing Odds rows before permitting a new canonical game.

3. **Authorize only the bounded schedule mutation.** Review an exact revision,
   date range, observed identities, expected target IDs, and allowed mutation
   envelope before using the maintained schedule synchronization path. It can
   insert games/source links and update start/participants, and commits each
   date independently; it is not an existing-only recovery tool or an atomic
   multi-date backfill. Fetch-date scope can include more events than a gamePk
   allowlist. If that scope cannot satisfy the approval, design/review a bounded
   mechanism separately instead of inventing unsupported allowlist flags or
   issuing ad hoc SQL. Preserve partial failure evidence and inspect committed
   state before any retry. No Odds acquisition is needed for source linkage.

4. **Verify linkage and identity preservation.** After separately authorized
   schedule synchronization, require exactly one `mlb_stats` mapping per approved
   gamePk, correct target/orientation/UTC start, no duplicate/split games, and
   preservation of existing Odds IDs and protected betting evidence. Check actual
   database identities and counts rather than treating a synchronization summary
   as proof. Validate the earliest start returned by the canonical deadline query
   for each Pacific date and retain before/after evidence.

5. **Preserve failed and expired workflow history.** Inspect the reported
   pending/initialized workflow with missing run IDs without resetting it. Do not
   fabricate predictions, odds captures, evaluations, settlements, or successful
   Pregame/Postgame states. Expired official windows remain historical gaps;
   later evidence cannot reconstruct an official PIT card. Leave Postgame guards
   intact. Any state-resolution or historical-result recovery must be separately
   specified, reviewed, and authorized; missing run IDs are not permission to
   bypass prerequisites.

6. **Review the complete live-path candidate before deployment.** Shared
   championship eligibility is implemented locally, not deployed or executed.
   Independently review the new policy, empty-slate refusals, recovery v3 contract,
   and remaining model/provider-transition uncertainty. Production identity/result
   recovery still requires separate exact-scope authorization. Do not treat local
   offline tests as proof of production or PostgreSQL integration readiness.

7. **Early Entry and health gates.** Inspect actual Early Entry cohort membership,
   immutable predictions, exposure/coverage records, PIT cutoffs, and dependencies
   before proposing recovery. Missing official outputs or later-loaded identities
   must not be retroactively relabeled as timely observations. Distinguish any
   separately authorized non-official diagnostics from official cohorts. Before
   declaring automation healthy, resolve the downstream eligibility issues and
   validate effective deployed code, application/database readiness, canonical
   coverage/deadlines, required feature/result freshness, actual eligible game
   counts, complete workflow lineage, dashboard/output behavior, and retained task
   logs from authorized in-window execution. A task's Ready state, a canonical row,
   or a local unit-test pass is not operational-health evidence. Task changes and
   reruns remain separately authorized actions.

No production health or recovery completion is asserted by this local patch.
