# SportsModel Roadmap

## Vision

SportsModel is intended to become a professional sports market research platform demonstrating modern software engineering, data engineering, statistical analysis, and machine learning practices.

The long-term objective is not simply predicting games, but building a reproducible analytics platform capable of researching betting strategies using historical market data.

---

# NFL Program Status

**NFL Phase 2: COMPLETE**

The first frozen NFL Moneyline baseline and its one-time 2025 historical
holdout result are recorded in
[`docs/architecture/nfl_phase_2_closeout.md`](docs/architecture/nfl_phase_2_closeout.md).
The 2025 season is now exposed and is not an untouched holdout for subsequent
model development.

Next: **NFL Phase 3A — Early-Season Coverage**. Design and validate a separate
point-in-time-safe strategy for games where one or both teams have fewer than
three current-season prior games, without altering the frozen Phase 2
baseline. Phase 3A is not implemented yet.

---

# Version 1.0 — Analytics Platform ✅

Completed

### Infrastructure

- Python project structure
- PostgreSQL database
- Repository pattern
- Automated migrations
- Feature branch workflow

### Data

- Historical MLB ingestion
- Live Odds API ingestion
- Sportsbook normalization
- Historical game linking

### Analytics

- Complete Market Builder
- Line Movement
- Probability utilities
- No-Vig Engine
- Consensus Engine
- Expected Value Engine
- Market Timeline Engine
- Closing Line Value Engine

### Strategy

- Positive Expected Value Strategy

### Quality

- Unit testing
- Live validation scripts
- Immutable domain models
- Clean architecture

Current status:

- **41 automated tests passing**

---

# Version 1.1 — Research & Backtesting

Planned

### Research

- Bet candidate research layer
- Historical wager settlement
- Backtesting engine
- Performance reporting

Metrics:

- ROI
- Win %
- Units Won
- Drawdown
- Closing Line Value statistics

---

# Version 2.0 — Machine Learning

Planned

### Feature Store

- Expected Value
- Closing Line Value
- Line Movement
- Reverse Line Movement
- Steam Detection
- Consensus Features
- Historical Team Metrics

### Machine Learning

- Model training
- Cross validation
- Hyperparameter tuning
- Model evaluation

---

# Future Goals

Potential future enhancements include:

- Additional sportsbooks
- Additional sports
- Automated data collection
- Dashboarding
- REST API
- Cloud deployment
- Scheduled ingestion
- Strategy optimization
- Kelly staking
- Monte Carlo bankroll simulation

---

# Engineering Goals

Throughout development the project prioritizes:

- Clean Architecture
- Testability
- Maintainability
- Reproducibility
- Statistical correctness
- Avoidance of look-ahead bias
