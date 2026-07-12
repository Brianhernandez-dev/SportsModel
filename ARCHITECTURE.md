# SportsModel Architecture

## Purpose

SportsModel is a Python and PostgreSQL sports-betting analytics platform. MLB is the first supported sport. The system collects historical results and sportsbook odds, normalizes the data into canonical entities, builds market-level analytics, identifies potential expected-value opportunities, and prepares data for later backtesting and machine-learning workflows.

## Current Data Flow

```text
The Odds API / MLB Stats API
            |
            v
      Ingestion Layer
            |
            v
       PostgreSQL
            |
            v
      Repository Layer
            |
            v
      MarketSnapshot
            |
            v
   Complete Market Builder
            |
            v
      CompleteMarket
            |
      +-----+------------------+
      |                        |
      v                        v
Line Movement Engine      No-Vig Engine
      |                        |
      v                        v
 LineMovement               NoVigMarket
                               |
                               v
                    Consensus Market Engine
                               |
                               v
                      ConsensusMarket
                               |
                               v
                    Expected Value Engine
                               |
                               v
                   ExpectedValueMarket
```

## Main Layers

### 1. Ingestion

Location:

```text
src/sportsmodel/ingest/
```

Responsibilities:

- Fetch MLB schedules and finalized results from the MLB Stats API.
- Fetch moneyline, spread, and total odds from The Odds API.
- Normalize teams and sportsbooks.
- Create or reuse canonical games.
- Store sportsbook market selections as time-stamped snapshots.
- Record ingestion-run audit information and failures.

Important modules:

```text
mlb_stats.py
odds_api.py
```

### 2. Database and Migrations

Locations:

```text
src/sportsmodel/database/
database/migrations/
```

Responsibilities:

- Provide PostgreSQL connections.
- Discover, validate, baseline, and apply ordered SQL migrations.
- Protect applied migrations with SHA-256 checksums.
- Run each new migration transactionally.
- Load stored odds data through the repository layer.

Important modules:

```text
connection.py
migrations.py
repository.py
```

Important tables:

```text
games
game_sources
historical_games
sportsbooks
odds_market_snapshots
odds_ingestion_runs
schema_migrations
market_analysis
```

### 3. Domain Models

Location:

```text
src/sportsmodel/models/
```

Responsibilities:

- Define immutable, typed objects passed between application layers.
- Keep database rows separate from derived analytics.
- Preserve market identity, sportsbook identity, timestamps, lines, and prices.

Current models:

```text
MarketSnapshot
CompleteMarket
LineMovement
NoVigSelection
NoVigMarket
ConsensusSelection
ConsensusMarket
ExpectedValueSelection
ExpectedValueMarket
```

### 4. Analytics

Location:

```text
src/sportsmodel/analysis/
```

#### Complete Market Builder

Module:

```text
market_builder.py
```

Groups raw sportsbook selections into valid two-sided markets.

Grouping rules:

- Moneyline: same game, sportsbook, and snapshot time.
- Totals: same game, sportsbook, total, and snapshot time.
- Spreads: same game, sportsbook, absolute spread value, and snapshot time.
- Incomplete or inconsistent markets are excluded.

#### Line Movement Engine

Module:

```text
line_movement.py
```

Calculates opening-to-latest movement for each sportsbook selection.

Outputs include:

- Opening and latest line.
- Line change.
- Opening and latest price.
- Price change.
- First and latest snapshot time.
- Snapshot count.

Pregame snapshots are used by default. Live and post-start odds require explicit opt-in.

#### Probability Utilities

Module:

```text
probability.py
```

Provides reusable probability calculations:

- American odds to implied probability.
- American odds to decimal odds.
- Vig removal through probability normalization.

#### No-Vig Engine

Module:

```text
no_vig.py
```

Transforms each `CompleteMarket` into a `NoVigMarket` by:

1. Converting each price to implied probability.
2. Summing the implied probabilities.
3. Normalizing them so the no-vig probabilities sum to 1.0.

#### Consensus Market Engine

