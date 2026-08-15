# NFL Phase 1 Team-Game Statistics Persistence

Migration 024 adds one provider-neutral `nfl_team_game_statistics` row per
`(game_id, team_id)`. It references existing `nfl_games` and canonical `teams`;
it does not copy scores, kickoff, status, opponent, home/away, or provider IDs.

## Canonical fields

| Canonical field | nflverse weekly field | Meaning |
|---|---|---|
| `completions` | `completions` | completed passes |
| `pass_attempts` | `attempts` | official pass attempts, excluding sacks |
| `passing_yards` | `passing_yards` | nflverse team passing yards |
| `passing_touchdowns` | `passing_tds` | passing touchdowns |
| `passing_interceptions` | `passing_interceptions` | interceptions thrown |
| `sacks_suffered` | `sacks_suffered` | sacks taken |
| `carries` | `carries` | official carries, including nflverse-defined scrambles/kneels |
| `rushing_yards` | `rushing_yards` | team rushing yards |
| `rushing_touchdowns` | `rushing_tds` | rushing touchdowns |
| `fumbles_lost` | `fumbles_lost_total` | all fumbles lost |
| `penalties` | `penalties` | team penalties; nullable when absent |
| `penalty_yards` | `penalty_yards` | team penalty yards; nullable when absent |

Counts use typed, nonnegative `SMALLINT` columns. Zero is preserved. Penalty
fields are nullable so missing historical evidence is not silently converted
to zero. Completions cannot exceed attempts.

Fantasy metrics, player/receiver shares, EPA, CPOE, air yards, defensive
derived values, returns, kicking/punting splits, timeouts, points, total yards,
first-down composites, weather, injuries, and quarterback fields are excluded.
Their semantics, versioning, availability, or Phase 1 scope are not sufficient
for canonical persistence. Scores remain exclusively in `nfl_games`.

## Resolution, evidence, and corrections

The adapter resolves `team` and `opponent_team` aliases through the stable
nflverse team mapping. It then requires exactly one existing canonical game
with the same season, season type, week, and unordered pair of participants.
It never infers home/away and never creates a game. A provider game mapping, if
present, must agree. Missing, conflicting, or ambiguous resolution is a hard
run failure. This includes stats for a cancelled/absent game such as 2022
BUF-CIN: no row is synthesized or quarantined because there is no canonical
identity to attach durable accepted evidence to.

Each invocation creates a durable `nfl_ingestion_runs` row. Every successful
statistics write creates a dedicated observation containing the run, source
asset provenance inherited through the run, canonical IDs, provider IDs, raw
canonicalized JSON, SHA-256, and retrieval time. Same-source reruns create a
normal new run and observation but the unique `(game_id, team_id)` canonical
row is updated, not duplicated. Thus the latest successfully committed
observation becomes canonical and prior evidence remains queryable.

The run is committed before processing. Canonical statistics and observations
are committed atomically afterward. Any processing error rolls them all back,
then marks the durable run failed in a fresh transaction. Failure bookkeeping
does not mask the original exception.

These historical statistics are only a data foundation. Future feature code
must enforce point-in-time availability before each prediction timestamp; this
slice does not calculate features, rolling values, models, or predictions.

The weekly dataset remains PBP-derived statistical evidence, not authoritative
game lifecycle evidence, and has no provider row update timestamp. Retrieval
time and asset hash therefore bound what was observed, not when nflverse first
published a correction.
