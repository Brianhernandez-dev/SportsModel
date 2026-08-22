# NFL Phase 4 — Market Layer and Paper Validation Architecture Audit

Status: Phase 4A1 through Phase 4A4 implemented; Phase 4A remains incomplete

Audit baseline for Phase 4A4: `main` at
`a20255a6e684e3e1b5aa4c31a5ac78176f1bde06`

## 1. Scope and governing constraints

Phase 3 is the immutable upstream evidence system. Phase 4 must consume its
completed predictions without changing the mature artifact
`nfl_moneyline_frozen_0.1.0`, the early artifact
`nfl_moneyline_early_frozen_0.1.0`, either feature schema, routing contract
`nfl_moneyline_routing_0.1.0`, or forward protocol
`nfl_moneyline_forward_0.1.0`. Partial 2026 results are forward evidence only;
they must not drive retraining, recalibration, model selection, qualification
threshold tuning, or retrospective replacement of an official observation.

This audit inspected migrations 001–026, the foundational test schema, the MLB
Odds API ingestion path, shared market analytics, MLB Moneyline evaluation and
paper workflows, and the NFL Phase 3 loaders, routing, inference, prediction
service, persistence, and forward evaluation. No live provider was called and
no production data or migration was changed.

The architectural preference is the smallest additive boundary:

1. Keep Phase 3 tables and code unchanged.
2. Keep raw sportsbook observations shared across sports after repairing sport
   isolation and provenance.
3. Add NFL-specific evaluation, qualification, paper-bet, settlement, and CLV
   evidence rather than widening MLB-specific production tables.
4. Reuse pure calculations only after the caller has constructed a sport-safe,
   complete, strictly pregame input set.

### Phase 4A1 implementation record — 2026-08-20

The first sport-isolation slice is implemented without a live NFL endpoint or
NFL persistence path:

- migration 027 replaces scheduled-run uniqueness on
  `(target_date, snapshot_role)` with
  `(sport, target_date, snapshot_role)` for the same running/completed scheduled
  roles; failed and manual runs retain their previous repeatable semantics;
- every existing MLB date/role odds-run selector is explicitly scoped to the
  canonical `baseball_mlb` provider sport key;
- a strict, transport-independent parser supports only `baseball_mlb` and
  `americanfootball_nfl` H2H payloads and preserves event, sport, commence time,
  team names, bookmaker key/title/update time, market key/update time, outcome,
  American price, and optional point;
- the existing MLB HTTP path consumes the parsed DTOs for valid provider
  responses, while no NFL request, canonical mapping, or persistence command is
  exposed; and
- final Phase 4A1 validation on committed main passed with disposable PostgreSQL
  integration enabled: 963 passed, 0 failed, 0 skipped.

The following intentionally unscoped paths were found and deferred because they
select already-linked rows by exact IDs rather than discovering scheduled runs
by date/role: MLB market-evaluation status validation, pipeline audit/status
lookups, and live-dashboard joins. The legacy global `analysis.market` scan is
also unchanged. Cross-sport run/game consistency, direct-ID sport validation,
and sport-safe derived-analysis boundaries belong to the next provenance and
identity hardening slice; they must be resolved before official NFL evidence.

At the close of Phase 4A1, strong source provenance, stable sportsbook identity,
normalized NFL selection identity, strict canonical NFL event/game matching, and
database-level kickoff/pregame protection remained open. Phase 4A2 addresses the
first two for new observations; the NFL identity and timing boundaries remain.

### Phase 4A2 implementation record — 2026-08-21

Phase 4A2 hardens the shared odds source graph offline. Migration 028 is
additive and does not backfill or rewrite historical evidence.

Before Phase 4A2, a stored quote could identify its ingestion run, the run's
declared sport/source/role/date and lifecycle/quota metadata, a canonical shared
game, a sportsbook display-name row, the market/selection/price/line, and one
application capture time. It could not recover the Odds API bookmaker key,
provider sport/event identity on the observation, provider commence/team facts,
provider book/market update times, exact secret-free request context, or a
database response-receipt time. Display title was sportsbook identity, and the
source graph had no protection against later updates.

For new provenance-bearing captures, Phase 4A2 now guarantees:

- `odds_ingestion_runs` retains the provider source and sport plus the
  secret-free request path, regions, markets, odds format, optional commence
  window, a database `request_started_at`, the existing HTTP/quota metadata,
  and a database `response_received_at`. The API key and full query string are
  never persisted.
- `sportsbook_provider_identities` immutably maps
  `(provider_name, provider_bookmaker_key)` to one existing shared
  `sportsbooks` row. The Odds API bookmaker key is identity; title is not. A
  later title/branding observation returns the same identity and does not rename
  or duplicate the sportsbook. One sportsbook cannot acquire two keys from the
  same provider, and one provider key cannot point to two sportsbooks.
- `odds_provider_event_observations` immutably retains one provider event per
  ingestion run: provider source, provider sport key, external event ID,
  commence time, provider home/away names, and the exact response observation
  time. Its composite foreign key requires source, sport, and observation time
  to equal the parent run.
- New `odds_market_snapshots` link to the exact run/event observation and
  provider sportsbook identity. They retain bookmaker title at observation,
  optional bookmaker and market update timestamps, and SportsModel
  `observed_at`. Composite foreign keys prove the event belongs to the same run
  and the provider identity belongs to the same sportsbook/source.
- A partial unique quote contract permits only one selection for the same
  run/event/provider-book/market/selection tuple. An exact event replay in one
  run is accepted only when all retained facts match; conflicting replays fail
  closed.
- Provider identity and event rows are immutable. Provenance-bearing quote rows
  cannot be updated, deleted, or retrofitted onto historical rows. Request
  identity is immutable once a new run is reserved; response metadata is set
  once; and a terminal provenance-bearing run cannot be changed or deleted.

Existing MLB rows remain valid with all Phase 4A2 columns null. Their unknown
provider event IDs, bookmaker keys, provider update timestamps, request context,
and response receipt times remain honestly unknown. When a future valid MLB
capture first observes a provider key with an exact existing sportsbook title,
the immutable mapping attaches to that existing sportsbook ID without changing
historical snapshot references. No retroactive provenance is synthesized.

No raw response body or payload hash is retained in Phase 4A2. The retained
normalized facts and database relationships support attribution and mutation
resistance, but do not prove provider authenticity or permit byte-for-byte raw
response replay. No hash is claimed to provide such proof.

Phase 4A3 owns canonical NFL identity. Phase 4A2 deliberately did not map an
Odds API NFL event to `nfl_games`, resolve NFL team names, add canonical NFL
selection team IDs, determine pregame/official eligibility, or expose an NFL
network/persistence command. Phase 4A3 implements the strict existing-only team
and game resolution, kickoff-drift handling, provider-event mapping policy, and
database run/event/game/selection consistency described below.

