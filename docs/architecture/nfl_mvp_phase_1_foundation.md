# NFL MVP Phase 1 Foundation

## 1. Phase 1 goal

Create the smallest additive NFL data foundation that can produce a
reproducible, point-in-time-safe baseline training dataset before the 2026
regular season, without changing MLB production behavior.

Phase 1 should establish:

- stable NFL franchise and provider identity;
- canonical scheduled and completed games;
- season, season type, week, venue context, status, and final scores;
- idempotent historical schedule/results loading with retained source evidence;
- a narrow team-game statistical boundary for the first baseline;
- a documented seam for later NFL Moneyline, Spread, and Total snapshots; and
- package and test boundaries that keep NFL code out of MLB workflows.

The recommended architecture is **hybrid**. Continue to use `teams`, `games`,
`game_sources`, `sportsbooks`, `odds_ingestion_runs`, and
`odds_market_snapshots` where their existing keys and shapes are genuinely
useful. Add NFL-specific extension tables and Python modules for concepts that
do not belong in MLB records. Do not redesign stable MLB tables merely to make
the system look uniformly multi-sport.

## 2. Explicit non-goals

Phase 1 does not include:

- an NFL prediction model or model training;
- production predictions, candidate qualification, or automation;
- live schedule, results, injury, depth-chart, or odds calls;
- full Moneyline, Spread, and Total ingestion;
- betting thresholds, CLV, staking, or automated wagering;
- production dashboard pages;
- perfect historical injury or starting-quarterback reconstruction;
- play-by-play, player props, fantasy projections, or tracking data;
- speculative cross-sport rewrites of MLB repositories;
- migrations applied to any database; or
- changes to MLB schedules, snapshot roles, model artifacts, or settlement.

Preseason data may be stored, but it is not required in the first baseline
training population. Spread and Total compatibility must be designed now, not
implemented now.

### Approved Phase 1 source decision

The approved historical provider is **nflverse**, consumed through static
`nflverse-data` release assets or an `nflreadpy`-compatible adapter. The
SportsModel contract is its own immutable Python records; Polars DataFrames and
`nflreadpy` objects must stop at the adapter boundary.

The approved historical population is 2018-2025 regular season plus
postseason. Preseason rows may be retained when available but are excluded from
the baseline population by default. This approval is only for the historical
Phase 1 foundation. nflverse is not automatically the future live production
provider; that remains a separate operational decision.

## 3. Existing SportsModel components reviewed

The audit covered the following repository areas at base commit
`5d38ee81c2eb040e85fc9a05116838069156142f`:

- migrations `001` through `021`;
- canonical `teams`, `games`, `game_sources`, and `historical_games` usage;
- MLB schedule and historical-results adapters;
- canonical game matching and team-name normalization;
- Odds API ingestion, ingestion-run auditing, sportsbook lookup, and market
  snapshots;
- baseball player, team assignment, team-game, and pitching-stat schemas;
- feature definitions, point-in-time context, providers, builders, generation,
  flattening, and Moneyline dataset construction;
- logistic-regression training, chronological splitting, artifact persistence,
  manifests, checksums, and prediction runs;
- market evaluation, paper settlement, performance reporting, daily
  orchestration, and snapshot scheduling; and
- read-only dashboard repositories and views.

Important repository facts:

1. `game_sources` already provides the correct external-event mapping shape:
   `(source_name, external_game_id)` is unique and maps to `games.game_id`.
2. `odds_ingestion_runs.sport` is already present, and
   `odds_market_snapshots` can represent `h2h`, spreads, and totals through
   `market_type`, `selection_name`, `line_value`, and `price`.
3. The live odds adapter is nevertheless MLB-specific through constants,
   Pacific calendar-day filtering, team-name insertion, `h2h` filtering, and
   MLB snapshot roles.
4. Scheduled odds-run uniqueness currently omits `sport`. The unique key is
   effectively `(target_date, snapshot_role)`, so an NFL scheduled run could
   collide with an MLB run for the same date and role.
