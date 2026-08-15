# nflverse Phase 1 Source Contract

## Decision and boundary

nflverse is the approved historical provider for the SportsModel NFL MVP
Phase 1 foundation. The approved baseline history is 2018-2025 regular season
and postseason. Preseason may be retained when present but is excluded from the
baseline population by default.

This decision does not select nflverse as the future live production provider.
Live freshness, correction timing, operational support, and service guarantees
require a separate decision.

`nflreadpy` is an access adapter, not a domain dependency. Its Polars
DataFrames must be converted at the boundary into SportsModel-owned immutable
records. Parser inputs in this slice are ordinary mappings so CSV readers,
Parquet readers, nflreadpy, or offline fixtures can supply the same contract.

## Sources inspected

Static release assets were retrieved on 2026-08-13. No live sports API was
called.

| Dataset | nflreadpy-compatible source | Inspected asset | SHA-256 |
|---|---|---|---|
| Schedules | `nflreadpy.load_schedules()` | `nflverse-data/releases/download/schedules/games.csv` | `0ec820632c4b5c67921179011a8afdd05e8480065aa058b0f7b6040e1fb2779c` |
| Teams | `nflreadpy.load_teams()` | `nflverse-data/releases/download/teams/teams_colors_logos.csv` | `4eab559fcf89cb4eaf61cb63a88abc47b01b6c9049187c59f3efe95888c3d048` |
| Weekly team statistics | `nflreadpy.load_team_stats(seasons=2025, summary_level="week")` | `nflverse-data/releases/download/stats_team/stats_team_week_2025.csv` | `91058a59d894855377b2f39f40c4e7bdbeef96d12144289dc68215209a1c93cb` |

The schedules asset contained 7,548 rows covering seasons 1999-2026 at
inspection time. The teams asset contained 36 alias rows representing 32
distinct numeric `team_id` values. The 2025 weekly team-stat asset contained
570 team rows, 285 game IDs, and 138 columns.

Official project references:

- <https://github.com/nflverse/nflverse-data/releases/tag/schedules>
- <https://github.com/nflverse/nflverse-data/releases/tag/teams>
- <https://github.com/nflverse/nflverse-data/releases/tag/stats_team>
- <https://nflreadpy.nflverse.com/api/load_functions/>
- <https://nflreadr.nflverse.com/articles/dictionary_schedules.html>
- <https://nflreadr.nflverse.com/articles/dictionary_team_stats.html>

The fixture is a selected-column representation, not a replacement or mirror
of the upstream datasets. nflverse data and accompanying licenses/attribution
requirements remain upstream concerns that must be reviewed before broader
distribution.

## Schedule contract

### Fields consumed by Phase 1

| Source field | Observed source type | SportsModel meaning | Requirement | Normalization | Coverage/caveat |
|---|---|---|---|---|---|
| `game_id` | string | Provider game identity | Required | Trim; preserve exactly as `external_game_id` | nflverse ID is constructed from season/week/teams; other provider IDs also exist in the row. |
| `season` | integer | NFL season starting year | Required | Strict non-negative integer; Phase 1 accepts 2018-2025 history and fixtures may include current scheduled rows | Postseason games played in the following calendar year retain the prior NFL season. |
| `game_type` | string code | Season/round classification | Required | `REG` to regular; `PRE` to preseason if encountered; `WC`, `DIV`, `CON`, `SB` to postseason with explicit round label | Inspected 2018-2025 rows contained `REG`, `WC`, `DIV`, `CON`, and `SB`; no preseason rows were present. |
| `week` | integer | nflverse week number | Required | Positive integer | Postseason uses continued numeric weeks; display meaning comes from `game_type`. |
| `gameday` | ISO date string | Scheduled local date | Required | Parse ISO date | Contains the currently published date, not an original-schedule audit trail. |
| `gametime` | `HH:MM` string | Scheduled local kickoff time | Required | Parse and attach `America/New_York`, preserving DST, then expose timezone-aware datetime | Source fields are not offset-stamped. The 13:00/20:20 convention is US Eastern; adapter code must own this explicit assumption. |
| `home_team` | string abbreviation | Home/source team alias | Required | Resolve through parsed team alias index to external team ID | Unknown abbreviation is rejected; no name guessing. |
| `away_team` | string abbreviation | Away/source team alias | Required | Resolve through parsed team alias index to external team ID | Same boundary as home. |
| `home_score` | nullable integer | Final home score | Conditionally required | Both scores present means final; blank/null means unplayed | Source does not supply a lifecycle status. |
| `away_score` | nullable integer | Final away score | Conditionally required | Must be present or absent with home score | One-sided score is malformed. Ties remain valid NFL final results. |
| `overtime` | nullable 0/1 integer | Whether final required overtime | Required for final | `0`/`1` to `False`/`True`; absent for unplayed | Does not express overtime periods. |
| `location` | string | Home-designated versus neutral site | Required | `Home` to false, `Neutral` to true | Provider home/away orientation is preserved at neutral sites. |