Remaining risks include historical MLB provenance gaps, mutable legacy quotes,
the existing MLB create-on-miss canonical game behavior, quote-level canonical
selection IDs, no database kickoff cutoff, and no immutable official NFL
snapshot/evaluation/paper evidence. Phase 4A therefore remains incomplete.

### Phase 4A3 implementation record — 2026-08-21

The existing NFL identity architecture was extended rather than duplicated.
`nfl_team_profiles` remains the canonical current-franchise identity,
`nfl_team_seasons` remains the season display/abbreviation record, and
`nfl_team_sources` remains the exact external-team mapping. Migration 029 adds
one immutable `odds_api` source identity for each of the 32 active canonical
teams. The Odds API's full current team name is both the exact external ID and
retained provider name. Matching is case-sensitive and exact: there is no
normalization, substring lookup, fuzzy matching, fallback abbreviation, or
team creation. Missing, duplicate, inactive, or same-team resolutions fail
closed.

The canonical game resolver accepts only a parsed `americanfootball_nfl` H2H
event. It resolves both provider team names first, verifies every included H2H
market contains those two names exactly once regardless of outcome order, and
queries only existing `nfl_games`. A match requires exact canonical home/away
orientation, `unplayed` status, and a provider commence time within 15 minutes
of `nfl_games.scheduled_start_time`. The 15-minute maximum is the established
repository game-match boundary already used by the MLB canonical matcher; A3
does not broaden it. Zero matches, more than one accepted match, reversed
orientation, a final game, or drift greater than 900 seconds fails closed.
The result exposes the signed drift and labels zero as `exact` and any accepted
nonzero drift as `acceptable_drift`. It returns the current canonical kickoff
and separately retains the provider commence time; provider data never updates
the canonical schedule.

Migration 029 adds `nfl_odds_provider_event_mappings` for the narrow immutable
contract `(provider_name, provider_sport_key, external_event_id) -> nfl_game`.
The row retains oriented canonical team IDs, exact provider names, canonical
kickoff at first mapping, first provider commence time, and signed initial
drift. Foreign keys prove the target is an NFL game and that its shared-game
home/away IDs agree. The provider sport is fixed to `americanfootball_nfl`, and
initial drift is constrained to 900 seconds. One provider event ID cannot move
to a different game or team identity. Exact reprocessing is idempotent.
Different provider event IDs may map to the same canonical NFL game so a
provider reissue is retained as another immutable identity instead of
overwriting or being forced through generic `game_sources`, whose one-source-ID
per-game rule has different MLB-oriented cardinality.

`odds_provider_event_observations` gains an optional mapping link. A composite
foreign key requires the link's provider, sport, event ID, and provider
home/away names to equal the observed event. The existing Phase 4A2 composite
foreign key independently requires the observation sport/source/time to equal
its ingestion run. Consequently an NFL event cannot attach to an MLB run, an
NFL mapping cannot target a shared MLB-only game, and reversed or copied team
IDs cannot be persisted. Existing observations remain null and are not
rewritten; MLB creation and matching behavior is unchanged.

Canonical selections are returned as a fixed home/away pair containing the
exact provider selection name, canonical team ID, and side. Provider outcome
ordering is irrelevant. A missing market, third or unknown outcome, duplicate
home selection, or duplicate away selection is rejected. A3 deliberately does
not persist quote-level canonical selection IDs yet because official evidence
qualification and its immutable snapshot contract belong to Phase 4A4.

Phase 4A3 remains fully offline: it adds no NFL transport, CLI, scheduler, live
capture path, no-vig/EV calculation, candidate creation, or paper evidence.
Validation with the guarded tests enabled against the disposable local
PostgreSQL container completed with 1007 passed, 0 failed, and 0 skipped.
Phase 4A4 must define and enforce the official pregame boundary using canonical
kickoff and SportsModel observation/response time, with provider timestamps as
provenance only. It must add immutable official snapshot evidence and reject
equality with or observation after kickoff at both service and database
boundaries. Phase 4A is not complete until that boundary exists.

### Phase 4A4 implementation record — 2026-08-21

Migration 030 and the official-pregame evidence service establish the first
explicit official NFL quote boundary. Raw odds observations remain raw by
default. A caller must deliberately qualify one exact provenance-bearing quote
snapshot; qualifying a newer quote creates a new row and never changes an
earlier decision.

The timestamp meanings are intentionally distinct:

1. `odds_ingestion_runs.request_started_at` is the database clock recorded when
   SportsModel reserves and begins the provider request.
2. `odds_ingestion_runs.response_received_at` is the database clock recorded
   when SportsModel receives the provider response. This is the trusted
   possession and observation time.
3. `odds_provider_event_observations.observed_at`,
   `odds_market_snapshots.observed_at`, and the provenance-bearing snapshot's
   `snapshot_time` are constrained to that same response-receipt time.
4. `provider_commence_time` is the provider's event time and remains provenance.
5. `bookmaker_updated_at` is the bookmaker-level provider update time and
   remains provenance.
6. `market_updated_at` is the market-level provider update time and remains
   provenance.
7. `nfl_games.scheduled_start_time` is the current canonical NFL kickoff and is
   authoritative for pregame eligibility.

The exact official rule is:

```text
trusted SportsModel observed_at < current canonical NFL kickoff
```

Equality is live, not pregame, and is rejected. Any later observation is also
rejected. An earlier provider bookmaker or market update, or a later provider
commence time, cannot make a late SportsModel observation eligible. Provider
timestamps never override either the trusted observation clock or canonical
kickoff.

`nfl_official_pregame_evidence` references one exact raw snapshot, its event
observation, immutable Phase 4A3 mapping, ingestion run, sportsbook provider
identity, existing NFL game, and canonical selection team. The insert trigger
requires a completed Odds API NFL provenance run, exact response/event/snapshot
observation-time equality, exact game linkage, current canonical home/away
orientation, an H2H provider selection matching one mapped team, and the
strictly pre-kickoff observation. It copies the American price, optional line,
provider selection text, trusted observation time, provider commence/book/market
timestamps, and current canonical kickoff used for qualification. The canonical
team ID, not provider text, is authoritative downstream.

Official evidence rows reject update and delete. Their referenced Phase 4A2 and
Phase 4A3 source rows are already immutable and all evidence foreign keys use
`ON DELETE RESTRICT`. Reprocessing the same snapshot and selection is
idempotent; attempting to bind that snapshot to another canonical selection
fails closed. A different later pregame snapshot produces a distinct evidence
row.