5. Snapshot-role database checks encode the MLB sequence (`opening`,
   `evening`, `late_night`, `morning`, `entry`, `afternoon`, `near_close`).
6. `games` is used as a canonical cross-source key but has acquired MLB-only
   columns such as scheduled innings, doubleheader status, and game number.
   This is acceptable if NFL metadata is added in a one-to-one extension
   rather than adding more NFL columns to `games`.
7. Existing `teams` usage is name-centric. MLB alias handling is a small
   hard-coded map, not a provider-independent identity system.
8. Baseball features are strongly typed and point-in-time aware, but their
   contexts, groups, vectors, providers, and repositories include starting
   pitchers and baseball statistics.
9. Prediction, evaluation, workflow, and settlement persistence is explicitly
   MLB Moneyline (`moneyline_*`) and should not be generalized during NFL data
   foundation work.
10. The migration history assumes foundational tables such as `teams`,
    `games`, `historical_games`, and `sportsbooks` already exist; their original
    creation DDL is not represented in the numbered migration directory. A
    clean-bootstrap schema audit is therefore required before writing the
    first NFL migration.

## 4. Reuse matrix

| Subsystem | Classification | Phase 1 decision |
|---|---|---|
| PostgreSQL connection and migration runner | Reusable unchanged | Use the existing environment and migration execution conventions; do not run migrations during design. |
| `teams.team_id` | Reusable with generalization | Keep the canonical key, add NFL profile/source/history tables, and stop treating a display name as sufficient identity. |
| `games.game_id` | Reusable with generalization | Keep the canonical key and home/away/start fields; attach NFL metadata in `nfl_games`. |
| `game_sources` | Reusable unchanged | Use sport-qualified source names such as `nfl_provider_name` and `odds_api_americanfootball_nfl`. |
| `historical_games` | Not needed for NFL MVP Phase 1 | It is legacy name-based MLB results storage. NFL finals belong in typed NFL tables. |
| MLB team alias normalization | NFL-specific implementation required | NFL mappings must use stable provider IDs and franchise keys, not only names. |
| MLB schedule/results adapters | NFL-specific implementation required | Preserve their parse/validate/persist separation, but do not reuse MLB payload logic. |
| Canonical game matcher | Reusable with generalization | Source mapping is reusable; time-tolerance matching needs ambiguity detection and NFL reschedule/neutral-site rules. |
| `sportsbooks` | Reusable unchanged | Sportsbook identity is sport independent. |
| `odds_market_snapshots` | Reusable with generalization | Its row shape supports all three target markets; add validation/parsing above it rather than changing existing MLB rows. |
| `odds_ingestion_runs` | Reusable with generalization | Sport exists, but scheduled uniqueness, role validation, and lookup indexes must become sport-aware before scheduled NFL use. |
| Odds HTTP/request adapter | Reusable with generalization | Extract request configuration and response parsing from MLB constants; retain sport-specific entry points. |
| MLB snapshot schedule and roles | Not needed for NFL MVP Phase 1 | Do not copy the baseball cadence. Define NFL capture semantics only with a concrete operational requirement. |
| Consensus/no-vig/EV arithmetic | Reusable unchanged | These pure market calculations are not baseball-specific when inputs are valid complete markets. |
| Feature cutoff/context principle | Reusable unchanged | Point-in-time rules, deterministic generation, and source-time checks remain mandatory. |
| Baseball feature groups/builders | NFL-specific implementation required | Do not put NFL offense, defense, rest, or quarterback data into pitcher/batting abstractions. |
| Feature flattener/schema validation pattern | Reusable with generalization | Reuse contracts and deterministic ordering; create an NFL vector/schema. |
| Moneyline dataset builder | Reusable with generalization | The one-row-per-game, target-after-features pattern is useful; the current types and starter fields are MLB-specific. |
| Logistic baseline mechanics | Reusable with generalization | Chronological split, imputation, scaling, calibration metrics, and artifact hashing are reusable after a narrow utility extraction or an NFL wrapper. |
| MLB model artifacts/manifests | Reusable with generalization | Follow version/hash/cutoff conventions but use NFL-specific artifact types, schema versions, and paths. |
| `moneyline_prediction_*` persistence | NFL-specific implementation required | Add NFL prediction persistence later; do not widen frozen MLB tables. |
| MLB daily orchestration | Not needed for NFL MVP Phase 1 | Design ingestion commands first. Production orchestration follows a validated baseline. |
| Pure Moneyline settlement arithmetic | Reusable with generalization | Team selection and American-price profit arithmetic can be shared later. Spread/Total grading is NFL/market-specific. |
| MLB settlement repositories/workflows | NFL-specific implementation required | They reference MLB prediction/evaluation tables and legacy result storage. |
| Existing dashboard | Not needed for NFL MVP Phase 1 | Add NFL read-only pages only after persisted predictions and performance exist. |

