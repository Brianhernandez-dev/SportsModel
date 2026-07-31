# SportsModel

SportsModel is a modular sports analytics and prediction platform currently focused on an MLB Moneyline minimum viable product.

It combines data ingestion, feature engineering, model evaluation, pregame prediction, sportsbook market comparison, forward paper tracking, settlement, operational auditing, and a read-only Streamlit dashboard.

## Current Milestone

Version candidate: `v1.3.0` — Live MLB Moneyline Pipeline and Dashboard

Completed capabilities include:

- Historical MLB schedules, results, and box scores
- Canonical teams, players, rosters, and assignment history
- Pregame Moneyline odds ingestion
- Feature schema `1.2.0`
- Multi-season Moneyline training dataset
- Chronological model evaluation
- Frozen and hash-validated model artifact
- Upcoming schedule synchronization
- Daily prediction persistence
- Model-versus-market evaluation
- Versioned paper-candidate policy
- Paper settlement
- End-to-end pipeline audit
- Streamlit system-health and Moneyline Live dashboard
- Automated testing

## Current Model

- Model: `mlb_moneyline_v1`
- Feature schema: `1.2.0`
- Training games: 7,998
- Active features: 42
- Representation: matchup difference
- Model type: regularized logistic regression
- Artifact directory: `data/models/mlb_moneyline_v1`

## First Forward Slate

The first permanent live slate completed on July 30, 2026:

- Predictions: 10
- Evaluations: 10
- Paper candidates: 5
- Settlements: 5
- Record: 4-1-0
- Profit: +2.7353 units
- ROI: 54.71%
- Pipeline state: complete
- Integrity issues: None

Five candidates are not a meaningful profitability sample. This result validates the engineering pipeline while repeated forward testing will evaluate the model and policy.

## Architecture

    MLB Stats API
        |
    Games, results, box scores, players, rosters
        |
    Feature generation
        |
    Frozen Moneyline model
        |
    Stored pregame predictions
        |
    The Odds API
        |
    Stored Moneyline market snapshots
        |
    Model-market evaluation
        |
    Paper-candidate policy
        |
    Result ingestion and settlement
        |
    Pipeline audit
        |
    Streamlit dashboard

## Project Structure

- `database/migrations/` — PostgreSQL schema migrations
- `docs/` — architecture, feature, and operations documentation
- `scripts/` — operational and research entry points
- `src/sportsmodel/` — application package
- `tests/` — automated test suite
- `data/` — generated local artifacts, intentionally untracked

## Current Priority

The next phase is repeated MLB Moneyline forward paper validation.

Deferred work includes MLB Totals, Run Line, First Five, Team Totals, Player Props, NFL expansion, public deployment, and automated wager recommendations.

## Operations

See `docs/operations/mlb_moneyline_live_pipeline.md` for the daily sequence, safe rerun behavior, settlement process, audit requirements, and dashboard launch command.

## Disclaimer

SportsModel is intended for personal research, analytics, and software engineering development. Model output and paper candidates do not guarantee future performance.