Eligibility is evaluated against the current `nfl_games` kickoff while the
canonical row is locked against concurrent schedule updates. The kickoff used
for that decision is copied to
`canonical_kickoff_at_qualification`. If the canonical schedule changes before
qualification, the new kickoff controls. If it changes afterward, the immutable
historical evidence and its retained qualification kickoff are not silently
reclassified or rewritten. Provider odds data never changes `nfl_games`.

Service and database boundaries reject missing raw provenance, missing event
mapping, MLB or other sport/source identity, incomplete runs, incompatible
run/event/book/game links, unknown or third selections, selection/team mismatch,
naive timestamps, and observations at or after kickoff. No probability,
no-vig, edge, EV, evaluation, paper bet, settlement, or CLV is created.

Final validation with guarded tests enabled against the disposable local
PostgreSQL container completed with 1037 passed, 0 failed, and 0 skipped.

Phase 4A5 owns the first controlled live NFL capture. Before it runs, the
operator must use an explicitly approved nonproduction rehearsal, verify the
request window and API quota, confirm the intended canonical games and mappings,
exercise duplicate-request protection, and prove that returned raw quotes can
be qualified only through this strict boundary. Phase 4A remains incomplete
until that controlled live path and its evidence audit are validated.

## 2. Current-state repository audit

### 2.1 Schema through migration 026

The foundational schema has shared `teams`, `games`, and `sportsbooks` tables.
`games` has a timestamp and home/away team IDs but no sport discriminator.
`sportsbooks` identifies a book only by unique display `name`.

Migrations 001–004 add MLB and Odds API identifiers and the generic
`game_sources` mapping. The mapping guarantees one canonical game per
`(source_name, external_game_id)` and, since migration 012, at most one external
ID from a given `source_name` per canonical game. The latter is useful for MLB
doubleheader protection but cannot represent a provider reissuing an NFL event
ID for the same canonical game.

Migrations 005–007 establish the shared odds foundation:

- `odds_market_snapshots` stores canonical game, sportsbook, market type,
  selection display name, optional line, American price, `snapshot_time`,
  source name, and ingestion-run ID.
- `odds_ingestion_runs` stores `sport`, source, lifecycle timestamps/status,
  counts, and errors.
- `market_analysis` is a mutable derived row per snapshot.

Migration 008 makes `games.game_date` timezone-aware. Migrations 018, 020, and
021 add MLB-oriented snapshot roles and quota metadata. A running or completed
scheduled run is unique on only `(target_date, snapshot_role)`. The `sport`
column is not in that index. Therefore an MLB and NFL capture for the same date
and role cannot safely coexist. The role check also admits only the current
MLB-derived vocabulary plus `legacy` and `manual`.

Migrations 014–017, 019, and 025 are MLB Moneyline production persistence:
prediction runs and games, market evaluations, paper-candidate settlements,
and daily workflow runs. They include baseball starter identity and coverage,
MLB run semantics, and links to `historical_games`. They are not generic
Moneyline tables despite some unqualified names.

Migrations 022–024 create NFL-specific identity, game, result, team-statistic,
and raw source-observation layers. NFL teams are canonical `teams` rows extended
by `nfl_team_profiles`, season identity, and `nfl_team_sources`. The only seeded
NFL provider identity is currently `nflverse`. NFL games extend shared `games`
through `nfl_games`; raw nflverse game/stat observations retain payloads and
SHA-256 hashes.

Migration 026 is substantially stronger than the odds and MLB paper schemas.
It creates NFL-specific run and prediction rows with committed artifact,
protocol, routing, slate, feature, source-trace, and probability identities.
It enforces 2026+, official uniqueness per game/protocol, exact parent/child
identity, canonical target identity, strict pre-kickoff creation, one-way run
lifecycle, completed count coherence, and update/delete rejection. Its foreign
keys use `ON DELETE RESTRICT`. This is the standard Phase 4 evidence should
follow; Phase 4 must not weaken or modify it.

### 2.2 MLB Odds API ingestion

`sportsmodel.ingest.odds_api` combines request construction, HTTP execution,
response parsing, canonical identity mutation, and persistence in one MLB-only
module. It hard-codes `baseball_mlb`, `h2h`, US regions, American odds, Pacific
calendar-day windows, and the MLB snapshot-role set. A scheduled run is reserved
and committed before the request, so duplicates avoid spending a credit. On
success, selections and run completion are committed together; on failure,
selection writes roll back and the reserved run is marked failed with quota and
error details.

One UTC `snapshot_time` is assigned after the full response is decoded and is
used for every outcome in the response. Events are admitted only when the Odds
API `commence_time` is within the requested Pacific day and is strictly later
than that local capture timestamp. This is a useful application guard, but it
trusts the provider event time rather than the canonical game time and has no
database equivalent.

Team resolution calls `normalize_team_name`, whose alias map is baseball-only,
then inserts a missing shared `teams` row. Sportsbooks are similarly found or
created by provider display title, even though the provider response has a
stable bookmaker key that is not persisted. Game matching first uses
`game_sources`, then matches exact team orientation within 15 minutes, and
otherwise creates a new shared `games` row. That create-on-miss behavior is
appropriate for the present MLB ingestion history but is unacceptable for NFL
odds: canonical NFL schedule and team entities already exist and an odds feed
must not manufacture substitutes.

Raw request parameters, provider response payload, response hash, Odds API
sport/event/bookmaker keys, bookmaker/market `last_update`, and provider outcome
payload are not retained. The module also contains unreachable residue of an
older game-resolution implementation after `get_sportsbook_id`; it is not used
by the active path but argues for separating the adapter before adding a sport.

The auxiliary CLI and PowerShell scheduling wrappers are explicitly MLB and
encode MLB role/date behavior. They must remain unchanged during NFL Phase 4.

### 2.3 Pure market analytics

The following calculations are deterministic and have no baseball dependency:

- American price to implied probability and decimal odds;
- normalization of a complete market to no-vig probabilities;
- complete-market construction for two-outcome `h2h` markets;
- cross-sportsbook consensus as the mean of book-level no-vig probabilities;
- best offered price by decimal return;
- line movement and same-contract price CLV calculations.

Their important precondition is not encoded in their types: inputs must already
belong to one sport, one canonical event, one capture instant, and a valid
pregame interval. `MarketSnapshot` carries neither sport/run provenance nor a
canonical selection team ID. Pure builders group by game/book/market/time and
will process live or postgame data if a caller supplies it.

`analysis.expected_value.calculate_expected_value_markets` computes
**market-relative EV**, not model EV. For each target book it creates a
leave-one-out no-vig consensus from at least two other books and calculates:

`reference_consensus_probability * offered_decimal_odds - 1`.

By contrast, `analysis.moneyline_model_value.evaluate_moneyline_model_value`
computes **model EV** at the best stored price:

`frozen_model_probability * offered_decimal_odds - 1`.