## 5. Proposed NFL canonical data model

Use shared IDs for the narrow concepts that are already structurally common,
then use typed NFL extensions.

```text
teams
  1 --- 1 nfl_team_profiles
  1 --- * nfl_team_seasons
  1 --- * nfl_team_sources

games
  1 --- 1 nfl_games
  1 --- * game_sources
  1 --- 2 nfl_team_game_statistics
  1 --- * nfl_game_source_observations

nfl_ingestion_runs
  1 --- * nfl_game_source_observations

odds_ingestion_runs
  1 --- * odds_market_snapshots
                 * --- 1 games
                 * --- 1 sportsbooks
```

`teams` and `games` remain the join keys needed by existing sportsbook
storage. NFL rows become identifiable through their required one-to-one
extension rows; consumers must never infer sport from a team name.

### Team domain

An NFL team is a franchise identity, not its current display name. The stable
identity survives changes such as Oakland to Las Vegas or Washington naming
changes. Season-specific display and alignment data remains historical.

### Game domain

`games.game_date`, `home_team_id`, and `away_team_id` remain the canonical
event join fields. `nfl_games` owns football semantics:

- season;
- season type (`preseason`, `regular`, `postseason`);
- week label/number;
- lifecycle status;
- original and current scheduled start;
- final scores;
- overtime indicator;
- neutral-site indicator;
- venue/provider context; and
- update timestamps.

The current scheduled time should be reflected in `games.game_date` for
compatibility. The original scheduled time belongs in `nfl_games` so a flex,
postponement, or reschedule does not erase history.

## 6. Proposed table/schema additions

These are proposed migrations, not DDL to create during this assignment.

### `nfl_team_profiles`

```text
team_id                 PK/FK -> teams.team_id
franchise_key           text, unique, stable and project-owned
current_abbreviation    text, unique among active NFL teams
is_active               boolean
created_at              timestamptz
updated_at              timestamptz
```

Do not use a provider ID, city, nickname, or abbreviation as `franchise_key`.
Use a project-issued UUID stored in canonical lowercase form, prefixed for
human context (for example `nfl_franchise_<uuid>`). The UUID is assigned once
when SportsModel creates the franchise and never recomputed. Readable current
abbreviations remain separate attributes. This avoids embedding a relocation,
rename, or provider convention in immutable identity.

### `nfl_team_seasons`

```text
team_id                 FK -> nfl_team_profiles.team_id
season                  integer
display_name            text
abbreviation            text
conference              enum/check: AFC, NFC
division                enum/check: East, North, South, West
primary key             (team_id, season)
```

This preserves historical names and alignment without mutating old games.

### `nfl_team_sources`

```text
nfl_team_source_id      bigint PK
team_id                 FK -> nfl_team_profiles.team_id
source_name             text
external_team_id        text
source_team_name        text nullable
valid_from              date nullable
valid_to                date nullable
unique                  (source_name, external_team_id)
```

Provider IDs are the primary match. Names are retained for audit and aliases,
not used as the sole identity in normal ingestion.

### `nfl_ingestion_runs`

