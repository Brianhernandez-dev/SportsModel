# MLB postseason operator-tooling candidate 0.6.2

DEVELOPMENT / independent review only. No production read/write, provider,
deployment, commit, task or workflow authority is granted by these commands.
Do not retrain or change frozen artifacts. Publication/inference remains held.

## Explicit target and access boundary

`scripts/mlb_postseason_operator.py` has history, preview and execute modes.
All require an explicit non-secret target JSON, date, database user, exclusive
outside-checkout output and database-read acknowledgement. Authentication uses
non-echoing getpass; echo fallback fails closed. No password argv/file/environment
discovery, no provider requests, no scheduled workflow or model loading. The CLI
suppresses repository dotenv import-time discovery during its own invocation.
Libraries require an explicit injected connection factory; no ambient fallback.

Target schema: fields host (literal loopback IP), port (client), database,
server_address (literal IP), server_port (may differ through Docker forwarding),
postmaster_started_at (aware ISO timestamp), identity_kind native/isolated,
system_identifier (isolated only), domain exactly MLB, migration_boundary exactly
33. Values must come from separately approved observed target evidence, not guesses.
The full 001-033 inventory, filenames and migration checksums must match reviewed
repository bytes; MAX(version) is insufficient. Newer/missing versions refuse.

Native production requires 127.0.0.1:5432/sportsmodel, pinned postmaster epoch,
server version major 16, and exact backend -> postmaster -> native service process
chain; one IPv4 listener, SportsModelPostgreSQL16 and exact pg_ctl/-D/-N identity.
Read-only CIM/listener observation requires host permissions. No privileged SQL
data_directory query, role change or superuser connection is used. Lack of proof
fails closed. Isolated verification refuses production DB/name/host port and pins
its system identifier (test-role query), server endpoint and epoch. Both modes
verify actual libpq client endpoint as well as connected server endpoint.

## Read-only H-1 gate

Example placeholders (not runnable authorization):

```powershell
.\.venv\Scripts\python.exe .\scripts\mlb_postseason_operator.py history `
  --target D:\APPROVED_EVIDENCE\target.json --db-user APPROVED_ROLE `
  --date YYYY-MM-DD --game-ids APPROVED_CANONICAL_IDS `
  --starter-ids APPROVED_CANONICAL_STARTER_IDS --cutoff AWARE_ACTUAL_CUTOFF `
  --output D:\APPROVED_EVIDENCE\history-check.json --acknowledge-db-read
```

Supply every retained MLB target-date canonical game ID (1-16 unique), and exactly two
canonical baseball_player_ids per game from separately approved current probable
starter evidence. All supplied starter IDs must be unique across the entire slate
for this operator version. Duplicates refuse before opening a database connection;
exceptional legitimate repeated-pitcher slates require separate explicit review,
not deduplication or weakened normal admission. These are NOT MLB transport person
IDs. The tool cannot certify
that a caller's manually supplied starter list matches a current provider: no
provider loader exists here. Revalidate identity/starter evidence at the actual
inference cutoff before future use. Cutoff must be aware, not future, and before
all target starts. Date scope is Pacific UTC-converted half-open midnight interval.
An empty or mismatched target slate is a refusal, not PASS.

One READ ONLY REPEATABLE READ session includes all reads. Authoritative team and
player source identities prove MLB domain. The real 200-game team / 50 persisted
starter-start selector and public completeness gate are reused without weakening.
Additionally, the tool audits each target team's last 200 retained canonical
events before cutoff, including events lacking mlb_stats mapping; invisible or
ambiguous identities FAIL rather than disappear. This conservative extra check
may include duplicate/nonplayed Odds rows. Disposition must precede PASS; the
tool does not infer occurrence or invent terminal exemptions. Actual selected
history IDs/range, invisible IDs, completeness diagnostics and PASS/FAIL emitted.
Independently, it audits each supplied canonical starter's newest 50 persisted
prior starts, including former-team/traded-player appearances, WITHOUT requiring
a game-source mapping before selecting the window. The authority is
`pitcher_statistics_repository.GET_COMPLETED_STARTS_BEFORE_QUERY`, reached through
`FeatureDataProvider` and `StartingPitcherFeatureBuilder.SEASON_START_LIMIT=50`:
exact player, is_starter TRUE, game_date strictly before cutoff, pitching created_at
at or before cutoff, participant orientation, game_date/game_id descending. The
limit must agree with completeness.FEATURE_START_LIMIT or the gate refuses.
Season/year and last-five builder filters occur after that 50-start fetch; the
operator audits the entire fetched window. Relievers and post-cutoff rows do not
enter this independent window. Invalid eligible orientations are conservatively
refused even outside the newest 50; selected participants must prove MLB identity,
and duplicate player/game appearances refuse. Team and starter windows are derived
separately before canonical IDs are deduplicated. Every selected game needs one
valid mlb_stats identity; mapped independent windows are also validated with the
existing completeness snapshots even if the core mapping-filtered selector differs.
Core feature/completeness selection remains unchanged and can conservatively add
requirements beyond the independent PIT starter window; PASS never bypasses it.
Report fields distinguish retained_team_history_games, retained_starter_history_games
(player, game, start, team, created_at, rank), each window's missing-identity IDs,
combined games_missing_mlb_stats_identity, visible_required_game_pks and
games_missing_required_feature_history. retained_history_games remains the legacy
team-only field. No statement certifies live probable-starter or provider freshness.
FAIL returns exit 1; no run, prediction, odds, settlement, publication or DB write.
Even PASS does not lift INFERENCE_PUBLICATION_HOLD or certify wagering readiness.