It also computes model-minus-consensus market edge and model-minus-offered-price
implied-probability edge. These concepts must remain separately named and
persisted. The generic expected-value module must not be presented as NFL model
value.

The legacy `analysis.market.analyze_markets` scans all sports' snapshots without
a sport or pregame filter and calculates a different cross-book aggregate. It
is not an official Phase 4 evaluation path.

### 2.4 MLB Moneyline production layers

The MLB market evaluation service loads one completed MLB prediction run and
one completed odds run, builds complete book markets and consensus, chooses the
best price for the predicted team, applies policy `1.0.0`, and upserts a combined
evaluation/qualification row. It protects its normal service path by requiring
`snapshot_time >= prediction_time` and `snapshot_time < game_start_time` in
Python. The snapshot query itself has no time or odds-run sport predicate, and
the database does not enforce that the evaluation's copied run, snapshot,
sportsbook, price, selection, and time all describe the same source row.

The qualification policy is explicitly baseball-specific: starter match,
starter coverage, starter feature availability, minimum model EV, minimum
model-market edge, and sportsbook count. A qualified paper candidate is not a
separate immutable bet; it is the mutable boolean state of an upserted evaluation
row. Re-evaluation can therefore replace qualification evidence.

Settlement loads qualified evaluations, joins final MLB results through
`historical_games`, calculates flat one-unit profit, and upserts one settlement
per evaluation. Score, outcome, profit, and `settled_at` can be changed by a
rerun. The current behavior is operationally useful for MLB score corrections,
but it is not an append-only evidence design.

Early-entry, cohort comparison, movement/CLV, dashboard, audit, and daily
orchestration modules are all coupled to MLB prediction tables, roles, target
dates, result ingestion, and/or starters. Several role lookup queries use only
`target_date`, role, and status, with no `sport = 'baseball_mlb'` predicate.
Today the cross-sport uniqueness index masks part of that ambiguity; after
sport-safe coexistence those queries must be explicitly pinned to MLB before
NFL scheduled roles exist.

The role-aware MLB movement service loads snapshots without joining the game
start or filtering `snapshot_time`. Its pure CLV layer treats the final complete
market in a supplied timeline as the close. A post-start capture in a selected
run could therefore become the derived close. The generic repository is safer
by default (`snapshot_time < games.game_date`) but exposes `include_live=True`
and compares to the mutable shared game timestamp, not immutable NFL prediction
evidence.

### 2.5 NFL Phase 3 components

The fit-free artifact loader validates exact JSON fields, ordered feature names,
training seasons, preprocessing parameters, specification and model
fingerprints, and committed artifact identity. Inference selects `early` unless
both teams have at least three current-season prior games; otherwise it selects
`mature`. Feature history is strictly before target kickoff, and source traces
and feature vectors are hashed.

The prediction service uses an explicit UTC half-open slate and the database
clock. A persisted run reserves a UUID request identity, then performs target
selection, feature reads, inference, child inserts, and completion in one
`REPEATABLE READ` transaction. Official duplication, late prediction, partial
slates, artifact drift, route drift, canonical identity drift, and mutation are
rejected by service and/or database. The completed prediction row already
contains exactly what Phase 4 needs: immutable game/team/kickoff identity,
selected route and frozen model identity, creation time, and the canonical
home-win probability.

The forward evaluation layer reads official evidence and canonical NFL final
scores to report probability metrics. It does not contain odds or paper logic
and should remain independent. Market and paper performance are additional
Phase 4 reports, never inputs to Phase 3 model development during the frozen
forward protocol.

## 3. Explicit A–J findings

**A. Reusable unchanged:** the entire Phase 3 frozen prediction boundary;
American-odds/probability conversion; no-vig normalization; and the pure
complete-market, consensus, movement, and CLV calculations when their inputs
have already passed NFL sport, identity, completeness, and time guards.

**B. Reusable after sport-safe generalization:** ingestion-run reservation and
lifecycle, the Odds API transport/parser seam, sportsbook persistence, raw quote
persistence, run/snapshot repositories, best-price/model-at-price calculation,
and role-aware loaders. Each needs explicit sport identity and the evidence
hardening described below.

**C. Must not be reused directly:** MLB team auto-creation, generic
create-on-miss game matching, Pacific MLB slate timing, MLB CLIs/schedulers,
starter-aware evaluation and qualification objects/tables, `historical_games`
settlement, early-entry/cohort logic, dashboard/audit queries, and MLB daily
orchestration.

**D. Cross-sport collision risks:** Phase 4A1 resolved scheduled-run identity and
MLB role lookups; Phase 4A2 resolved provider event/run sport coherence and
title-only sportsbook identity for new observations. Team creation, canonical
run/game sport mismatch, free-text selections, legacy evidence, and global
derived analysis remain.

**E. Blocking database constraints:** migration 027 repaired the scheduled-run
index and migration 028 added source/event/provider coherence without changing
NFL roles. The snapshot-role check still has no official NFL semantics, and the
one-event-per-game/source `game_sources` index may reject a replacement NFL
provider event. Other current constraints permit storage but do not make
canonical NFL coexistence safe.

**F. Post-kickoff entry points:** the full list is in section 5.2. The central
gaps are provider-time trust in ingestion, no database cutoff on raw snapshots,
unfiltered generic/CLV loaders, pure functions that assume prefiltered input,
and mutable evaluation/qualification persistence.

**G. NFL mapping:** resolve explicit provider team aliases to existing NFL
franchises, then require one existing canonical NFL game with exact orientation
and compatible kickoff. Never create a team/game on an odds miss. See section 6.

**H. Provenance sufficiency:** Phase 4A2 provides stable provider/bookmaker keys,
secret-free request context, database request/response times, provider event and
update timestamps, cross-row source coherence, and conditional immutability for
new evidence. Official NFL evidence is still blocked by canonical selection/game
identity, kickoff enforcement, and the future evaluation source graph. Raw bytes
and authenticity proof are deliberately not claimed. See section 5.3.

**I. EV semantics:** generic `calculate_expected_value_markets` is
market-relative leave-one-out consensus EV. NFL official model EV is the frozen
NFL probability multiplied by the offered book's decimal odds, minus one. They
must have distinct names, fields, tests, and reports.

**J. Schema boundary:** strengthen the shared raw odds source layer, then keep
NFL evaluation, qualification, paper bet, settlement, and CLV evidence in
NFL-specific append-only relationships referencing Phase 3 predictions. See
section 7.

## 4. Reuse, generalize, and NFL-specific matrix