```text
nfl_ingestion_run_id    bigint PK
source_name             text
ingestion_type          schedule | results | team_stats
season_from/to          integer nullable
week_from/to            smallint nullable
started_at/completed_at timestamptz
status                  running | completed | failed
records_received        integer
records_written         integer
records_skipped         integer
error_message           text nullable
```

This provides restart and coverage evidence without coupling NFL source work
to MLB workflow tables.

### `nfl_games`

```text
game_id                         PK/FK -> games.game_id
season                          integer
season_type                     preseason | regular | postseason
week                            smallint nullable
week_label                      text nullable
status                          scheduled | postponed | cancelled |
                                in_progress | final | suspended
original_scheduled_start_time   timestamptz
home_score                      smallint nullable
away_score                      smallint nullable
went_to_overtime                boolean nullable
neutral_site                    boolean default false
venue_name                      text nullable
completed_at                    timestamptz nullable
source_updated_at               timestamptz nullable
created_at/updated_at            timestamptz
```

Checks should require scores and `completed_at` only for `final`, reject
negative scores, reject identical home/away teams through the shared game
record, and allow postseason week labels that are not naturally numeric.

### `nfl_game_source_observations`

```text
nfl_game_source_observation_id bigint PK
nfl_ingestion_run_id           FK
game_id                        FK -> nfl_games.game_id nullable until mapped
source_name                    text
external_game_id               text
observed_at                    timestamptz
source_updated_at              timestamptz nullable
payload                        jsonb
payload_sha256                 char(64)
unique                         (source_name, external_game_id,
                                payload_sha256)
```

Raw observations make parser corrections and reschedule audits deterministic.
If raw JSON volume proves material, the same manifest/hash design can point to
immutable files instead; a season of game-level NFL data is small enough that
JSONB is initially reasonable.

### `nfl_team_game_statistics`

The first typed statistics table should contain only provider-stable box-score
fields needed by the initial team baseline:

```text
game_id, team_id               unique pair
is_home
points
first_downs nullable
total_yards nullable
passing_yards nullable
rushing_yards nullable
pass_attempts nullable
rush_attempts nullable
sacks_allowed nullable
turnovers nullable
penalties nullable
penalty_yards nullable
possession_seconds nullable
source_name
source_updated_at nullable
created_at/updated_at
```

Advanced EPA, success rate, pressure, coverage, personnel, and play-level
fields should not be placed here until a licensed and stable source is chosen.

### Deferred player/quarterback tables

`nfl_players`, `nfl_player_sources`, and point-in-time quarterback availability
snapshots are valuable but should not block the first team-results baseline.
If the selected Phase 1 provider supplies stable player IDs and actual starter
identity at negligible additional cost, retain them in source observations and
add typed tables in a separate reviewed migration.

## 7. Team identity strategy

1. Seed exactly the 32 active franchises with project-owned franchise keys.
2. Create one `teams` row and one `nfl_team_profiles` row per franchise in one
   transaction.
3. Store season-specific display name, abbreviation, conference, and division
   in `nfl_team_seasons`.
4. Map each provider by external team ID in `nfl_team_sources`.
5. Treat provider names as audited aliases only. Name-only matching may suggest
   a mapping but must not silently create a second franchise.
6. Reject or quarantine unknown provider IDs until explicitly mapped.
7. Never rewrite old game team IDs when a franchise relocates or renames.

This is safer than adding NFL aliases to the MLB-only normalization dictionary
and avoids silently conflating a franchise with a seasonal display name.

## 8. Game identity and idempotency strategy

Primary identity is `(source_name, external_game_id)` in `game_sources`.

Ingestion order:

1. Parse and validate a provider record into a provider-neutral NFL object.
2. Resolve both teams by provider ID.
3. Resolve an existing `game_sources` mapping.
4. If unmapped, search conservatively by NFL identity: season, season type,
   home team, away team, and scheduled time window.
5. If zero candidates exist, insert `games`, `nfl_games`, and `game_sources`
   atomically.
6. If exactly one safe candidate exists, attach the new source mapping.
7. If multiple candidates exist, quarantine the row rather than guessing.
8. Upsert mutable schedule/status/result fields and append a raw observation.

