# Baseball Prediction Engine Architecture

## 1. Purpose

The Baseball Prediction Engine is responsible for producing calibrated pregame probabilities for MLB Moneyline and Totals markets.

The system must support:

* Reproducible historical training datasets
* Point-in-time-safe feature generation
* Walk-forward model evaluation
* Pregame inference using the same feature definitions used during training
* Comparison between model probabilities and sportsbook market probabilities
* Model, feature, and dataset versioning
* Future expansion without redesigning the core data pipeline

The initial MVP is intentionally limited to:

1. MLB Moneyline
2. MLB Totals

The following markets and capabilities are deferred:

* Run Line refinement
* First Five Innings
* Team Totals
* Player Props
* NFL modeling
* Dashboards
* Automated wagering
* Advanced lineup simulation
* Batter-versus-pitcher modeling

---

## 2. Architectural Principles

### 2.1 Point-in-Time Correctness

Every historical feature must represent only information that was available before the prediction cutoff time.

For every generated feature:

```text
source_record_time <= feature_cutoff_time
```

The system must not use:

* Final game results as input features
* Postgame statistics
* Closing odds for models intended to run earlier
* Confirmed lineups published after the prediction cutoff
* Weather observations recorded after the prediction cutoff
* Season-ending aggregates when reconstructing earlier games

Point-in-time correctness is a mandatory requirement, not an optional optimization.

### 2.2 Reproducibility

The same raw inputs, feature definitions, cutoff time, and software version must produce the same training dataset.

Every training dataset must record:

* Dataset version
* Feature version
* Target version
* Prediction context
* Historical date range
* Build parameters
* Row count
* Feature count
* Dataset storage location
* Dataset checksum or hash
* Creation timestamp

### 2.3 Separation of Responsibilities

The prediction system will be divided into distinct layers:

```text
Raw Source Data
        ↓
Normalized Baseball Data
        ↓
Daily Historical Aggregates
        ↓
Point-in-Time Game Feature Snapshots
        ↓
Versioned Training Datasets
        ↓
Trained Models
        ↓
Pregame Predictions
        ↓
Market Comparison and Bet Evaluation
```

Models must not directly query raw data.

Models consume versioned training datasets and game feature snapshots.

### 2.4 Training and Inference Consistency

Historical training features and live pregame features must be built using the same feature definitions and transformation logic.

Separate implementations for training and live predictions should be avoided because they create training-serving skew.

### 2.5 Probability Quality Before Profitability

The primary objective is to produce accurate and calibrated probabilities.

Initial model evaluation must prioritize:

* Log loss
* Brier score
* Calibration
* Out-of-sample stability
* Walk-forward performance

Betting ROI, Expected Value, and Closing Line Value remain important downstream measures, but they must not replace probability-quality evaluation.

### 2.6 Baseball and Market Information Must Remain Distinguishable

The initial prediction model will be a baseball-only model.

Sportsbook prices, consensus probabilities, and line movement will not be included as model inputs during the first phase.

This allows the project to measure whether baseball-derived information provides value independently of the betting market.

Later model categories may include:

* Baseball-only model
* Market-only baseline
* Baseball-plus-market model

These models must remain independently identifiable and evaluable.

---

## 3. Prediction Context

The initial supported prediction context will be:

```text
PREGAME_60_MINUTES
```

The intended feature cutoff is approximately 60 minutes before scheduled first pitch.

This context is selected because it should provide access to:

* Starting pitcher information
* Most confirmed starting lineups
* Useful weather forecasts
* Current bullpen availability estimates
* Recent market information for downstream evaluation
* Enough time to generate and review predictions before first pitch

Each feature snapshot must include:

* Canonical game ID
* Scheduled start time
* Prediction context
* Feature cutoff time
* Feature version
* Source manifest
* Creation timestamp

Future prediction contexts may include:

* Opening market
* Morning of game
* Three hours before first pitch
* Ten minutes before first pitch

Features from different prediction contexts must never be mixed without explicit modeling and validation.

---

## 4. Prediction Targets

## 4.1 Moneyline

The Moneyline model will predict:

```text
P(home_team_wins)
```

Target definition:

```text
home_win = 1 when home_score > away_score
home_win = 0 when home_score < away_score
```

The away-team probability is:

```text
P(away_team_wins) = 1 - P(home_team_wins)
```