| Component | Classification | Phase 4 treatment |
|---|---|---|
| Phase 3 frozen artifacts/loaders, routing, inference, prediction service, migration 026 persistence | Reuse unchanged | Read completed official prediction evidence; do not add odds columns or modify lifecycle. |
| Probability conversion and no-vig normalization | Reuse unchanged | Use `Decimal` paths as pure calculations. |
| Complete-market, no-vig, consensus builders | Reuse unchanged with guarded inputs | Feed only one sport/run/game/capture instant, two canonical NFL team selections, and strictly pregame rows. |
| Pure line movement and CLV comparison | Reuse unchanged with guarded inputs | Derive timelines only after sport and cutoff filtering; never let the pure function choose eligibility. |
| `analysis.expected_value` | Reuse unchanged for market-relative analysis only | Label output `market_relative_expected_value`; never substitute it for frozen-model EV. |
| Model-at-price EV formula and best-price ordering | Reuse calculation, not MLB object/service | Extract/use sport-neutral pure logic with explicit frozen NFL probability; leave starter policy behind. |
| Shared `odds_ingestion_runs` and `odds_market_snapshots` | Partially hardened in Phase 4A1/4A2 | Sport-safe uniqueness, source provenance, event/run coherence, and conditional immutability are implemented; canonical selection/game identity and kickoff enforcement remain. |
| Shared `sportsbooks` | Reused through Phase 4A2 provider mapping | Provider/bookmaker key is stable identity; display title is retained per observation and does not drive later resolution. |
| Odds API HTTP/request handling | Reuse after generalization | Separate request/response DTO parsing from sport-specific canonical resolution and persistence; inject sport key and time window. |
| Generic `game_sources` | Conditional | Use a sport-qualified provider source only if reissued-event cardinality is resolved; otherwise add a narrow odds-event mapping. |
| MLB team normalization and create-on-miss game matching | MLB-specific; do not reuse | NFL resolver must find existing NFL teams/games and fail closed on zero/multiple matches. |
| MLB snapshot timing schedule and Pacific target-date semantics | MLB-specific; do not reuse | NFL roles are capture intent; eligibility is per-game relative to immutable kickoff. |
| MLB market evaluation policy/model objects/services/repository | MLB-specific; do not reuse directly | Starter fields, MLB tables, mutable upsert, and policy version are incompatible with NFL evidence. |
| MLB paper settlement, early entry, cohort, dashboards, audits, daily workflow | MLB-specific; do not reuse directly | Add NFL-specific services and tables; preserve MLB behavior. |
| MLB result join through `historical_games` | MLB-specific; do not reuse | Settle from canonical `nfl_games` final evidence with retained source provenance. |

## 5. Cross-sport, leakage, and evidence risks

### 5.1 Cross-sport collisions and blocking constraints

1. **Scheduled run collision — resolved in migration 027:**
   `uq_odds_ingestion_runs_active_scheduled_snapshot` now includes `sport` and
   preserves same-sport MLB uniqueness while allowing an NFL run for the same
   date/role.
2. **Role constraint:** the role check prevents any new NFL-specific official
   capture semantics. Adding roles must not reinterpret existing MLB roles.
3. **Unscoped role lookup — resolved for MLB in Phase 4A1:** MLB early-entry,
   preview, movement, and related date/role queries are pinned to
   `baseball_mlb`.
4. **Provider event namespace — resolved before canonical mapping:** Phase 4A2
   retains a per-run `(source, provider_sport_key, external_event_id)` event
   observation and proves source/sport equality with the run. `game_sources`
   remains unsuitable for NFL canonical mapping and is deferred to Phase 4A3.
5. **One source event per game:** `idx_game_sources_game_id_source_name` prevents
   mapping a replacement Odds API event ID to the same game. NFL reschedules or
   provider event reissues need a deliberate rule, not duplicate games.
6. **Team creation:** the MLB adapter inserts teams by normalized display name.
   An NFL spelling or relocation alias can create a duplicate shared entity
   outside `nfl_team_profiles`.
7. **Sportsbook identity — resolved for new observations:** immutable
   `(provider_name, provider_bookmaker_key)` mapping is shared across sports.
   Display title is retained on each quote and is no longer identity. Historical
   rows remain unknown until an exact existing title is legitimately attached.
8. **Run/game mismatch:** a snapshot references both a run and a shared game,
   but no database rule proves the run sport matches the canonical game's sport.
9. **Selection identity:** a selection is free text. Nothing proves an NFL
   `h2h` selection is exactly the canonical home or away team, and display-name
   changes can break joins and settlement.
10. **Global derived analysis:** `market_analysis` and `analysis.market` do not
    carry sport identity and can combine or rewrite derived values without an
    official evidence boundary.

No migration-026 constraint prevents NFL odds from referencing the shared
`games` row; that remains the desired bridge. Phase 4A1/4A2 removed the raw
sport-coexistence and source-attribution blockers. The material remaining
blockers are official NFL role/canonical mapping semantics, `game_sources`
cardinality policy, canonical selection identity, and kickoff enforcement.

### 5.2 Every identified route for post-kickoff odds to enter pregame analysis

1. The MLB adapter now uses database `response_received_at` as the observation
   time, but still compares only with provider `commence_time`; a stale/later
   provider time can admit a quote after the canonical kickoff.
2. `save_market_selection` and `odds_market_snapshots` allow direct inserts at
   or after game time. There is no trigger using either `games.game_date` or
   `nfl_moneyline_game_predictions.target_kickoff`.
3. Run completion does not validate every child quote against canonical game
   time. Phase 4A2 protects new provenance-bearing terminal runs/snapshots from
   update/delete, but legacy rows retain their established mutability.
4. `analysis.market.analyze_markets` reads every snapshot with no pregame
   filter.
5. `get_market_snapshots(include_live=True)` intentionally returns live rows;
   callers can feed them to pure analytics. Its default guard uses mutable
   `games.game_date`, not immutable prediction kickoff.
6. Complete-market, consensus, expected-value, timeline, line-movement, and CLV
   pure functions accept any supplied timestamp. They do not know kickoff.
7. The generic CLV function defines close as the final input market. If input
   loading includes a post-start quote, it becomes the close.
8. The MLB movement service selects run roles without sport and loads their
   snapshots without any game-start filter before deriving latest/close.
9. The MLB evaluation snapshot SQL has no time predicate. Its normal Python
   service rejects snapshots before prediction and at/after start, but direct
   repository use or direct SQL can bypass it; the evaluation table has no
   equivalent constraint.
10. The preview dashboard loads role snapshots without an explicit timing
    validation before calculating displayed qualification-like results. It is
    informational today but must not become an NFL official source.
11. The evaluation table copies snapshot/run/book/time/price fields without a
    composite foreign key proving they match, so inconsistent or post-kickoff
    evidence can be inserted directly.
12. Qualification is a mutable field on an upserted evaluation, and settlement
    is also upserted. A rerun after kickoff can replace what appears to have
    been the pregame decision unless the official NFL path is append-only.