The existing 15-minute game matcher is a useful starting pattern but cannot be
used unchanged. NFL flex scheduling and postponements can move an event by
hours or days. Once a source mapping exists, it remains authoritative despite
time changes. Neutral-site games retain provider home/away designation and set
`neutral_site=true`; they must not swap teams based on venue.

Suggested uniqueness and indexes:

- existing unique `(source_name, external_game_id)` in `game_sources`;
- unique `nfl_games.game_id` by primary key;
- index `(season, season_type, week)`;
- index `(status, original_scheduled_start_time)`; and
- no speculative natural unique key that would reject a rare duplicate or
  rescheduled event.

Reprocessing an unchanged payload writes no duplicate observation and updates
no semantic data. Reprocessing a changed payload appends an observation and
idempotently updates the canonical row.

## 9. Historical results ingestion design

Use a three-layer boundary:

```text
provider client / fixture reader
        -> pure payload parser
        -> validated provider-neutral NFL records
        -> transactional repository/upsert service
```

All clients must be injectable so tests use fixtures and never the network.
The first implementation should include a fixture-directory input mode before
any HTTP client is enabled.

Minimum retained raw fields, subject to the actual source contract:

- provider and external game ID;
- provider team IDs and names;
- season, season type, and week/round;
- scheduled start and provider update timestamps;
- home/away designation;
- game status and status detail when supplied;
- scores by side;
- overtime/period count when available;
- neutral-site and venue fields;
- source payload/hash and retrieval timestamp; and
- stable team box-score fields when supplied.

The approved initial historical range is **2018 through 2025**, including
regular season and postseason. Eight completed seasons provide roughly two
thousand games, cover current rules and team environments reasonably well, and
match the repository's preference for modern, chronologically evaluated data.
Load preseason for identity/schedule validation only if it comes from the same
source, and exclude it from baseline training by default.

The inspected nflverse schedule asset does not expose a lifecycle status,
original scheduled date, reschedule flag, or timezone marker. SportsModel must
not invent those facts: two scores mean `final`; two missing scores mean
`unplayed`; a single missing score is malformed. `gameday` plus `gametime` is
normalized using the documented nflverse schedule convention of US Eastern
time and immediately retained as a timezone-aware value. A coverage report by
season, team, season type, final-score completeness, and duplicate source ID is
required before training readiness is declared.

## 10. NFL odds integration boundary

No odds call or odds migration is part of Phase 1 foundation implementation.
The later integration should retain the shared market tables but first extract
a sport-configured adapter.

### Already sport-agnostic

- `sportsbooks` identity;
- ingestion-run lifecycle fields;
- game and sportsbook foreign keys;
- snapshot timestamp and source;
- American price;
- `market_type`, `selection_name`, and `line_value` storage;
- consensus, no-vig, expected-value, line-movement, and timeline arithmetic.

### Currently MLB-specific

- `SPORT = "baseball_mlb"` and `MARKETS = "h2h"`;
- Pacific calendar-day slate selection;
- scheduled snapshot-role vocabulary and role timing;
- the scheduled-run unique index, which omits sport;
- direct team creation by normalized display name;
- Odds API event matching assumptions;
- CLI names and orchestration; and
- Moneyline evaluation/prediction persistence.

### Required generalization before NFL scheduled odds

1. Introduce an immutable request configuration containing sport key, markets,
   regions, format, event window, and snapshot context.
2. Keep `fetch_mlb_odds` as a compatibility wrapper around the generalized
   adapter so MLB callers and tests do not change behavior.
3. Parse `h2h`, `spreads`, and `totals` into the existing snapshot shape:
   team selection plus nullable line for Moneyline; team plus spread line for
   Spread; `Over`/`Under` plus total line for Total.
4. Resolve team selections through `nfl_team_sources`; never insert an NFL team
   solely from an odds display name.
5. Change scheduled-run uniqueness and lookup to include `sport`, with an
   explicit regression test proving the same date/role can exist for MLB and
   NFL.
