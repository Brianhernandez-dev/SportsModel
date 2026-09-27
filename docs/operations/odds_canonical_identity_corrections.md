# Odds Canonical Identity Corrections

## Purpose and boundary

Migration 033 introduces an append-only correction layer for the narrow case
where an immutable, provenance-bearing MLB odds observation was acquired under
the wrong canonical game. It changes only the canonical association used by
downstream readers. It does not reconstruct odds, change when a quote existed,
or change any provider, book, market, selection, line, price, run, or observation
evidence.

The base `odds_market_snapshots.game_id` remains the raw acquisition identity.
Application readers that need canonical identity use the single centralized
`odds_market_snapshots_effective` view:

- `raw_acquisition_game_id` is always the immutable snapshot `game_id`;
- `effective_game_id` is the correction's `corrected_game_id`, if one valid
  observation correction exists, and otherwise the raw acquisition game ID.

Code must not reproduce this resolution with local `CASE` or `COALESCE`
expressions.

## Reader inventory

The repository-wide inventory includes direct SQL, Python construction of
`MarketSnapshot`, scripts, and downstream pure-Python consumers.

### A: effective canonical identity required

| Reader | Use |
| --- | --- |
| `analysis/market.py` | Groups snapshots into canonical markets. |
| `database/repository.py` | Selects snapshots by game and applies pregame cutoffs. |
| `analysis/moneyline_market_evaluation_service.py` | Links entry snapshots to prediction games. |
| `analysis/moneyline_movement_service.py` | Groups opening/entry movement by game. |
| `analysis/moneyline_preview_dashboard_service.py` | Links opening prices to preview predictions. |
| `auditing/moneyline_live_pipeline.py` | Audits snapshot coverage for prediction games. |
| `database/feature_data_audit.py` | Evaluates whether snapshots precede canonical starts. |

The market builder, no-vig, line-movement, closing-line, and model-value code
consume `MarketSnapshot.game_id` in memory. They therefore receive effective
identity from the centralized database loaders and require no separate SQL
resolution.

### B: raw acquisition identity intentionally required

| Reader | Reason |
| --- | --- |
| `nfl/official_pregame_evidence.py` | Freezes and validates the raw NFL acquisition graph; MLB corrections do not alter it. |
| `scripts/invoke_native_postgresql_backup_restore_acceptance.ps1` | Checks raw referential integrity, not betting semantics. |
| Migration 028 triggers and provenance tests | Protect the originally acquired rows. |
| Migration 030 NFL evidence trigger/tests | Compare raw NFL snapshot identity to the NFL mapping contract. |
| Correction integration tests | Prove raw and effective identities remain separately queryable. |

### C: unaffected

| Reader/writer | Reason |
| --- | --- |
| `database/control_center_repository.py` | Counts snapshots and reads the latest timestamp only. |
| `database/moneyline_dashboard_status_repository.py` | Reads the maximum snapshot time for a run only. |
| `ingest/odds_api.py` | Writes new immutable acquisitions; future canonical selection occurs before insertion. |
| `nfl/manual_odds_capture.py` | Writes immutable NFL acquisitions. |
| Settlement, candidate, and publication readers | Follow persisted evaluation/prediction identity and do not derive a game from snapshot `game_id`. |
| Historical feature/training extraction | No direct snapshot-identity extraction exists outside the classified readers above. |

Tests that construct `MarketSnapshot` directly remain unaffected because the
new `raw_acquisition_game_id` field is optional. Database loaders populate it
explicitly.

## Insert validation and immutability

One correction row covers all snapshots owned by one provider observation. The
database rejects a correction unless all of these conditions hold:

- the observation is an Odds API MLB observation;
- it owns at least one snapshot and all covered snapshots have exactly one raw
  game ID equal to `original_game_id`;
- provider home/away names and orientation exactly match both original and
  corrected canonical games;
- the observation's source/event identity is uniquely mapped to the corrected
  game before the correction is inserted;
- the corrected game is the sole same-orientation, MLB-authoritative canonical
  game within 15 minutes of the provider commence time;
- original and corrected game IDs differ;
- no earlier correction exists for the observation;
- reason and evidence reference are non-empty.

Correction rows cannot be updated or deleted. Existing migration-028 triggers
continue to prevent changes to provenance-bearing runs, observations, and
snapshots.

## Point-in-time contract

The correction does not change `snapshot_time`, `observed_at`, provider commence
time, book identity, line, price, market, or selection. Pregame filtering uses
the unchanged snapshot timestamp against the corrected canonical game's start.
The correction therefore cannot make a quote appear to have been observed
earlier and supplies no later quote content. It is an identity correction, not
historical odds reconstruction.

## Non-executed production sequence

This sequence is a proposal for separate review and authorization. This
candidate does not execute it.

1. Deploy the reviewed application and migration artifact while keeping affected
   workflows inactive until schema compatibility is established.
2. Apply only controlled migration 033.
3. Reverify Git, schema, production identity, the two canonical games, the Odds
   event mapping, observation 2283, all 12 immutable snapshots, and protected
   state fingerprints.
4. In one bounded `SERIALIZABLE` transaction, with exact preconditions:
   update the two reviewed `game_date` values; reassign `game_sources` row 12197
   to canonical 11362; insert one correction for observation 2283 from raw 11368
   to effective 11362. Do not update any snapshot, observation, or ingestion run.
5. Verify raw/effective identity, unchanged provenance and quote fields, unique
   matcher resolution, write counts, and transaction commit evidence.
6. Verify the next natural workflow; do not manually rerun a point-in-time
   workflow merely to test the correction.
