# Phase 8 Odds Snapshot and CLV Foundation

Status: Accepted for implementation
Date: 2026-08-04

## Objective

Add a reliable fixed-snapshot odds foundation for MLB Moneyline
movement and closing-line-value analysis without changing the frozen
Moneyline model, candidate thresholds, or settlement behavior.

## Existing Boundary

The production daily workflow owns one official odds ingestion run for
each target date. That run is used for market evaluation, paper
candidate selection, auditing, and settlement.

Additional odds captures must remain ingestion-only and must not create
predictions, evaluations, paper candidates, or settlements.

## Snapshot Roles

Supported ingestion-run roles are:

- legacy
- manual
- opening
- morning
- entry
- afternoon
- near_close

The entry role is the official model-entry snapshot used by the daily
Moneyline workflow.

Latest and closing are derived concepts rather than stored roles.

Latest is the newest completed eligible snapshot.

Closing is the newest completed snapshot captured before the individual
game's scheduled start time.

## Storage Decision

Raw sportsbook observations remain immutable in
odds_market_snapshots.

Snapshot identity and API response metadata belong to
odds_ingestion_runs.

The ingestion-run table will add:

- target_date
- snapshot_role
- status_code
- remaining_requests
- used_requests

Existing daily-workflow odds runs will be classified as entry runs.
Other historical runs will be classified as legacy unless their
existing use clearly identifies them as an entry snapshot.

## Idempotency

Only one running or completed scheduled capture may exist for each
target_date and snapshot_role combination.

Scheduled roles are:

- opening
- morning
- entry
- afternoon
- near_close

Failed captures may be retried.

Manual and legacy captures are not constrained to one run per date.

The ingestion run must be reserved before making the external API
request so a duplicate scheduled invocation cannot spend an
unnecessary API credit.

## Production Protection

The daily Moneyline pregame workflow explicitly requests the entry
snapshot role.

Only entry snapshots may drive official Moneyline market evaluation and
paper candidate creation.

Auxiliary snapshot workflows perform odds ingestion only.

No Phase 8 snapshot work changes:

- mlb_moneyline_v1
- feature schema 1.2.0
- candidate policy 1.0.0
- minimum EV
- minimum model edge
- sportsbook-count requirement
- starter or feature-availability requirements

## Movement and CLV

Opening, entry, latest, and closing consensus values are derived from
the stored raw snapshots.

For the model-selected team:

Probability CLV =
closing no-vig consensus probability
minus
entry no-vig consensus probability

A positive result means the closing market moved toward the model
selection. A negative result means the market moved away.

American entry and closing prices will also be exposed, but
probability-based CLV is the primary analytical measure.

## Initial Rollout

1. Add ingestion-run snapshot metadata and constraints.
2. Preserve existing entry-workflow behavior.
3. Add a reusable ingestion-only command for auxiliary roles.
4. Validate duplicate protection using mocked requests.
5. Test manual captures before creating scheduled tasks.
6. Add fixed auxiliary schedules only after quota behavior is verified.
7. Add movement and CLV queries.
8. Add dashboard visibility.
9. Consider per-game near-close scheduling only after the fixed
   foundation is stable.