6. Separate role vocabulary from MLB timing. For an initial NFL MVP, use
   `manual` during validation and define at most `opening`, `official`, and
   `near_close` only after the desired weekly operating cadence is approved.

Current MLB roles should not be copied automatically. Football markets are
weekly, injury-driven, and strongly affected by quarterback news. The database
can reuse generic role labels later, but operational meaning must be documented
per sport.

## 11. Feature-data requirements for the eventual baseline

### A. Data required in Phase 1

- stable team/franchise identity and seasonal alignment;
- games with season, type, week, scheduled time, home/away, neutral-site, and
  lifecycle status;
- final scores and overtime;
- idempotent provider mappings and raw observations;
- a minimum team-game box score when consistently available;
- source/retrieval timestamps sufficient for leakage checks; and
- season-level coverage and integrity reporting.

### B. Features required for the first baseline model

Start with a deliberately small team-only feature set derived strictly from
prior completed games:

- home-field and neutral-site indicators;
- prior-season and season-to-date win rate;
- rolling points scored and allowed over 3, 5, and 8 games;
- rolling point differential;
- offensive and defensive yards/play or yards/game if coverage is reliable;
- turnover margin with sample count;
- rest days and short-week/long-rest indicators;
- recent form separated from season baseline;
- opponent-strength-adjusted rating, preferably a simple time-ordered Elo or
  equivalent rating;
- season/week and postseason indicators; and
- missingness/sample-size indicators.

The first model should be a home-win probability baseline. Market inputs stay
outside the first football-only feature set and are joined later for evaluation.

### C. Later enhancements

- point-in-time starting quarterback and backup identity;
- injury/game-status snapshots and active rosters;
- quarterback efficiency and availability deltas;
- play-by-play EPA, success rate, explosive plays, and early-down performance;
- opponent-adjusted offense/defense beyond a simple rating;
- special teams, pressure, coverage, personnel, and coaching changes;
- travel distance, time-zone, altitude, surface, roof, and weather;
- market-assisted features, line movement, and closing information;
- player-level projections; and
- Spread and Total-specific targets/features.

Quarterback availability is an explicit architectural boundary, not a hidden
assumption. The team-only baseline may proceed without reconstructed historical
injury designations, but no later live model should represent final starter
knowledge as though it were known at an earlier cutoff.

## 12. Proposed Python package/module layout

Keep NFL code visibly separate while reusing pure infrastructure:

```text
src/sportsmodel/nfl/
    __init__.py
    models/
        team.py
        game.py
        team_game_statistics.py
    ingest/
        records.py
        parser.py
        service.py
        cli.py
    database/
        team_repository.py
        game_repository.py
        ingestion_run_repository.py
        statistics_repository.py
    features/
        context.py
        definitions.py
        builders/
            team_form.py
            scoring.py
            defense.py
            rest.py
            rating.py
        vector.py
        service.py
    datasets/
        moneyline.py
    training/
        moneyline_baseline.py
```

Corresponding tests should live under `tests/nfl/` with the same subdivisions.

Do not add package files until the first implementation commit has real domain
objects and tests. Empty scaffolding creates no verified architecture.

Potential shared extractions should remain narrow and evidence-driven:

- provider-neutral ingestion-run status;
- chronological binary-classification utilities;
- artifact hashing/manifest validation;
- market parsing and snapshot persistence; and
- pure Moneyline grading.

An extraction must preserve current MLB public functions as wrappers and pass
all existing tests before NFL callers adopt it.

## 13. Proposed migration sequence

No migration is created or executed by this design task.

1. **Foundation schema audit:** document or reconstruct the authoritative base
   DDL for `teams`, `games`, `historical_games`, and `sportsbooks`; verify the
   next migration number on current main.
2. **NFL team identity:** add `nfl_team_profiles`, `nfl_team_seasons`, and
   `nfl_team_sources`; seed 32 stable franchise identities transactionally.
3. **NFL games and ingestion audit:** add `nfl_ingestion_runs`, `nfl_games`, and
   `nfl_game_source_observations` with status/final-score checks and indexes.