### Schedule fields retained for later review

The inspected schedule schema also includes:

- display/time context: `weekday`;
- derived result fields: `result`, `total`;
- alternate game IDs: `old_game_id`, `gsis`, `nfl_detail_id`, `pfr`, `pff`,
  `espn`, `ftn`;
- rest: `away_rest`, `home_rest`;
- market data: `away_moneyline`, `home_moneyline`, `spread_line`,
  `away_spread_odds`, `home_spread_odds`, `total_line`, `under_odds`,
  `over_odds`;
- context: `div_game`, `roof`, `surface`, `temp`, `wind`;
- quarterback/coaching: `away_qb_id`, `home_qb_id`, `away_qb_name`,
  `home_qb_name`, `away_coach`, `home_coach`;
- officiating/venue: `referee`, `stadium_id`, `stadium`.

These are intentionally outside the Phase 1 provider-neutral game record.
Betting lines must later enter through the odds snapshot architecture rather
than becoming historical game truth. Quarterback and weather fields need a
point-in-time availability decision before feature use.

### Status and reschedule limitation

The schedule release does not expose an authoritative status, original
scheduled date, postponement flag, cancellation flag, or source update
timestamp. The parser therefore uses only two truthful states:

- `final`: both scores and a valid overtime flag are present;
- `unplayed`: both scores are absent.

It does not claim that an unplayed row is specifically scheduled, postponed,
or cancelled. The fixture includes `2020_12_BAL_PIT`, whose final published row
has a Wednesday date after a real reschedule, but the row itself has no marker
or original date. SportsModel cannot reconstruct that history from this asset
alone. A future live/correction source must address lifecycle and schedule
history.

## Team contract

| Source field | Observed source type | SportsModel meaning | Requirement | Normalization | Coverage/caveat |
|---|---|---|---|---|---|
| `team_id` | zero-padded numeric string | nflverse franchise/source identity | Required | Preserve as string including leading zeroes | Stable across inspected aliases: OAK/LV share `2520`; LA/LAR/STL share `2510`; SD/LAC share `4400`. It is still provider-owned, not the SportsModel franchise key. |
| `team_abbr` | string | nflverse alias used by schedules/stats | Required | Trim and preserve | Multiple aliases may map to one `team_id`. |
| `team_name` | string | Alias display name | Required | Trim and preserve | Current and historical aliases coexist; not canonical identity. |
| `team_nick` | string | Nickname | Required for fixture contract | Trim | May change with franchise naming. |
| `team_conf` | string | Current conference | Required | Validate `AFC`/`NFC` | Current descriptive dataset, not a season-effective membership source. |
| `team_division` | string | Current conference/division label | Required | Validate one of eight current divisions | Must not be projected backward without a seasonal source. |

Logo and color fields (`team_color*`, `team_logo_*`, `team_wordmark`, and league
or conference logos) are presentation data and excluded from ingestion-domain
records.

### Immutable franchise key recommendation

Use a project-issued UUID, serialized as `nfl_franchise_<uuid>`. Assign it once
when the canonical franchise is created. Do not derive it from nflverse
`team_id`, abbreviation, city, nickname, or current display name. Store
nflverse `team_id` and every alias in provider mapping rows. This gives a stable
SportsModel identity even if a provider changes identifiers or a franchise
relocates/renames.

