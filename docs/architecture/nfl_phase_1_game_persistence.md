# NFL Phase 1 Canonical Game Persistence

Migration 023 implements the smallest additive game slice approved by the NFL
foundation. Shared `games.game_id` remains the cross-provider and future odds
join key. Football lifecycle and results live only in the one-to-one
`nfl_games` extension; existing MLB columns and rows are unchanged.

## Identity and writes

The immutable nflverse identity is `(source_name, external_game_id)` in the
existing `game_sources` table. The adapter preserves nflverse `game_id`
verbatim. A new identity inserts `games`, `nfl_games`, and `game_sources` in
the caller's transaction. A known identity may update schedule/result fields
only when its canonical home and away team IDs still match. A changed matchup
raises an error rather than remapping the provider identity. Teams are resolved
by nflverse abbreviation to stable nflverse team ID at the adapter boundary,
then through `nfl_team_sources`; no team is created or matched by display name.

Canonical reads by `games.game_id` or season use only `games` plus
`nfl_games`, and return the provider-independent internal team IDs. They never
join `game_sources`, so attaching additional provider mappings cannot duplicate
or change a canonical read. Provider resolution is a separate explicit lookup
by `(source_name, external_game_id)` and returns the provider-facing record.

## Runs and evidence

Every adapter invocation creates `nfl_ingestion_runs` provenance containing
the asset identity, retrieval time, asset SHA-256, status, and row counts.
Every accepted row retains deterministic JSON, its SHA-256, transformation
fields, and the run association in `nfl_game_source_observations`. nflverse has
no claimed provider update timestamp, so that column remains null. A rerun of
the same bytes creates a new run and a new observation for that run, while the
canonical game and `game_sources` identity are updated in place. Within one run
byte-identical evidence is unique.

The public adapter owns transaction boundaries. It commits the ingestion-run
row before processing, then writes all canonical games and observations in one
atomic transaction. On any non-quarantine processing error it rolls that
transaction back, marks the durable run `failed` with the original error in a
fresh transaction, commits that evidence, and re-raises the original error.
Consequently no partial canonical game or observation survives a failed run,
and a PostgreSQL aborted transaction cannot mask the provider error.

## Results and absent events

Only two statuses exist in this slice: two valid scores produce `final`; both
scores absent produce `unplayed`. Partial scores fail. Final postseason ties
fail; regular-season ties remain valid. Unplayed rows have no overtime value,
while final rows require nflverse's explicit overtime flag. Input omission has
no delete or synthesis behavior: in particular, the absent 2022 BUF-CIN event
does not create a cancelled, postponed, or synthetic game.

The default bounded import is seasons 2018 through 2025, regular season and
postseason only. Callers may change the bounds and explicitly include
preseason. This structurally permits 2026 scheduled rows without adding a
production scheduler or downloader.

## Timestamp anomalies

`gameday + gametime` is validated and interpreted as `America/New_York`.
There is no neutral-site or late-clock correction heuristic. The reviewed
registry contains only `2018_07_TEN_LAC` and `2018_08_PHI_JAX`, and requires
their exact provider date and `21:30` value before applying the reviewed
`09:30` Eastern correction. An unexpected date or time for either registered
identity is not corrected and receives no canonical write. Instead, its raw
payload/hash is retained with `game_id = NULL`, `anomaly_state = quarantined`,
an explicit mismatch reason, and the reviewed audit plus official NFL source
reference. This exact-evidence quarantine is row-local, so the run continues
with other valid rows and increments `rows_quarantined`. Any other malformed
provider row fails the atomic run. Normal reviewed observations preserve the
original `21:30` raw JSON and mark the canonical correction as `overridden`.