## Reconciliation allowlist version 1

See mlb_reconciliation_allowlist.schema.json and the SYNTHETIC-only example.
One explicit date, raw payload SHA-256, nonempty exact gamePk list (maximum 16),
canonical home/away names, expected aware start, required existing canonical ID,
exact current source list and exact resulting source list. Only addition of that
gamePk's mlb_stats mapping is legal; retained Odds IDs never removed or remapped.
Only existing mlb_stats/odds_api source identities supported. No wildcard dates,
new canonical games/teams, placeholders, unbounded ranges or arbitrary sources.

Pinned raw schedule bytes/hash checked before DB access; strict duplicate-key /
nonfinite JSON and shared date/envelope/confirmation policy. Every returned game
must be exactly allowlisted once; even an intentional non-model outside event is
not silently filtered. Each expected provider start equals pinned evidence and
falls in the approved Pacific date. Real club/source identities and orientation
must match. Conditional Y/TBD/unresolved games refuse conservatively.

```powershell
.\.venv\Scripts\python.exe .\scripts\mlb_postseason_operator.py preview `
  --target D:\APPROVED_EVIDENCE\target.json --db-user APPROVED_ROLE `
  --date YYYY-MM-DD --payload D:\APPROVED_EVIDENCE\schedule.json `
  --allowlist D:\APPROVED_EVIDENCE\allowlist.json `
  --output D:\APPROVED_EVIDENCE\preview.json --acknowledge-db-read
```

Preview is SELECT-only READ ONLY REPEATABLE READ and rolls back/closes. It invokes
the maintained canonical matcher in existing-only/no-mapping mode, not a second
matching algorithm. New mode flags default to unchanged ordinary behavior; a
no-mapping mode without existing-only is refused before SQL. Snapshot includes
oriented same-date/nearby candidates, raw mappings, teams/source identities and
original timing. A second same-day oriented row refuses even if normal near-time
matching could prefer one. Start drift capped at the existing 15-minute tolerance:
incident tooling intentionally does not automatically exercise ordinary same-day
fallback beyond that cap. Large reschedules/doubleheaders need independent review.

Preview canonical body hash pins raw payload and allowlist hashes, exact target,
full current identity snapshot, schema fingerprint and operator/shared-rule source
bytes. It is deterministic for unchanged inputs/DB/code, without a fresh clock
field. Approve this canonical preview_sha256, not the raw JSON file hash.

## Later execution — implemented, NOT authorized/performed on production

```powershell
.\.venv\Scripts\python.exe .\scripts\mlb_postseason_operator.py execute `
  --target D:\APPROVED_EVIDENCE\target.json --db-user APPROVED_ROLE `
  --date YYYY-MM-DD --payload D:\APPROVED_EVIDENCE\schedule.json `
  --allowlist D:\APPROVED_EVIDENCE\allowlist.json `
  --preview D:\APPROVED_EVIDENCE\preview.json `
  --approved-preview-sha256 EXACT_APPROVED_CANONICAL_HASH `
  --output D:\APPROVED_EVIDENCE\execution.json `
  --acknowledge-db-read --acknowledge-writes
```

One SERIALIZABLE transaction; exact preview/payload/allowlist/date/target/code
binding, target/schema guard, locked state reconstruction and byte comparisons
before mutation. UPDATE locks on all relevant existing candidate games;
SHARE locks on teams and source rows. No advisory lock. SERIALIZABLE predicates/uniqueness
protect concurrent insert conflicts; errors never automatically retry. Existing
source rows are retained, missing mlb_stats mapping added via the same matcher;
only approved existing timestamp refreshed via ordinary schedule updater with
unchanged participant IDs. Resulting source state verified before one commit.
No betting/history/team/player/workflow mutations. Maintenance quiescence still
needs separate approval; row locks aren't a global scheduler interlock.

Already reconciled exact state with freshly approved no-op preview is idempotent:
zero source/time writes. A stale pre-write preview repeated after successful
mutation is refused, not silently reinterpreted. New state needs a new approved
preview. Preserve execution stdout/receipt; output-file failure after commit is
not rollback (report is printed first). Commit/rollback acknowledgement uncertainty
requires inspection before any retry. Failed SQL may consume sequence values.

## Recovery/cohort and release constraints

0.5.0 demonstrates six Oct 6-7 targets have absent history, so v3's populated
guard is not their current blocker; missing identity is. Additional invisible
events' team/source/history details are incomplete in retained audit evidence.
Do not assume their emptiness, create inferred PKs, broaden recovery, or delete
rows. Any proven populated target requirement needs independent recovery-v3
amendment review; v3 implementation is unchanged by this task. See review package
RECOVERY_COHORT_ANALYSIS.md for evidence-bounded classifications.

INFERENCE_PUBLICATION_HOLD remains: recovery preparation independent of inference,
official/preview/Early Entry publication needs a separate reviewed release decision.
Neither Preview nor paper labels prove safe shadow mode. Late Night PowerShell
stderr truncation remains a separate untouched post-recovery hardening item.