The NFL design must enforce admissibility before calculation, again on insert,
and when sealing a run. Reporting queries should still filter defensively.

### 5.3 Current odds provenance verdict

For new Phase 4A2 observations, the current tables preserve ingestion-run ID,
declared provider source/sport/role/date, secret-free request context, database
request and response timestamps, lifecycle/quota metadata, immutable provider
event/sport identity and provider team/commence facts, immutable provider
bookmaker key mapping, title at observation, bookmaker/market update times,
SportsModel observation time, exact price/line/selection, and a stable quote ID.
Composite foreign keys prove run/event/source/sport/time and
quote/book/source relationships. Conditional triggers protect this new source
graph without retrofitting old MLB rows.

This is **still not sufficient for official NFL paper evidence**. Missing
evidence includes strict existing-only canonical NFL team/game mapping,
canonical selection team ID, kickoff-drift and pregame database enforcement,
and immutable evaluation/qualification/paper source relationships. Historical
MLB rows cannot recover fields discarded before Phase 4A2. No full raw payload
or payload hash is stored, so the system retains normalized attribution facts
but cannot reproduce provider response bytes or prove authenticity.

## 6. Canonical NFL event and team mapping

NFL odds ingestion must be enrichment-only. It must never call the generic
create-on-miss team or game functions.

Recommended mapping order:

1. Parse and validate the provider response into immutable DTOs without any
   database writes.
2. Resolve provider home/away names through explicit Odds API identities or
   aliases attached to existing `nfl_team_profiles`/season rows. Seed and test
   all 32 teams before a live call. Zero or multiple matches is a hard failure
   for that event; do not fall back to inserting `teams`.
3. Resolve an existing sport-qualified Odds API event mapping if present and
   verify it still has the same teams and compatible kickoff.
4. Otherwise match only existing `nfl_games`/`games` rows with exact canonical
   home/away team IDs, an allowed season/status, and kickoff within a documented
   tolerance. Require exactly one match. Do not reverse teams, and do not create
   a game on miss.
5. Compare provider commence time with both the immutable Phase 3 target kickoff
   when an official prediction exists and the current canonical NFL kickoff.
   Identity drift makes the game ineligible for official evaluation and should
   be retained as an anomaly, not silently remapped.
6. Persist the provider event mapping/observation only after all identity checks
   pass. A replacement external event for the same game must be retained as a
   new observed provider identity with explicit supersession/anomaly provenance,
   not as another canonical game.

The smallest safe event namespace is `(provider, provider_sport_key,
external_event_id)`. If `game_sources` cannot represent provider reissues
without changing established MLB cardinality, add a narrow odds-event mapping
rather than weakening MLB matching globally.

## 7. Recommended persistence boundary (relationships, not DDL)

Shared, strengthened source layer:

- `odds_ingestion_runs`: one provider request/capture attempt, sport-qualified,
  with request identity, database request/response timestamps, raw response
  hash/location or retained payload, lifecycle, role, and quota metadata.
- provider sportsbook identity mapping: stable provider bookmaker key to the
  existing canonical `sportsbooks` row.
- sport-qualified odds event observation/mapping: provider event identity,
  canonical NFL game, provider commence time, canonical-resolution evidence,
  raw event hash/payload, and anomaly state.
- `odds_market_snapshots`: append-only exact quote/outcome observations linked
  to the run/event, canonical game, canonical selection team, provider book,
  market, price/line, provider update time, and conservative received time.

NFL-specific evidence layer:

- **NFL official market evaluation run** references one completed Phase 3 NFL
  prediction run and one completed NFL odds run, records protocol/calculation
  versions, policy identity if applicable, status/counts, and deterministic
  input/output fingerprints.
- **NFL official market evaluation** references exactly one immutable NFL game
  prediction and the exact offered-price snapshot used. It stores frozen model
  probability, offered implied probability, model price edge, model EV,
  consensus no-vig probability, model-market edge, sportsbook count, evaluation
  time, and target kickoff copied under database validation. A child/junction
  records every exact quote snapshot contributing to consensus so consensus can
  be reproduced; a count alone is insufficient.
- **NFL qualification result** references an evaluation and a versioned,
  immutable qualification policy. It stores every policy input, threshold,
  boolean result, and ordered reasons. It is append-only and separate from the
  calculated market evaluation so reporting a new policy cannot rewrite the
  official calculation or old decision.
- **NFL paper bet** references one qualifying result and exact offered quote.
  It snapshots canonical selected team ID, American price, frozen probability,
  stake convention, accepted/evidence time, kickoff, and contract fingerprint.
  It is inserted strictly before kickoff and never updated or deleted. A
  disqualified evaluation cannot receive a paper bet.
- **NFL settlement observation** references a paper bet and retained canonical
  NFL result/source evidence. It stores score, win/loss/push, flat-unit profit,
  settlement time, and result fingerprint. If result corrections must be
  supported, append a superseding settlement observation rather than updating
  the original; reports select the latest valid revision while retaining all
  evidence.
- **NFL CLV evaluation** references the paper bet, exact closing quote snapshot,
  and (if consensus close is chosen) every contributing closing snapshot. It
  stores the closing-definition version and price/probability CLV. Missing a
  valid pregame close produces an explicit unavailable state, never a
  post-kickoff substitute.

All NFL Phase 4 evidence foreign keys should use `ON DELETE RESTRICT`. Terminal
runs, source snapshots used by official evidence, evaluations, qualifications,
paper bets, and settlement/CLV observations should reject update/delete.
Database checks/triggers should verify source row coherence and use the database
clock, following migration 026's defense-in-depth pattern. Do not add Phase 4
foreign keys or columns to the Phase 3 prediction tables.

Relationship summary:

```text
completed nfl_moneyline_prediction_run
  -> immutable nfl_moneyline_game_prediction
       + completed sport-qualified odds_ingestion_run
       + exact pregame odds snapshots / consensus contributors
          -> NFL market evaluation run + evaluation
             -> immutable qualification result
                -> immutable paper bet
                   -> settlement observation(s)
                   -> closing quote evidence + CLV evaluation
```

## 8. Exact point-in-time rules

The official protocol should state and enforce all of the following:

1. Only a completed Phase 3 `official` prediction under the pinned forward
   protocol may seed an official Phase 4 evaluation. Preview predictions and
   manual odds remain explicitly nonofficial cohorts.
2. The prediction must exist before the official odds request begins. Use
   database timestamps; do not accept caller-supplied ordering timestamps.
3. Record at least `request_started_at` and `response_received_at`. Provider
   `last_update` is provenance, not proof that the system possessed the quote
   then. For eligibility, use the conservative received time.
4. An official quote and every consensus contributor must come from the same
   completed NFL ingestion run and must satisfy
   `response_received_at < target_kickoff` and
   `snapshot_received_at < target_kickoff`.