Games excluded from the initial Moneyline training dataset:

* Cancelled games
* Postponed games without a final result
* Suspended games without a finalized result
* Spring Training games
* Exhibition games
* All-Star games
* Games with unresolved canonical mappings
* Games missing required feature data
* Historical shortened doubleheader games unless separately modeled

The Moneyline model must output probabilities rather than only classifications.

## 4.2 Totals

The Totals model should estimate the underlying run environment rather than directly predicting only an Over or Under result.

Preferred outputs:

```text
expected_home_runs
expected_away_runs
expected_total_runs
```

The model or downstream distribution layer should then estimate:

```text
P(total_runs > market_total)
P(total_runs < market_total)
P(total_runs = market_total)
```

This approach allows the same run model to evaluate multiple sportsbook totals such as:

* 7.5
* 8.0
* 8.5
* 9.0
* 9.5

Initial Totals targets:

```text
home_runs
away_runs
total_runs
```

A binary Over or Under result will be derived only when a valid historical market line is available.

---

## 5. Historical Data Domains

The prediction engine requires historical data from the following domains.

## 5.1 Game and Schedule Context

Required data:

* Canonical game ID
* MLB source game ID
* Season
* Game date
* Scheduled start time
* Actual start time
* Home team
* Away team
* Venue
* Game type
* Doubleheader indicator
* Doubleheader game number
* Day or night designation
* Final home score
* Final away score
* Innings played
* Extra-innings indicator
* Previous game date
* Previous game venue
* Series position

Derived features may include:

* Rest days
* Games played during prior 3 days
* Games played during prior 7 days
* Games played during prior 14 days
* Travel distance
* Time-zone change
* Same-day doubleheader status
* Previous-day extra-innings status
* Consecutive game count

## 5.2 Starting Pitchers

Required identity and status data:

* MLB player ID
* Canonical player ID
* Pitcher name
* Throwing hand
* Probable starter status
* Confirmed starter status
* Starter announcement timestamp
* Starter confirmation timestamp
* Starter replacement history

Required historical pitcher information:

* Games started
* Innings pitched
* Batters faced
* Pitch count
* Strikeout rate
* Walk rate
* Home-run rate
* Ground-ball rate
* Fly-ball rate
* Hard-hit rate
* Barrel rate
* Average exit velocity allowed
* wOBA allowed
* xwOBA allowed
* ERA
* FIP or FIP components
* xERA
* Fastball velocity
* Pitch mix
* Days of rest
* Recent workload
* Platoon splits

Candidate historical windows:

* Last 3 starts
* Last 5 starts
* Last 30 days
* Season to date
* Prior season
* Multi-season baseline

Recent results must be shrunk toward larger historical samples to reduce noise.

## 5.3 Team Offense

Required team offense data:

* Plate appearances
* Runs per game
* On-base percentage
* Slugging percentage
* Isolated power
* wOBA
* xwOBA
* Strikeout rate
* Walk rate
* Hard-hit rate
* Barrel rate
* Average exit velocity
* Ground-ball rate
* Fly-ball rate
* Performance against left-handed pitching
* Performance against right-handed pitching

Candidate historical windows:

* Last 7 days
* Last 14 days
* Last 30 days
* Season to date
* Prior season
* Multi-season baseline

Team offense should be matched to the opposing starting pitcher's throwing hand.

## 5.4 Bullpen

Required bullpen data:

* Bullpen innings during prior 1 day
* Bullpen innings during prior 3 days
* Bullpen innings during prior 7 days
* Bullpen pitches during prior 1 day
* Bullpen pitches during prior 3 days
* Relievers used during the previous game
* Relievers used on consecutive days
* Reliever appearance frequency
* Strikeout rate
* Walk rate
* Home-run rate
* ERA
* FIP or FIP components
* wOBA allowed
* xwOBA allowed
* Hard-hit rate
* Estimated bullpen quality
* Estimated available bullpen quality
* Estimated bullpen fatigue

General bullpen quality and game-specific bullpen availability must remain separate concepts.

## 5.5 Venue and Run Environment

Required data:

* Venue ID
* Venue name
* Roof type
* Indoor or outdoor status
* Elevation
* Multi-season run factor
* Multi-season home-run factor
* Handedness-specific home-run factors when supported
* League runs per game
* Season run environment
* Relevant rules-era indicators

Park factors should use adequate historical samples and shrinkage toward league average.