Human-readable current abbreviation is mutable metadata, not a primary key.
No 32-team seed is included in this slice.

## Weekly team-stat contract

The team-stat release is generated from nflverse play-by-play aggregation. It
has one team/opponent row per game and provides extensive offensive, defensive,
special-teams, kicking, punting, return, fumble, and penalty aggregates.

### Fields accepted into the Phase 1 source record

| Source field | Observed source type | SportsModel meaning | Requirement | Normalization | Coverage/caveat |
|---|---|---|---|---|---|
| `season` | integer | NFL season | Required | Integer | Weekly files are season-specific. |
| `week` | integer | Week number | Required | Positive integer | Postseason interpretation uses `season_type`. |
| `season_type` | string | Regular/postseason population | Required | `REG` to regular, `POST` to postseason | Unlike schedules, team stats use `POST` rather than round-specific codes. |
| `game_id` | string | nflverse game identity | Required | Preserve | Present in the inspected current release even though some older documentation examples omit it. Verify across 2018-2025 before persistence design. |
| `team` | abbreviation | Subject team alias | Required | Resolve through team alias index | Unknown aliases rejected. |
| `opponent_team` | abbreviation | Opponent alias | Required | Resolve through team alias index | Does not directly say home/away. |
| `completions` | integer | Completed passes | Required | Non-negative integer | PBP-derived. |
| `attempts` | integer | Official pass attempts | Required | Non-negative integer; completions cannot exceed attempts | nflverse definition excludes sacks. |
| `passing_yards` | integer | Team passing yards | Required | Signed integer | The provider contract does not guarantee nonnegative game totals; net/team definition must be validated against desired model meaning. |
| `passing_tds` | integer | Passing touchdowns | Required | Non-negative integer | Does not equal all offensive TDs. |
| `passing_interceptions` | integer | Interceptions thrown | Required | Non-negative integer | Used as one turnover component. |
| `sacks_suffered` | integer | Sacks taken | Required | Non-negative integer | Sack yards are separately available upstream. |
| `carries` | integer | Official team rush attempts | Required | Non-negative integer | Includes scrambles and kneel-downs per nflverse dictionary. |
| `rushing_yards` | integer | Team rushing yards | Required | Signed integer | PBP-derived; the provider contract does not guarantee nonnegative game totals. |
| `rushing_tds` | integer | Rushing touchdowns | Required | Non-negative integer | Does not include receiving/return TDs. |
| `fumbles_lost_total` | integer | Total fumbles lost | Required | Non-negative integer | Selected over narrower passing/rushing-only fumble fields. |
| `penalties` | nullable integer | Team penalties | Optional/nullable evidence | Preserve missing as null; when present, require a non-negative integer | Zero is a real observed value and must not be conflated with missing evidence; verify correction behavior across seasons. |
| `penalty_yards` | nullable integer | Team penalty yards | Optional/nullable evidence | Preserve missing as null; when present, require a non-negative integer | Zero is a real observed value and must not be conflated with missing evidence; PBP-derived. |

The record deliberately does not expose Polars types, lazy frames, or
nflreadpy metadata.

### Available but deferred team-stat families

The 138-column inspected schema additionally includes:

- passing air yards, yards after catch, first downs, EPA, CPOE, conversions,
  and explosive-play thresholds;
- rushing/receiving first downs, EPA, conversions, fumbles, targets,
  receptions, air yards, and explosive-play thresholds;
- defensive tackles, tackles for loss, sacks, quarterback hits,
  interceptions, passes defended, fumbles, safeties, blocks, and touchdowns;
- return attempts/yards/touchdowns;
- detailed field-goal, extra-point, game-winning kick, and punt splits;
- detailed fumble classifications; and
- timeout and special-teams totals.

These fields are not yet the baseline persistence contract. EPA/CPOE and
defensive event semantics deserve explicit versioning and multi-season
coverage checks before use.