5. Equality with kickoff is live and rejected. No grace period is allowed.
6. The authoritative target identity is the immutable Phase 3 prediction
   `(game_id, teams, target_kickoff)`. It must still equal current canonical NFL
   identity at evaluation. If a game is rescheduled or participants/status
   drift, record an exclusion/anomaly; do not reinterpret the old prediction.
7. Provider commence time must also be later than received time, but provider
   time can never relax rules 4–6.
8. A complete NFL `h2h` market contains exactly the two canonical team IDs,
   once each, for one book/event/capture. Free-text name equality is not enough.
9. Evaluation runs use a repeatable database snapshot. All consensus inputs,
   best-price selection, calculations, and inserts are atomic. Seal deterministic
   hashes of ordered input snapshot IDs and outputs.
10. Best price means the greatest decimal return for the selected canonical
    team among eligible quotes in the official run. Tie-breaking must be stable
    and documented; it must not depend on query order.
11. Paper qualification and paper-bet insertion happen in the same transaction
    as, or in a transaction locked to, the immutable evaluation; the paper bet's
    database creation time must be strictly before target kickoff.
12. Closing evidence is the latest *complete, received, eligible* market strictly
    before the individual game's kickoff under a versioned definition. A role
    label alone does not make a quote a close.
13. Reports must filter sport, protocol, official/manual cohort, model identity,
    policy version, and evidence status explicitly. Partial 2026 results remain
    reporting evidence only.

## 9. Proposed NFL snapshot semantics

Do not copy MLB's 6:30 PM/8:30 PM/11 PM/opening/morning/8 AM entry sequence.
NFL games occur across Thursday, Sunday, Monday, overseas windows, and flexed
kickoffs; a calendar-day run can be pregame for one event and post-start for
another.

For the controlled manual period, use only semantics needed by the protocol:

- `manual`: exploratory, never official evaluation or paper evidence.
- `official_entry`: a capture initiated after a completed official Phase 3
  prediction run for an explicit slate and intended to supply that run's entry
  prices. Each game is still independently admitted by exact timestamps.
- `closing_candidate`: a capture intended to provide possible closing evidence.
  The actual close is derived per game/book as the latest valid complete quote
  strictly before kickoff.

“Opening” should initially be a derived label meaning first retained valid
observation, not a claim that the provider exposed the true market open.
“Latest” is always derived. Do not schedule or add further role vocabulary until
manual observations establish an operational cadence and quota budget.

Run identity should use sport plus an explicit slate/prediction identity, not
only Pacific `target_date`. The existing date may remain for MLB compatibility
and operator display, but NFL eligibility comes from per-game kickoff and the
linked prediction run.

## 10. Proposed Phase 4 subphases

### 4A — Odds Foundation and Sport Isolation

- Repair scheduled odds uniqueness to include sport while preserving MLB's
  current one-active-run-per-date/role behavior.
- Add explicit MLB sport predicates to every role/date lookup before allowing
  a second sport.
- Separate provider request/parsing from canonical resolution/persistence.
- Add stable bookmaker identity, sport-qualified event identity, raw provenance,
  conservative timestamps, canonical NFL team selection, and append-only
  protections.
- Implement strict existing-only NFL team/game matching using offline fixtures.
- Add no-network/zero-credit tests and keep NFL capture manual/nonofficial.

### 4B — Official Market Evaluation

- Add NFL-specific immutable evaluation run and row persistence linked to
  completed official Phase 3 predictions.
- Persist exact offered quote and all consensus contributors.
- Implement distinct named fields for model EV, market-relative EV (if reported),
  model-market edge, and model-price edge.
- Enforce all point-in-time and canonical identity rules in service and database.

### 4C — Paper Qualification and Immutable Evidence

- Define and version an NFL qualification policy without changing the frozen
  probabilities.
- Persist qualification separately from evaluation.
- Create append-only paper bets with exact quote/contract fingerprints and
  strict pre-kickoff database time.
- Support manual official runs only; no scheduler.

### 4D — Settlement and CLV

- Settle against canonical NFL finals with retained source/result provenance.
- Preserve corrections through append-only settlement revisions.
- Define and persist exact closing quote evidence and CLV; never use a post-start
  fallback.
- Report market/paper metrics separately from Phase 3 probability metrics.

### 4E — Controlled Manual Forward Validation

- Execute documented, operator-approved prediction -> odds -> evaluation ->
  paper -> settlement runs on genuine 2026+ events.
- Reproduce input/output fingerprints and audit zero post-kickoff observations.
- Track sample size, pending/excluded games, CLV availability, and operational
  failures. Do not tune models or thresholds from the accumulating sample.

### 4F — Automation Readiness

- Add idempotent scheduling only after manual lifecycle, quota, reschedule, flex,
  partial-response, and recovery behavior is proven.
- Base scheduling on explicit NFL slate/kickoff windows, add monitoring and
  operator-visible failure states, and retain a kill switch.
- Validate that automation cannot create a second official evaluation/paper bet
  or spend a duplicate provider credit.

## 11. End-to-end proposed data flow

1. Phase 3 creates and seals an official 2026+ prediction run and immutable game
   predictions using the frozen early/mature routing contract.
2. An operator selects that completed run and starts a sport-qualified
   `official_entry` odds capture. The run is reserved before HTTP, but no provider
   call occurs unless the exact request is eligible and not already reserved.
3. The adapter retains request/response evidence and parses provider events.
   Strict resolvers map teams and events only to existing canonical NFL entities;
   anomalies are retained and excluded.
4. Exact quote snapshots are appended with canonical selection team IDs and
   conservative received timestamps. Run completion validates counts, hashes,
   run/game sport consistency, and strict pregame status for official-eligible
   rows.
5. An NFL evaluation transaction joins each immutable prediction to the same
   run's complete eligible markets, calculates book no-vig probabilities and
   consensus, selects the best offered price, and calculates frozen-model EV and
   edges. It stores the exact source graph and seals the evaluation.
6. A versioned NFL policy produces an immutable qualification result. If it
   qualifies and database time is still before kickoff, an immutable flat-stake
   paper bet is appended from that exact quote.
7. Later closing-candidate captures add raw observations only. A CLV service
   selects the exact latest valid pregame close under its versioned definition
   and persists source references and calculation.
8. After canonical NFL final evidence exists, settlement appends the outcome and
   profit observation. Corrections append revisions rather than rewriting the
   paper contract.
9. Phase 4 reporting aggregates paper/market evidence. Phase 3 forward reporting
   continues independently, and neither path mutates or tunes a frozen model.

## 12. Tests required before the first live NFL odds call

All provider tests must use committed fixtures and a mocked transport. Add an
explicit test that an unmocked network call fails before request execution.

### Schema and coexistence

