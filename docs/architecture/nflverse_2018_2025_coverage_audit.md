# nflverse 2018-2025 Historical Coverage Audit

## 1. Executive conclusion

**Recommendation: CONDITIONAL GO** for canonical historical NFL game
persistence. The nflverse schedules release is structurally complete and
compatible for the 2,227 regular-season and postseason rows it supplies:
2,227/2,227 rows parse, all IDs are present and unique, all results are
internally consistent, and all team aliases resolve to the 32 migration-022
franchises. It is not sufficient by itself as an authoritative lifecycle or
schedule-history source.

Two source-time anomalies must be resolved or quarantined before scheduled
timestamps are persisted: `2018_07_TEN_LAC` and `2018_08_PHI_JAX` contain
`gametime=21:30` at Wembley. At audit time, the then-current parser truthfully
applied its declared Eastern-time assumption and consequently produced
2018-10-22 and 2018-10-29 01:30 UTC. The NFL's published schedule says both
kicked off at 09:30 Eastern, so these are provider values that were
syntactically accepted but semantically wrong. The later persistence
implementation added exact reviewed overrides; this section preserves the
historical audit result.

The 2022 population contains 271 rather than 272 regular-season rows because
the cancelled `2022_17_BUF_CIN` event is absent. That behavior is consistent
with the NFL's cancellation notice, but proves that absence cannot be treated
as a provider-supplied cancelled status.

## 2. Data source and reproducibility

The audit used the public `nflverse/nflverse-data` static GitHub release assets
identified by the existing source contract, retrieved by HTTPS on
2026-08-15 at 00:34:37 UTC:

| Dataset | Asset | Rows | SHA-256 |
|---|---|---:|---|
| Schedules/results | `releases/download/schedules/games.csv` | 7,548 | `3f99dc4e0d16e85f23eff30f2394c56a761694f177d9701dc54f37f5103c11df` |
| Teams/aliases | `releases/download/teams/teams_colors_logos.csv` | 36 | `4eab559fcf89cb4eaf61cb63a88abc47b01b6c9049187c59f3efe95888c3d048` |

The current schedules hash differs from the 2026-08-13 hash recorded in the
source contract, while the teams hash is unchanged. This demonstrates why a
retrieval timestamp and content hash must accompany every ingestion. No raw
provider asset is committed. Reproduce with:

```powershell
python scripts/audit_nflverse_phase1_coverage.py `
  --schedules <games.csv> --teams <teams_colors_logos.csv> `
  --season-from 2018 --season-to 2025 `
  --retrieved-at <ISO-8601-UTC> --json-output <result.json>