## 5.6 Weather

Required weather information:

* Forecast timestamp
* Forecasted game-time temperature
* Humidity
* Wind speed
* Wind direction
* Barometric pressure when available
* Precipitation probability
* Roof status
* Weather source

Historical training must use the forecast that existed before the prediction cutoff rather than final observed weather.

## 5.7 Lineups

Lineup information will be treated as an enhancement rather than a blocker for the first baseline model.

Future lineup data may include:

* Confirmed starting lineup
* Lineup confirmation timestamp
* Expected plate appearances
* Batter handedness
* Player-level offensive projections
* Lineup quality against pitcher handedness
* Missing regular starters
* Difference between confirmed and typical lineup quality

The first model may use team-level offense against pitcher handedness without requiring confirmed lineup projections.

## 5.8 Market Data

Market information is required for evaluation and bet selection but is not part of the initial baseball-only feature set.

Relevant market data includes:

* Opening Moneyline
* Current Moneyline
* Closing Moneyline
* Opening total
* Current total
* Closing total
* No-vig probabilities
* Consensus probabilities
* Sportsbook dispersion
* Line movement
* Snapshot timestamp

Market data must be joined using the same prediction cutoff rules as baseball features.

Closing prices may be used for CLV evaluation but may not be used as features for an earlier prediction context.

---

## 6. Storage Architecture

## 6.1 PostgreSQL

PostgreSQL will store:

* Canonical entities
* Games
* Teams
* Players
* Starting pitcher assignments
* Feature metadata
* Daily aggregated baseball features
* Game feature snapshots
* Dataset registry records
* Model registry records
* Predictions
* Market comparisons

## 6.2 Parquet

Parquet files will store:

* High-volume raw Statcast data
* Intermediate processed datasets
* Versioned training datasets
* Large analytical exports

Recommended partitioning:

```text
data/raw/statcast/season=YYYY/month=MM/
```

Training dataset paths:

```text
data/training/moneyline/<dataset_version>/
data/training/totals/<dataset_version>/
```

## 6.3 Model Artifacts

Serialized model artifacts should be stored outside the source package:

```text
artifacts/models/moneyline/
artifacts/models/totals/
```

Each artifact must be traceable to:

* Model version
* Dataset version
* Feature version
* Source code commit
* Training parameters
* Validation metrics

Raw data, generated datasets, and model binaries should not be committed to Git unless they are intentionally small test fixtures.

---

## 7. Feature Store Design

The project will use two feature representations.

## 7.1 Domain Aggregate Tables

Strongly typed domain tables will store reusable historical aggregates such as:

* Pitcher daily features
* Team offense daily features
* Team bullpen daily features
* Venue factors
* Weather snapshots

These tables support validation, inspection, and point-in-time joins.

## 7.2 Game Feature Snapshots

A game feature snapshot is a frozen representation of all model inputs available for one game and one prediction context.

Conceptual identity:

```text
game_id
prediction_context
feature_cutoff_time
feature_version
```

The snapshot must record:

* Source manifest
* Starting pitchers used
* Team offense inputs
* Starting pitcher inputs
* Bullpen inputs
* Schedule inputs
* Venue inputs
* Weather inputs
* Lineup inputs when available
* Missing-data indicators
* Feature reliability indicators

The snapshot must be immutable after creation. Corrections should produce a new feature version rather than silently changing an existing model input record.

---

## 8. Feature Definitions and Versioning

Every model feature must be documented in the feature dictionary.

Each feature definition must include:

* Feature name
* Description
* Domain
* Entity
* Data source
* Data type
* Unit
* Historical window
* Prediction context
* Cutoff rule
* Minimum sample requirement
* Missing-value policy
* Fallback hierarchy
* Transformation
* Supported model
* Feature version
* Leakage risk
* Validation requirement

Feature versions will use identifiers such as:

```text
baseball_features_v1
baseball_features_v2
```

Any change to a feature's meaning requires a feature-version change.

Examples of changes requiring a new version:

* Changing a rolling window
* Changing a fallback rule
* Changing minimum sample requirements
* Changing a source
* Changing shrinkage behavior
* Correcting a point-in-time bug
* Adding or removing model features
* Changing a feature transformation

---

## 9. Missing Data and Sample Reliability

Early-season and low-sample conditions must be handled explicitly.

