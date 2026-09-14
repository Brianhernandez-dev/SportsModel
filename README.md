# SportsModel

SportsModel is a modular sports analytics and prediction platform for reproducible market research, forward evidence collection, and production-oriented workflow validation across MLB and NFL.

It combines canonical sports data, point-in-time feature engineering, frozen model artifacts, pregame predictions, market evidence, evaluation, settlement, operational auditing, and read-only reporting. The repository separates model evidence from market-performance research and treats production operations as explicitly authorized workflows rather than implied project status.

## Established Capabilities

### MLB Moneyline

- Historical and current schedules, results, box scores, players, and rosters
- Point-in-time feature generation and chronological model evaluation
- Frozen, hash-validated Moneyline model artifacts
- Pregame prediction and sportsbook market-evidence persistence
- Model-versus-market evaluation and versioned paper-candidate policy
- Settlement, pipeline auditing, operational recovery controls, and dashboarding
- Forward-validation workflows with explicit timing, retry, and evidence rules

### NFL Moneyline

- Canonical schedules, results, teams, and team-game statistics with source provenance
- Point-in-time early-season and mature feature pipelines
- Frozen early-season and mature models with deterministic routing
- Immutable prospective prediction, odds, market-evaluation, and pregame evidence infrastructure
- Historical probability evidence reconstruction with leakage and provenance controls
- A frozen historical-market base research protocol and retained chain-of-custody records

The frozen NFL historical-market base protocol does not authorize historical market-performance analysis. Outcome-blind provider feasibility, a final provider amendment, a normative analysis specification, the required independent reviews and freezes, and activation of the approved analysis bundle must occur before historical odds may be joined to model probabilities, outcomes, or derived performance.

## Architecture

| Layer | Responsibility |
| --- | --- |
| Canonical data | Schedules, results, teams, players, and statistics with source provenance |
| Point-in-time features | Prediction-cutoff-safe feature generation |
| Models | Frozen, versioned model artifacts and deterministic routing |
| Probability evidence | Immutable pregame model outputs |
| Market evidence | Provider observations under sport-specific identity, provenance, and timing controls |
| Evaluation | Versioned model-market and research policies |
| Operations | Settlement, audit, recovery, and read-only reporting |

MLB and NFL share selected infrastructure only where identity, provenance, timing, and persistence contracts are explicitly sport-safe. Sport-specific production and evidence paths remain isolated where their contracts differ.

## Research and Evidence Boundaries

- Point-in-time correctness and prevention of data leakage are required for features, joins, model development, and market research.
- Frozen artifacts and protocols are immutable; successors require new identities and retained predecessor evidence.
- Exposed historical or forward evidence cannot be reused as untouched confirmation.
- Historical provider research must remain outcome-blind until all required pre-join methodology and review gates are satisfied.
- Production status is verified from current live evidence when authorized; it is not inferred from repository documentation.

Detailed NFL research boundaries are maintained in the [historical probability evidence architecture](docs/architecture/nfl_historical_probability_evidence.md), the [frozen historical-market base protocol](docs/architecture/nfl_historical_market_research_protocol_0.2.5.md), and its [freeze record](docs/architecture/nfl_historical_market_research_protocol_0.2.5_freeze_record.md).

## Project Structure

- `database/migrations/` — ordered PostgreSQL schema migrations
- `docs/architecture/` — durable system, evidence, and research contracts
- `docs/operations/` — authorized operational runbooks and recovery procedures
- `scripts/` — operational and research entry points
- `src/sportsmodel/` — application package
- `tests/` — automated unit and integration coverage
- `data/` and `artifacts/` — generated or frozen artifacts according to their documented retention contracts

## Current Direction

- Continue controlled MLB forward validation and production hardening without treating short-run results as profitability evidence.
- Complete outcome-blind NFL historical-market provider feasibility and the required provider, analysis, independent-review, freeze, and authorization gates.
- Begin historical NFL market-performance analysis only after those gates explicitly authorize the join.
- Consider additional sports and markets only after the current Moneyline evidence and correctness contracts are satisfied.

## Operations

- [MLB Moneyline Live Pipeline](docs/operations/mlb_moneyline_live_pipeline.md)
- [NFL Moneyline Forward Operations](docs/operations/nfl_moneyline_forward_operations.md)

Operational runbooks define the authorized sequence, timing, safe rerun behavior, audit requirements, and failure handling. Their existence does not establish current production health.

## Disclaimer

SportsModel is intended for personal research, analytics, and software engineering development. Model output and paper candidates do not guarantee future performance.