- Existing migrations plus the proposed migration apply on a clean PostgreSQL
  database and preserve all MLB tests/queries.
- MLB and NFL may reserve the same date/role independently; duplicate NFL
  running/completed reservations are rejected before HTTP; failed retries are
  allowed deliberately.
- Every existing MLB role/date lookup includes `sport = 'baseball_mlb'` and
  returns the same run as before.
- Snapshot/run sport mismatch, NFL snapshot to non-NFL game, invalid selection
  team, copied-source mismatch, mutation, deletion, and cascade loss are rejected.
- Official odds/evaluation/paper rows reject `snapshot_time == kickoff` and
  `snapshot_time > kickoff` at the database boundary.

### Adapter and provenance

- Exact request URL/parameters use the NFL provider sport key, `h2h`, American
  odds, intended region, and explicit UTC window without consuming a credit.
- Request reservation occurs before transport; duplicate reservation performs
  zero HTTP calls.
- Success, HTTP failure, timeout, malformed JSON, partial event, duplicate
  outcome, incomplete market, and rollback/failure lifecycle are covered.
- Request/response times, quota headers, raw payload/hash, event key, bookmaker
  key/title, provider update timestamps, price, and canonical received time
  round-trip exactly and reproduce hashes.
- Identical fixture reprocessing is idempotent according to the chosen evidence
  contract and cannot duplicate official quote evidence.

### NFL identity

- All 32 current NFL provider names/keys resolve to existing canonical team IDs;
  relocation/abbreviation aliases are explicit and season-aware.
- Unknown, blank, ambiguous, reversed, or conflicting teams fail closed and
  never insert `teams`, `games`, `nfl_games`, or `nfl_team_profiles`.
- Existing event mapping wins only after team/kickoff verification.
- Unique exact-team/tolerance match succeeds; zero or multiple matches are
  quarantined; reschedule and provider event-ID replacement scenarios retain
  evidence without duplicate canonical games.
- Provider commence later than canonical kickoff cannot admit a post-kickoff
  quote.

### Market and point-in-time calculations

- Only complete two-team NFL `h2h` markets enter no-vig/consensus.
- Consensus source IDs and deterministic hash reproduce exactly; cross-sport,
  cross-run, cross-event, and mixed-time inputs are rejected.
- Best-price selection and ties are deterministic.
- Market-relative leave-one-out EV and frozen-model-at-price EV have separate
  tests and intentionally different expected values.
- Official evaluation requires a completed pinned official Phase 3 prediction,
  request start after prediction creation, unchanged canonical identity, and all
  quote times strictly before kickoff.
- Pure analytics given a post-start row cannot make it official because the
  persistence/service boundary rejects the input.
- Closing selection ignores incomplete and at/after-kickoff observations and
  reports unavailable when no valid close exists.

### Immutable evidence lifecycle

- Evaluation run atomicity, counts, fingerprints, terminal transitions,
  concurrency, retries, and partial rollback mirror migration 026 standards.
- One official evaluation/qualification/paper contract per chosen protocol key
  is enforced; reruns return or reject rather than update.
- Disqualified evaluations cannot create paper bets; qualified paper-bet insert
  after kickoff is rejected even if the quote was pregame.
- Settlement uses the paper bet's stored team/price/stake, handles regular-season
  ties as the agreed push behavior, and cannot overwrite original evidence.
- Result correction and CLV evidence revisions retain history.
- The full existing suite remains green, no test writes production evidence, and
  a repository/data audit proves the fixtures used no live provider and no API
  quota.

## 13. Smallest recommended first implementation slice

The first Phase 4A task should be a single sport-isolation slice with no NFL
HTTP call:

1. Add a migration proposal/implementation that replaces scheduled odds-run
   uniqueness with `(sport, target_date, snapshot_role)` while preserving the
   same MLB partial-index semantics.
2. Add `sport = 'baseball_mlb'` to all current MLB date/role run selectors and
   prove unchanged behavior with regression tests.
3. Introduce a pure, transport-independent Odds API response DTO/parser that is
   parameterized by provider sport key and retains provider event/bookmaker
   identity and timestamps, exercised only with an NFL fixture.

Stop there. Do not yet persist NFL quotes or expose a live command. This removes
the known coexistence blocker, prevents MLB query ambiguity, and establishes the
testable adapter seam needed for the next provenance and strict-mapping slice
without speculative workflow abstraction.

## 14. Human decisions not determined by current code

The following require explicit protocol/product decisions rather than inference
from current MLB behavior:

1. Which legal/operational sportsbook region and allowlist defines the NFL
   consensus and best executable paper price.
2. Whether the official consensus includes the offered-price book or uses a
   leave-one-out reference. Model EV itself must always use the frozen model
   probability and actual offered price regardless of this choice.
3. The initial NFL qualification policy, stake convention, minimum book count,
   and whether any thresholds are declared before forward collection. They must
   not be selected by optimizing partial 2026 outcomes.
4. The operator cadence and exact slate grouping for `official_entry` and
   `closing_candidate`, including Thursday/Monday/overseas/flex games and API
   quota budget.
5. Whether official CLV is same-sportsbook price CLV, market-consensus
   probability CLV, or both. The close definition and fallback-to-unavailable
   policy must be versioned before evidence collection.
6. How canceled/postponed/rescheduled games, venue/home-team changes, and
   regular-season ties are treated for official paper cohorts. The conservative
   architecture excludes identity drift and never reuses post-kickoff odds.
7. Raw provider evidence retention policy: full payload in PostgreSQL versus an
   immutable external blob with a database hash/reference, subject to provider
   terms and storage policy.
8. Whether corrected NFL results create superseding settlement revisions or
   wait for a declared finalization interval before the first settlement. In no
   case should the immutable paper bet be changed.

## 15. Audit verdict

Phase 4 is feasible as a small additive layer, and migration 026 provides a
sound immutable upstream contract. The pure probability and market math is
largely reusable. The current MLB HTTP/persistence service, identity creation,
role timing, evaluation policy, paper tables, settlement, and orchestration are
not safe to reuse directly for NFL.

The shared odds schema is not yet ready for a controlled live NFL capture. Phase 4A1
removed the hard MLB/NFL scheduled-run collision, Phase 4A2 added stable
provider identity and immutable source attribution, and Phase 4A3 added exact
existing-only NFL team/game/selection resolution plus immutable provider-event
mapping. Phase 4A4 adds database-enforced, strictly pregame qualification,
canonical selection persistence, and immutable point-in-time official quote
evidence. The first controlled live capture, raw capture operational controls,
and its post-capture evidence audit remain for Phase 4A5; immutable market
evaluation and paper relationships remain later work. Keep Phase 3 frozen and
treat every partial 2026 outcome solely as prospective validation evidence.