4. **NFL team-game statistics:** add only the source-stable fields selected
   after fixture inspection.
5. **Odds sport isolation, later:** make scheduled odds uniqueness/lookups
   sport-aware before any scheduled NFL snapshot; preserve all MLB role data
   and behavior.
6. **NFL prediction persistence, post-baseline:** add NFL-specific run,
   prediction, market-evaluation, and settlement tables only after the baseline
   data contract is proven.

Each migration should include repository-level SQL contract tests and a
rollback/recovery note. Apply them only in an isolated development database
after human review.

## 14. Proposed test strategy

### Pure domain and parser tests

- all season types and postseason week labels;
- timezone-aware scheduled starts;
- final-score and lifecycle invariants;
- overtime and neutral-site parsing;
- missing/unknown provider fields;
- franchise renames and provider aliases;
- malformed payload rejection; and
- fixture determinism.

### Repository contract tests with fakes

- provider-ID team resolution;
- unknown-team quarantine;
- source mapping before heuristic matching;
- idempotent game and result upserts;
- changed schedule/status updates without duplicate games;
- ambiguous match quarantine;
- rescheduled/postponed/cancelled games;
- observation payload hash deduplication; and
- transaction rollback on partial failure.

### Isolated integration tests

- migrations on an empty disposable database;
- migration compatibility against a schema snapshot matching main;
- 32-team seed repeatability;
- same external ID reload idempotency;
- regular/postseason uniqueness;
- exactly two team-stat rows per completed game where stats are complete; and
- no cross-sport odds-run collision after odds generalization.

### Feature/dataset tests, when implemented

- no source record at or after the game cutoff;
- no same-game final information in features;
- rolling windows and rest boundaries;
- season and postseason filtering;
- reschedule-aware start/cutoff behavior;
- stable feature ordering and schema version;
- deterministic dataset hash and row count;
- chronological train/validation/test splits; and
- explicit future-information rejection.

Existing MLB tests remain the mandatory regression suite for any shared-table
or shared-code change. Tests must use fixtures/fakes or an isolated disposable
database, never production PostgreSQL or live providers.

## 15. Recommended implementation sequence

The sequence is optimized for a usable baseline, not a complete multi-sport
platform.

1. Select and approve the historical schedule/results provider and store a
   small, immutable set of representative fixtures (regular season,
   postseason, overtime, neutral site, postponed/rescheduled, and rename).
2. Audit foundational DDL and implement canonical NFL team identity, seasonal
   names/alignment, provider mappings, repositories, and tests.
3. Implement pure provider-neutral NFL game/result records and fixture parser.
4. Add NFL game/ingestion/observation schema and idempotent persistence.
5. Load one season from offline fixtures/export into an isolated database and
   produce coverage, duplicate, and mapping reports.
6. Expand to 2018-2025 schedules/results and validate every season before adding
   features.
7. Inspect provider box-score stability; add the minimum team-game statistics
   table and parser fields supported across the chosen range.
8. Implement point-in-time team form, scoring/defense, rest, and simple
   opponent-rating builders.
9. Build and hash the first NFL Moneyline training dataset with chronological
   splits.
10. Only then implement the logistic home-win baseline.
11. Generalize odds ingestion behind the existing MLB wrapper, make run
   uniqueness sport-aware, and validate NFL Moneyline first.
12. Add Spread and Total parsing/evaluation one market at a time after
   Moneyline persistence and settlement are stable.

## 16. Risks and unresolved decisions

### Human decisions required

1. **Postseason week representation:** numeric week plus label is recommended;
   confirm desired reporting labels.
2. **Team baseline statistics:** approve the stable subset supported by the
   chosen provider before migration DDL is fixed.
3. **Quarterback scope:** decide whether actual starter identity is retained in
   Phase 1 typed tables or only raw observations. It should not block the first
   team-only baseline.
4. **NFL prediction cutoff:** choose an operational context before feature
   snapshots (for example, a fixed weekly time versus game-relative cutoff).