Module:

```text
consensus.py
```

Combines matching no-vig markets across sportsbooks.

Rules:

- Markets must match by game, market type, canonical line, and snapshot time.
- At least two sportsbooks must contribute.
- Every contributing sportsbook must offer every selection.
- Spread markets retain signed selection lines while using the absolute spread as the market-level key.

#### Expected Value Engine

Module:

```text
expected_value.py
```

Calculates sportsbook-specific expected value using a leave-one-sportsbook-out consensus.

For each target sportsbook:

1. Exclude the target sportsbook from the reference group.
2. Average the no-vig probabilities from the remaining sportsbooks.
3. Convert the target sportsbook price to decimal odds.
4. Calculate:

```text
EV = (Consensus Probability x Decimal Odds) - 1
```

A positive result indicates that the target sportsbook price is better than the independent market consensus suggests.

## Repository Behavior

The repository currently loads market snapshots with this default behavior:

```python
get_market_snapshots()
```

- Returns only snapshots captured before the scheduled game start.
- Uses timezone-aware UTC timestamps.

Optional behavior:

```python
get_market_snapshots(game_id=123)
get_market_snapshots(include_live=True)
```

## Testing Strategy

Location:

```text
tests/
```

Current test areas:

```text
line movement
probability conversion
vig removal
no-vig markets
consensus markets
expected value
```

Standard validation command:

```powershell
python -m pytest
```

Development workflow:

```text
Design
  -> Implement
  -> Compile
  -> Run unit tests
  -> Validate against real data
  -> Commit
  -> Merge feature branch
```

## Git Workflow

Standard branch flow:

```text
main
  -> feature/<feature-name>
  -> commit tested milestone
  -> merge --no-ff into main
```

Before each major change:

```powershell
git status
git branch --show-current
```

Before each milestone commit:

```powershell
python -m pytest
git diff --check
git add .
git commit -m "<clear milestone message>"
```

## Current Status

Completed:

- PostgreSQL and Docker environment.
- Canonical game mapping.
- MLB historical-results ingestion.
- Live and historical odds ingestion.
- Sportsbook normalization.
- Odds-ingestion audit tracking.
- Automated migration runner.
- Pregame filtering and UTC timestamp handling.
- Domain-model layer.
- Repository layer.
- Complete Market Builder.
- Line Movement Engine.
- Probability utilities.
- No-Vig Engine.
- Consensus Market Engine.
- Expected Value Engine.
- Automated unit-test suite.

## Recommended Next Milestones

### 1. Closing Line Value

Define the closing snapshot for each market and compare earlier prices or probabilities against the final pregame market.

### 2. Backtesting

Simulate historical betting decisions without look-ahead bias. Track:

- Bet count.
- Win rate.
- Return on investment.
- Units won or lost.
- EV buckets.
- Market type.
- Sportsbook.
- Closing-line performance.

### 3. Feature Store

Create reproducible pregame features for modeling, including:

- Consensus probability.
- Expected value.
- Opening and current line.
- Line movement.
- Sportsbook disagreement.
- Snapshot depth and timing.
- Historical team performance.

### 4. Machine Learning

Train and evaluate initial models only after backtesting and leakage controls are established.

Suggested first targets:

- Home-team win probability.
- Total-over probability.
- Calibration against consensus market probability.

### 5. Automation and Reporting

Add scheduled ingestion and analysis, then generate concise reports showing:

- Highest positive-EV opportunities.
- Supporting sportsbook count.
- Market disagreement.
- Line movement.
- Data freshness.

## Design Principles

- Prefer small, testable components.
- Keep SQL access inside the repository or migration layer.
- Use immutable domain models between layers.
- Avoid persisting derived analytics until the output schema is stable and profiling justifies it.
- Default all betting analytics to pregame data.
- Exclude the target sportsbook from its own consensus benchmark.
- Preserve exact snapshot IDs, signed lines, sportsbook IDs, and timestamps for traceability.
- Prevent look-ahead bias in all backtesting and machine-learning workflows.