### Fields unavailable or unsuitable for direct use

- Final points are not present in weekly team stats; schedules remain the score
  source.
- Home/away is not present; it must be joined through schedule game identity.
- Possession time, total first downs as a single canonical value, and a simple
  total-yards field are not present in the inspected current asset.
- Defensive points/yards allowed are not direct fields; they require joining
  the opponent row or a separately defined aggregation.
- Source observation/update timestamps are not row fields.
- Team stats are derived from play-by-play and may receive later statistical
  corrections; raw asset hash/retrieval provenance must be retained.

## Parser normalization rules

1. Preserve every upstream external ID as text, including leading zeroes.
2. Parse ordinary mappings; never expose DataFrame-specific types.
3. Sort parsed collections by stable domain keys so input ordering cannot
   change output.
4. Attach `America/New_York` to schedule date/time and preserve a timezone-aware
   `datetime`; callers can convert to UTC for persistence.
5. Map schedule `REG` to regular and round codes to postseason plus a readable
   round label. Map team-stat `POST` to postseason.
6. Resolve schedule/stat abbreviations through parsed team source records.
   Reject unknown aliases rather than inserting or guessing a team.
7. Treat two scores as final, two missing scores as unplayed, and one missing
   score as malformed.
8. Preserve tied final scores; NFL regular-season ties are valid.
9. Require final overtime to be exactly `0` or `1`; leave overtime unknown for
   unplayed games.
10. Map only `Home` and `Neutral` location values. Preserve the provider's
    home/away orientation for neutral games.
11. Validate non-negative statistics and basic internal constraints such as
    completions not exceeding pass attempts.

## Fixture corpus

`tests/fixtures/nflverse/phase_1_source_rows.json` contains:

- `2023_01_DET_KC`: ordinary regular-season final;
- `2023_22_SF_KC`: postseason, neutral-site, overtime Super Bowl final;
- `2022_01_IND_HOU`: regular-season overtime tie;
- `2023_04_ATL_JAX`: neutral-site regular-season final;
- `2020_12_BAL_PIT`: final played on its rescheduled date, demonstrating that
  the source has no reschedule marker/original date;
- `2026_01_NE_SEA`: published scheduled/unplayed row with missing results;
- OAK/LV alias rows sharing nflverse `team_id=2520`; and
- two opposing team-stat rows for `2025_01_DAL_PHI`.

Each case records source, season, game ID, retrieval date at corpus level, and
transformation. Only selected source columns are retained. Empty CSV cells are
represented as JSON null; other values are unchanged.

## Persistence identity decision

The Phase 1 persistence seed maps each of the 32 distinct nflverse `team_id`
values to one project-owned UUID franchise key. The key is assigned once and
is not computed from nflverse data, abbreviation, city, or nickname.

The teams release represents relocation aliases with the same stable source
ID: STL/LA/LAR use `2510`, OAK/LV use `2520`, and SD/LAC use `4400`. Persistence
stores one `(source_name='nflverse', external_team_id)` mapping per stable ID;
the current source name is descriptive only. Alias names therefore cannot
create additional franchises. Source validity dates are omitted because the
inspected release does not provide authoritative effective dates for alias
rows. Season-specific project names remain in `nfl_team_seasons`.

The foundational production DDL for `teams`, `games`, and `sportsbooks` is
still absent from numbered migrations. Migration `022` is additive and assumes
the established shared tables; disposable tests use the documented test-only
foundation fixture rather than inventing a production bootstrap history.

## Coverage checks required before historical game persistence

Before migrations or persistence are implemented, inspect every 2018-2025
release and report:

- game counts by season and schedule game type;
- two-score completeness and partial-score anomalies;
- duplicate and malformed game IDs;
- team aliases missing from the teams release;
- exactly two team-stat rows per covered game;
- availability and type consistency of every selected team-stat field;
- correction/retrieval strategy and asset hashes; and
- preseason availability if retention remains desired.

This source contract supplies the provider boundary referenced by the
canonical game and team-game statistics persistence implementations. It does
not authorize a historical backfill or a live ingestion workflow.