5. **Odds cadence:** define NFL meanings for opening/official/near-close rather
   than copying MLB clock times.
6. **Future live provider:** select separately from nflverse historical-source
   approval after freshness, corrections, availability, and support review.

### Technical risks

- foundational table creation is missing from numbered migration history,
  complicating clean database setup and migration testing;
- shared `teams` relies on globally unique display names and lacks a sport
  discriminator;
- heuristic game matching can mis-handle reschedules without source IDs;
- historical corrections can change scores/status after initial ingestion;
- provider box-score definitions may vary by season;
- final quarterback/injury data can cause leakage if treated as pregame data;
- scheduled odds runs can collide across sports until sport is included in
  uniqueness; and
- premature shared abstractions could destabilize frozen MLB behavior.

Mitigation is additive schema, fixture-first parsing, source-ID identity,
append-only raw observations, conservative quarantine, and full MLB regression
tests for every shared change.

## 17. Phase 1 completion criteria

Phase 1 is complete when:

- all 32 franchises have stable canonical and provider identities;
- 2018-2025 regular-season and postseason game coverage is loaded from the
  approved source in an isolated environment;
- schedules, reschedules, status, neutral site, overtime, and final scores are
  represented without changing MLB data;
- repeated ingestion is idempotent and changed source records are auditable;
- unknown or ambiguous teams/games are quarantined rather than guessed;
- season/team coverage and integrity reports meet approved thresholds;
- the minimum team-game statistics needed by the baseline are available or
  explicitly marked missing;
- a point-in-time feature-data contract is approved;
- the schema can later join NFL games to existing market snapshots without
  cross-sport run collisions;
- no live production workflow depends on the new code; and
- every existing MLB test plus all NFL foundation tests passes.

## Implementation checklist organized into small commits

1. **Document source decision and add fixtures**
   - Record provider/license decision.
   - Add sanitized representative payload fixtures and expected parsed records.
   - No database or network code.

2. **Add NFL team domain objects**
   - Add franchise key, season membership, and source mapping dataclasses.
   - Validate stable IDs, seasons, conference, and division.
   - Add pure tests.

3. **Add NFL team identity migration**
   - Add the three team tables and 32-franchise seed.
   - Add migration SQL checks and repository tests.
   - Validate only against a disposable database.

4. **Add NFL game/result parser**
   - Parse fixtures into provider-neutral immutable records.
   - Cover regular/postseason/overtime/neutral/rescheduled cases.

5. **Add NFL game persistence**
   - Add ingestion-run, game-extension, and observation tables.
   - Implement transactional source-ID-first upserts and quarantine results.
   - Add rerun and correction tests.

6. **Add coverage reporting**
   - Report seasons, teams, statuses, missing finals, mappings, and duplicates.
   - Validate one offline season before expanding the backfill.

7. **Add minimum team-game statistics**
   - Finalize fields from actual fixture coverage.
   - Add typed persistence and completeness tests.

8. **Add NFL feature-data boundary**
   - Add NFL context/vector/schema and prior-game repositories.
   - Implement leakage and deterministic-order tests before feature formulas.

9. **Add baseline feature builders**
   - Team form, scoring/defense, rest, home/neutral, and simple rating.
   - Add cutoff and rolling-window tests.

10. **Add baseline dataset readiness**
    - Create one row per eligible game, target after feature generation,
      coverage report, schema version, and dataset hash.
    - Stop before fitting a model for a separate reviewed assignment.

11. **Generalize odds safely, after data readiness**
    - Preserve the MLB entry point.
    - Make run identity sport-aware.
    - Add offline NFL Moneyline parser/persistence tests before any live call.

### Exact recommended first implementation task

Approve one historical provider, add a small offline fixture corpus, and
implement the canonical NFL team identity slice end-to-end: pure team/source
records, the three additive team tables, a 32-franchise seed, an idempotent
provider-ID repository, and tests. This is the smallest task that removes the
highest-risk dependency for every later game, result, statistics, and odds
workflow while leaving MLB behavior untouched.