```

The tool filters only `REG`, `WC`, `DIV`, `CON`, and `SB`; preseason is
excluded. Counts are derived from the provider rows, not encoded expectations.

## 3. Seasons and coverage matrix

| Season | Regular | Postseason | Total | Unique IDs | Duplicate IDs | Teams | Final | Unplayed | OT | Ties | Neutral |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 256 | 11 | 267 | 267 | 0 | 32 | 267 | 0 | 17 | 2 | 4 |
| 2019 | 256 | 11 | 267 | 267 | 0 | 32 | 267 | 0 | 11 | 1 | 6 |
| 2020 | 256 | 13 | 269 | 269 | 0 | 32 | 269 | 0 | 10 | 1 | 4 |
| 2021 | 272 | 13 | 285 | 285 | 0 | 32 | 285 | 0 | 22 | 1 | 4 |
| 2022 | 271 | 13 | 284 | 284 | 0 | 32 | 284 | 0 | 20 | 2 | 7 |
| 2023 | 272 | 13 | 285 | 285 | 0 | 32 | 285 | 0 | 14 | 0 | 6 |
| 2024 | 272 | 13 | 285 | 285 | 0 | 32 | 285 | 0 | 16 | 0 | 7 |
| 2025 | 272 | 13 | 285 | 285 | 0 | 32 | 285 | 0 | 16 | 1 | 8 |
| **Total** | **2,127** | **100** | **2,227** | **2,227** | **0** | **32/season** | **2,227** | **0** | **126** | **8** | **46** |

Postseason round counts are 4 WC/4 DIV/2 CON/1 SB in 2018-2019 and 6/4/2/1
from 2020 onward. The missing 2022 regular-season event is not a duplicate or
malformed row: nflverse has no `2022_17_BUF_CIN` row. The NFL states that the
game was cancelled and would not be resumed.

## 4. Required-field and result integrity

Every in-scope row was checked for external game ID, season, game type, week,
date, time, both team abbreviations, both scores, overtime, and location.
There were no null/blank required fields, malformed values, partial scores,
negative scores, identical team pairings, tie-without-overtime states,
postseason ties, or unsupported locations. All 2,227 rows are finals with both
scores present; the historical slice contains no scheduled/unplayed row.

`week_label` is not a provider column. The parser deterministically derives
`Regular Season`, `Wild Card`, `Divisional`, `Conference Championship`, or
`Super Bowl` from `game_type`. That is a SportsModel transformation, not source
completeness.

The eight tied games are regular-season finals and all have `overtime=1`.
There are 126 overtime finals and 46 provider-designated neutral-site games.
No impossible result state was found.

## 5. Team/franchise identity findings

The schedules contain 33 abbreviations resolving to 32 distinct string-valued
provider IDs. All 32 IDs exactly match migration 022; no canonical seed ID is
unobserved and no schedule abbreviation is unresolved. Leading zeroes are
preserved (`0200`, `0325`, `0610`, and so on).

All alias groups in the teams release are:

| Provider ID | Aliases | Franchise result |
|---|---|---|
| `2510` | `LA`, `LAR`, `STL` | one Rams franchise; `LA` is observed in-range |
| `2520` | `LV`, `OAK` | one Raiders franchise; both are observed in-range |
| `4400` | `LAC`, `SD` | one Chargers franchise; only `LAC` is observed in-range |

`LAR`, `STL`, and `SD` occur in the alias asset but not in 2018-2025 schedule
rows. Historical aliases therefore require alias mappings, not duplicate
canonical franchises. Migration 022's one source mapping per stable provider
ID is compatible with every observed identity.

## 6. Parser compatibility at audit time

The parser at the audit commit was run one row at a time over the complete
in-scope dataset to retain rejection evidence:

| Attempted | Parsed | Rejected | Rejection rate | Categories |
|---:|---:|---:|---:|---|
| 2,227 | 2,227 | 0 | 0.000000% | none |

This proves syntactic and domain-record compatibility. It does not prove every
source value is semantically correct: the two Wembley times pass because
`21:30` is a valid clock value. They are category A, bad provider data, rather
than parser defects or contract mismatches. No category B-E rejection exists.

## 7. External game ID integrity

There are 2,227 nonblank IDs and 2,227 unique IDs. There are no duplicates
within seasons, duplicates across seasons, malformed IDs, season-prefix
mismatches, encoded-matchup mismatches, or same-ID/different-matchup cases.
Postseason IDs use the same `season_week_away_home` format as regular season.

**Decision:** `(source_name, external_game_id)` is sufficient as the nflverse
provider identity, provided the raw observation and asset hash are retained.
The ID is provider-owned and should not be recomputed when schedules change.

## 8. Temporal and timezone findings

Applying `America/New_York` yields 966 starts at UTC-04:00 and 1,261 at
UTC-05:00. Both DST offsets occur sensibly across early/late regular season
and postseason. There are 455 expected UTC calendar-date rollovers for evening
Eastern kickoffs. International 09:30 rows and Super Bowls otherwise convert
sensibly, and neutral designation does not change provider home/away identity.

The two exceptions are:

| Game ID | Source date/time | Parser UTC | Evidence |
|---|---|---|---|
| `2018_07_TEN_LAC` | 2018-10-21 21:30 ET | 2018-10-22 01:30Z | NFL published 09:30 ET |
| `2018_08_PHI_JAX` | 2018-10-28 21:30 ET | 2018-10-29 01:30Z | NFL published 09:30 ET |

The source contains no timezone or UTC-offset column. Do not silently replace
these values. Quarantine them or apply a separately reviewed, provenance-backed
override during persistence.

## 9. Lifecycle and rescheduling limitations

### What the provider supplies

- one current `gameday` and `gametime` per included row;
- scores and overtime for completed games;
- venue/stadium context and alternate provider IDs; and
- fully blank result fields on the 272-row 2026 future schedule sample.

### What SportsModel would have to infer or obtain elsewhere

- lifecycle/status (the release has no status field);
- whether blank scores mean scheduled, postponed, cancelled, or suspended;
- original scheduled date/time and reschedule history;
- a row-level update timestamp or correction sequence;
- timezone/offset metadata; and
- cancelled events omitted from the asset.

The final published `2020_12_BAL_PIT` row contains its Wednesday date but no
original date or reschedule marker. Neutral designation also includes true
international games, Super Bowls, and temporary domestic venue moves, so it is
not a lifecycle signal. SportsModel must not invent these states.

## 10. Known limitations and blockers

1. Resolve or quarantine the two confirmed 2018 Wembley time anomalies.
2. Do not claim exhaustive scheduled/cancelled coverage from a results-oriented
   historical release; the cancelled 2022 Bills-Bengals game is absent.
3. nflverse supplies no original schedule, lifecycle, source-update timestamp,
   or timezone metadata.
4. Static assets can change at the same release URL, as the changed schedules
   hash demonstrates. Persist retrieval time, hash, and raw evidence.
5. The data supports historical canonical results, not selection of nflverse
   as a live operational provider.

## 11. Exact persistence-layer transformations

1. Filter to `REG`, `WC`, `DIV`, `CON`, and `SB`; exclude `PRE` by default.
2. Preserve `game_id` verbatim and upsert identity by
   `(source_name='nflverse', external_game_id)`.
3. Preserve team IDs as strings; resolve schedule abbreviations through the
   full alias table, then map the stable provider ID to migration 022.
4. Map `REG` to regular; map `WC`/`DIV`/`CON`/`SB` to postseason and derive the
   reviewed week label without overwriting provider fields.
5. Require two scores or no scores; require 0/1 overtime for finals; preserve
   ties and `Home`/`Neutral` orientation exactly.
6. Attach `America/New_York` only after semantic validation. Quarantine the
   two listed Wembley rows until a reviewed override source is recorded.
7. Derive only `final` (two scores) and `unplayed` (no scores). Never derive
   postponed/cancelled from absence or blank scores.
8. Store asset URL, retrieval timestamp, SHA-256, raw row payload/hash, and
   ingestion observation time. Leave provider update time null.
9. Do not synthesize original schedule time. Set it only when a source that
   actually supplies schedule history is introduced.

## 12. 2026 future-schedule sanity check

The same release contains 272 2026 `REG` rows, all with both scores and
overtime blank. The current parser accepts this representation as `unplayed`,
so the contract plausibly supports future scheduled games structurally. It
does not distinguish schedule lifecycle states and is not by itself a live
provider approval.

## 13. Exact next development task

Implement the additive canonical NFL game persistence slice (new migration
after 022, repository, ingestion-run evidence, raw source observations, and an
idempotent nflverse adapter) using the transformations above. Include an
explicit quarantine/override mechanism for the two timestamp anomalies and
tests proving that omitted/cancelled games do not acquire invented lifecycle
states. Do not expand into live odds, scheduling, or production orchestration.

## 14. Validation

- Targeted audit/parser/team-identity tests: 23 passed.
- Full suite: 666 passed, 36 dependency deprecation warnings.
- Python compile validation (`src`, `scripts`, and `tests`): passed.
- `git diff --check`: passed (Git emitted only its Windows LF/CRLF notice for
  `.gitignore`).

The first full-suite attempt used a workspace-local `--basetemp`; 660 tests
passed and six fixtures errored after that directory disappeared during the
run. This was the known Windows pytest temp cleanup behavior, not test
assertion failure. The reported full-suite result is the clean rerun using the
unique isolated base
`C:\Users\Brian\AppData\Local\Temp\sportsmodel-nfl-audit-01a002d4`.

## 15. External corroboration

- NFL.com, “NFL announces times, dates for 2018 London games”:
  <https://www.nfl.com/news/nfl-announces-times-dates-for-2018-london-games-0ap3000000927291>
- NFL.com, “Week 17 Buffalo-Cincinnati game will not be resumed”:
  <https://www.nfl.com/news/week-17-buffalo-cincinnati-game-will-not-be-resumed-neutral-afc-championship-gam>