Recommended fallback hierarchy:

```text
Current rolling sample
        ↓
Current season sample
        ↓
Prior MLB season
        ↓
Multi-season MLB history
        ↓
League or role average
```

Features should use shrinkage rather than abrupt transitions whenever practical.

Relevant reliability fields may include:

* Sample plate appearances
* Sample batters faced
* Sample innings
* Sample games
* Current-season weight
* Prior-season weight
* Feature reliability score
* Rookie indicator
* MLB debut indicator
* Missing-data indicator

The model must be able to distinguish between:

* A league-average feature supported by a large sample
* A league-average fallback caused by missing information

---

## 10. Training Dataset Design

## 10.1 Moneyline Dataset

The Moneyline dataset will contain one row per eligible game.

Required identifiers:

* Game ID
* Game date
* Season
* Scheduled start time
* Feature cutoff time
* Prediction context
* Feature version
* Dataset version

Feature groups:

* Home and away schedule context
* Home and away offense
* Home and away starting pitchers
* Home and away bullpens
* Venue
* Weather
* Lineup features when available
* Feature differences
* Reliability and missing-data indicators

Target:

```text
home_win
```

Both team-specific and difference features may be included.

Example:

```text
home_starter_xwoba_30d
away_starter_xwoba_30d
starter_xwoba_difference_30d
```

## 10.2 Totals Dataset

The Totals dataset will contain one row per eligible game.

Feature groups:

* Home offense
* Away offense
* Home starting pitcher
* Away starting pitcher
* Home bullpen
* Away bullpen
* Venue
* Weather
* Schedule and fatigue
* Lineup information when available
* Season run environment

Targets:

```text
home_runs
away_runs
total_runs
```

Historical sportsbook totals may be attached for evaluation, but the underlying run model should not require a market total as a training target.

---

## 11. Validation Strategy

Random train-test splitting is prohibited for primary model evaluation.

All validation must preserve chronological order.

Initial recommended split:

```text
Training: 2018 through 2023
Validation: 2024
Test: 2025
Forward evaluation: 2026
```

Walk-forward evaluation should also be supported:

```text
Train through 2021 → evaluate 2022
Train through 2022 → evaluate 2023
Train through 2023 → evaluate 2024
Train through 2024 → evaluate 2025
```

No preprocessing transformation may be fit using validation or test data.

This includes:

* Imputation values
* Feature scaling
* Categorical encodings
* Calibration models
* Feature selection
* Hyperparameter selection

## 11.1 Moneyline Metrics

Primary metrics:

* Log loss
* Brier score
* Calibration error
* Calibration plots

Secondary metrics:

* ROC AUC
* Accuracy
* Precision by probability band
* Predicted probability distribution
* Performance by season
* Performance by month
* Performance by favorite and underdog range

Betting metrics:

* ROI
* Units won
* Maximum drawdown
* Expected Value threshold performance
* Closing Line Value
* Bet count
* Average price
* Average model edge

## 11.2 Totals Metrics

Primary metrics:

* Mean absolute error
* Root mean squared error
* Distributional deviance
* Over-probability calibration
* Under-probability calibration

Secondary analysis:

* Error by market total
* Error by venue
* Error by temperature range
* Error by wind conditions
* Error by starting pitcher quality
* Error by bullpen fatigue
* Error by predicted run environment

Betting metrics:

* ROI
* Units won
* Maximum drawdown
* Expected Value threshold performance
* Closing Line Value
* Push rate
* Performance by total line

---

## 12. Initial Model Roadmap

## 12.1 Data Foundation

Deliverables:

1. Canonical player identity support
2. Starting pitcher history
3. Historical Statcast ingestion
4. Team offense daily aggregates
5. Starting pitcher daily aggregates
6. Bullpen daily aggregates
7. Venue factors
8. Weather snapshots
9. Point-in-time feature builder
10. Feature snapshot validation
11. Versioned training dataset generation

Completion requirement:

```text
One reproducible, point-in-time-safe feature row can be generated for every eligible historical game.
```

## 12.2 Moneyline Baseline

Model sequence:

1. Home-team historical win-rate baseline
2. Logistic regression
3. Gradient-boosted tree model
4. Probability calibration
5. Walk-forward evaluation
6. Market comparison
7. EV and CLV analysis

The logistic regression baseline is required even if a more complex model is expected to outperform it.

It provides:

* Interpretability
* Directionality checks
* Leakage detection
* Calibration benchmark
* Complexity benchmark

## 12.3 Moneyline Production Evaluation

Deliverables:

* Stored pregame predictions
* Prediction versioning
* Market-price matching
* EV calculation
* CLV tracking
* Probability-band reporting
* Feature drift monitoring
* Prediction performance monitoring
* Forward-sample evaluation

## 12.4 Totals Baseline

Model sequence:

1. League-average run baseline
2. Park-adjusted run baseline
3. Poisson regression baseline
4. Negative Binomial model
5. Gradient-boosted run regression
6. Run-distribution calibration
7. Over and Under probability calculation
8. Market comparison
9. Walk-forward evaluation

Expected outputs:

```text
expected_home_runs
expected_away_runs
expected_total_runs
over_probability
under_probability
push_probability
```

## 12.5 Future Enhancements

Enhancements will be considered only after the baseline models and evaluation pipeline are stable.

Potential enhancements:

* Confirmed lineup projections
* Individual batter aggregation
* Pitch-type matchup features
* Batter skill against pitcher arsenals
* Advanced bullpen availability
* Umpire effects
* Injury and transaction intelligence
* Market-assisted models
* Model ensembles
* Run Line models
* First Five models
* Team Totals
* Player Props
* NFL expansion
* Dashboards

---

## 13. Testing Requirements

The feature system must include tests for:

* No source record after the cutoff time
* Correct rolling-window boundaries
* No same-game statistics in features
* Correct starting pitcher as of cutoff
* Correct team handedness matchup
* Correct rest-day calculation
* Correct bullpen workload calculation
* Correct game and player mappings
* Deterministic feature generation
* Stable dataset row counts
* Duplicate prevention
* Missing-data fallback behavior
* Dataset checksum stability
* Training and inference transformation consistency

At least one test should intentionally introduce future information and confirm that the pipeline rejects or excludes it.

---

## 14. Initial Scope Boundaries

The first feature version should favor a limited set of well-defined features over a very large set of experimental statistics.

Target initial feature count:

```text
Approximately 40 to 80 model features
```

The initial system should not depend on:

* Batter-versus-pitcher history
* Proprietary projection systems
* Complex neural networks
* Automated hyperparameter optimization
* Real-time injury news parsing
* Perfect reliever-role classification
* Full minor-league translations
* Automated betting execution

These may be added later only when they provide measurable value.

---

## 15. Development Milestones

### Milestone 1: Architecture and Feature Definitions

* Complete architecture document
* Complete feature dictionary
* Confirm historical sources
* Confirm prediction context
* Confirm target definitions

### Milestone 2: Historical Baseball Data Foundation

* Add required database migrations
* Add player identities
* Add starter assignments
* Add raw Statcast ingestion
* Add daily aggregate builders
* Add point-in-time validation

### Milestone 3: Moneyline Training Dataset

* Assemble feature snapshots
* Generate Moneyline dataset version 1
* Validate targets and exclusions
* Produce dataset quality report

### Milestone 4: Moneyline Baseline Model

* Train naive baseline
* Train logistic regression
* Train boosted-tree challenger
* Evaluate chronologically
* Calibrate probabilities
* Store artifacts and metrics

### Milestone 5: Moneyline Market Evaluation

* Match historical odds
* Calculate model edge
* Run betting simulations
* Evaluate EV thresholds
* Evaluate CLV

### Milestone 6: Totals Training Dataset

* Generate team-run and total-run targets
* Add weather and park features
* Validate scoring distributions

### Milestone 7: Totals Baseline Model

* Train run baselines
* Train count-based models
* Train nonlinear challenger
* Generate total-run distributions
* Evaluate Over, Under, and Push probabilities

---

## 16. Definition of Success

The Baseball Prediction Engine foundation is successful when:

* Historical features are point-in-time safe
* Dataset generation is deterministic
* Every model is traceable to its data and feature definitions
* Training and live prediction use the same feature logic
* Moneyline probabilities are calibrated out of sample
* Totals predictions represent a valid run distribution
* Market comparison occurs after baseball probability generation
* Backtests use prices available at the defined prediction time
* Future feature additions do not require redesigning the core architecture

The immediate product is not the machine-learning algorithm.

The immediate product is a reliable historical feature and dataset pipeline from which credible predictive models can be built.
