# MLB Moneyline Live Pipeline Runbook

## Purpose

This runbook documents the daily operating sequence for the SportsModel MLB Moneyline prediction, market evaluation, paper-candidate, settlement, audit, and dashboard pipeline.

A stored prediction or paper candidate is not automatically a wager or recommendation.

## Current Model

- Model: `mlb_moneyline_v1`
- Feature schema: `1.2.0`
- Representation: matchup difference
- Training rows: 7,998 regular-season MLB games
- Active features: 42
- Candidate policy: `1.0.0`
- Frozen artifact: `data/models/mlb_moneyline_v1`

The frozen model should not be retrained without a separately evaluated and versioned model candidate.

## Daily Operating Sequence

Run core commands from `D:\SportsModel`.

Use:

    D:\SportsModel\.venv\Scripts\python.exe

### Scheduled execution validity

Production wrappers fail closed when Task Scheduler starts an MLB writer
outside its intended Pacific-time start window. The valid start window is
half-open and lasts one hour from the scheduled trigger: `[trigger, trigger +
60 minutes)`. This admits normal start jitter and the configured retries at
15, 30, and 45 minutes while refusing broader `StartWhenAvailable` catch-up.

| Writer | Pacific trigger | Intended target |
| --- | --- | --- |
| Morning snapshot | 6:00 AM | Current Pacific date |
| Postgame | 7:15 AM and 1:15 PM | Previous Pacific date |
| Pregame | 8:00 AM | Current Pacific date |
| Afternoon snapshot | 12:00 PM | Current Pacific date |
| Opening snapshot | 6:30 PM | Next Pacific date |
| Tomorrow Preview | 6:45 PM | Next Pacific date |
| Evening snapshot | 8:30 PM | Next Pacific date |
| Late Night snapshot | 11:00 PM | Next Pacific date |

The wrappers check once before readiness or task-dependency waits and again
immediately before provider or workflow execution. An expired run exits
nonzero, records its intended schedule, target date, validity window, and
refusal reason in the task log, and must remain a point-in-time gap. Do not
backfill an expired snapshot or prediction with later evidence. `near_close`
remains an explicitly invoked, game-relative capture and is not one of these
fixed scheduled roles.

Pregame's second check also reads the earliest canonical MLB start for the
current Pacific target date. Its effective deadline is the earlier of that
first pitch and the normal one-hour limit. Missing or unreadable canonical
slate timing fails closed before the daily workflow creates a run or contacts
a provider.

Tomorrow Preview waits for an in-progress Opening Snapshot for up to ten
minutes and then requires Opening's last run to be from the current Pacific
date with a successful task result. Preview cannot generate output from a
missing, failed, or still-running Opening capture. This dependency permits a
normal Opening retry at or after 6:45 PM without allowing Preview to overtake
it; no separate static 6:45 PM Opening cutoff is applied.

### 1. Synchronize the schedule

    D:\SportsModel\.venv\Scripts\python.exe .\scripts\sync_mlb_schedule.py --start-date YYYY-MM-DD --days-ahead 7

### 2. Generate predictions

    D:\SportsModel\.venv\Scripts\python.exe .\scripts\predict_mlb_moneyline.py --target-date YYYY-MM-DD

Record the prediction run ID.

### 3. Capture Moneyline odds

    D:\SportsModel\.venv\Scripts\python.exe .\scripts\fetch_mlb_odds.py

Record the odds-ingestion run ID.

This command contacts The Odds API and consumes quota. Do not run it repeatedly for testing.

Safe help command:

    D:\SportsModel\.venv\Scripts\python.exe .\scripts\fetch_mlb_odds.py --help

### 4. Evaluate predictions against odds

    D:\SportsModel\.venv\Scripts\python.exe .\scripts\evaluate_moneyline_predictions.py --prediction-run-id PREDICTION_RUN_ID --odds-run-id ODDS_RUN_ID

Policy `1.0.0` currently requires:

- Model EV of at least 3%
- Model-market edge of at least 2 percentage points
- At least 5 sportsbooks
- Both probable starters
- Both starter feature sets

### 5. Run the pregame audit

    D:\SportsModel\.venv\Scripts\python.exe .\scripts\audit_moneyline_live_pipeline.py --prediction-run-id PREDICTION_RUN_ID --odds-run-id ODDS_RUN_ID

Expected pregame state:

    Pipeline state: awaiting_results

There should be no duplicates or integrity issues.

### 6. Ingest final results

    D:\SportsModel\.venv\Scripts\python.exe .\scripts\fetch_mlb_results.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD

The same date can safely be rerun when some games or box scores are not yet available.

### 7. Settle paper candidates

    D:\SportsModel\.venv\Scripts\python.exe .\scripts\settle_moneyline_paper_candidates.py --prediction-run-id PREDICTION_RUN_ID --odds-run-id ODDS_RUN_ID

Settlement uses stored pregame prices and flat one-unit stakes. Unfinished games remain pending. Reruns are safe.

### 8. Run the final audit

    D:\SportsModel\.venv\Scripts\python.exe .\scripts\audit_moneyline_live_pipeline.py --prediction-run-id PREDICTION_RUN_ID --odds-run-id ODDS_RUN_ID

Expected completed state:

    Pending candidates: 0
    Pipeline state: complete
    Integrity issues: None

## Dashboard

Run from `D:\SportsModel`:

    powershell.exe -ExecutionPolicy Bypass -File .\scripts\run_dashboard.ps1

The production dashboard is normally owned by the repository-managed Windows
scheduled task rather than an interactive shell. Its boot triggers, process
ownership, health contract, controlled restart procedure, and reboot validation
are documented in [Dashboard Boot and Recovery](dashboard_recovery.md).

The Moneyline Live page displays predictions, evaluations, paper candidates, settlements, record, profit, ROI, model EV, market edge, and drawdown.

The Daily Card provides prediction explanations only after a user selects a
specific prediction. Each explanation reconstructs the historical point-in-time
feature state with read-only database queries and the prediction run's frozen
model artifact. It does not call an external provider and is not a persisted
snapshot of the original inference vector.

Contribution rankings are shown only when the reconstructed probability and
missing-value evidence satisfy the explanation service's authority checks.
Non-authoritative reconstructions show the probability mismatch but withhold
category and feature rankings. A later historical source correction or backfill
can therefore make a previously reproducible prediction non-authoritative.

## First Forward Paper Slate

- Target date: 2026-07-30
- Prediction Run: 1
- Odds Run: 181
- Candidates: 5
- Record: 4-1-0
- Profit: +2.7353 units
- ROI: 54.71%
- Average model EV: 7.59%
- Maximum drawdown: 1.0000 unit
- Pipeline state: complete
- Integrity issues: None

The five-game result validates the end-to-end engineering pipeline. It is not a meaningful sample for establishing profitability.

## Forward Validation

Track results over repeated independent pregame slates:

- Predictions
- Qualified candidates
- Record
- Profit units
- ROI
- Average model EV
- Calibration
- Closing-line value when available
- Maximum drawdown
- Stability across time periods

Do not change candidate thresholds based on a small sample.
