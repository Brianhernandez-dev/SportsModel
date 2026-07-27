# Baseball Feature Dictionary

## 1. Purpose

This document defines every feature used by the Baseball Prediction Engine.

Each feature must specify:

* Name
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
* Intended model
* Feature version
* Leakage risk
* Validation requirement

No feature may be added to a training dataset until it is documented here.

---

## 2. Feature Naming Standard

Feature names should use lowercase snake case.

Recommended pattern:

```text
<entity>_<metric>_<window>_<split>
```

Examples:

```text
home_starter_xwoba_allowed_30d
away_offense_woba_season_vs_lhp
home_bullpen_innings_3d
starter_xwoba_difference_30d
```

Standard entity prefixes:

```text
home_
away_
home_starter_
away_starter_
home_offense_
away_offense_
home_bullpen_
away_bullpen_
game_
venue_
weather_
```

Difference features should use:

```text
<metric>_difference
```

The sign convention is:

```text
home value - away value
```

---

## 3. Prediction Context

Initial prediction context:

```text
PREGAME_60_MINUTES
```

All features in `baseball_features_v1` must be available at or before the feature cutoff time.

Default cutoff rule:

```text
source_record_time <= feature_cutoff_time
```

Statistics calculated from completed games must only use games completed before the current game's feature cutoff.

---

## 4. Initial Feature Version

```text
Feature version: baseball_features_v1
Target markets: Moneyline and Totals
Target feature count: 40 to 80
```

The initial feature set should favor stable, explainable features over large numbers of highly correlated statistics.

---

# 5. Game and Schedule Features

## game_is_home_doubleheader_game

| Attribute            | Definition                                                    |
| -------------------- | ------------------------------------------------------------- |
| Description          | Indicates whether the game is part of a same-day doubleheader |
| Domain               | Schedule                                                      |
| Entity               | Game                                                          |
| Data source          | MLB schedule data                                             |
| Data type            | Boolean                                                       |
| Unit                 | 0 or 1                                                        |
| Historical window    | Current game                                                  |
| Prediction context   | PREGAME_60_MINUTES                                            |
| Cutoff rule          | Schedule status known by cutoff                               |
| Minimum sample       | Not applicable                                                |
| Missing-value policy | Default to 0 only when schedule confirms no doubleheader      |
| Fallback             | Null when schedule status is unresolved                       |
| Transformation       | Boolean encoding                                              |
| Intended model       | Moneyline and Totals                                          |
| Feature version      | baseball_features_v1                                          |
| Leakage risk         | Low                                                           |
| Validation           | Compare against official game and doubleheader metadata       |

## game_number_in_doubleheader

| Attribute            | Definition                                                       |
| -------------------- | ---------------------------------------------------------------- |
| Description          | Indicates whether the game is Game 1 or Game 2 of a doubleheader |
| Domain               | Schedule                                                         |
| Entity               | Game                                                             |
| Data source          | MLB schedule data                                                |
| Data type            | Integer                                                          |
| Unit                 | 0, 1, or 2                                                       |
| Historical window    | Current game                                                     |
| Prediction context   | PREGAME_60_MINUTES                                               |
| Cutoff rule          | Schedule status known by cutoff                                  |
| Minimum sample       | Not applicable                                                   |
| Missing-value policy | 0 for non-doubleheader games                                     |
| Fallback             | Null when unresolved                                             |
| Transformation       | None                                                             |
| Intended model       | Moneyline and Totals                                             |
| Feature version      | baseball_features_v1                                             |
| Leakage risk         | Low                                                              |
| Validation           | Compare against official game number                             |

## game_is_day

| Attribute            | Definition                                                                         |
| -------------------- | ---------------------------------------------------------------------------------- |
| Description          | Indicates whether the game is officially designated as a day game                  |
| Domain               | Schedule                                                                           |
| Entity               | Game                                                                               |
| Data source          | MLB schedule data                                                                  |
| Data type            | Boolean                                                                            |
| Unit                 | 0 or 1                                                                             |
| Historical window    | Current game                                                                       |
| Prediction context   | PREGAME_60_MINUTES                                                                 |
| Cutoff rule          | Scheduled game designation known by cutoff                                         |
| Minimum sample       | Not applicable                                                                     |
| Missing-value policy | Null                                                                               |
| Fallback             | Derive from local scheduled start time only if official designation is unavailable |
| Transformation       | Boolean encoding                                                                   |
| Intended model       | Moneyline and Totals                                                               |
| Feature version      | baseball_features_v1                                                               |
| Leakage risk         | Low                                                                                |
| Validation           | Compare derived and official day/night classifications                             |

## home_rest_days

| Attribute            | Definition                                                                     |
| -------------------- | ------------------------------------------------------------------------------ |
| Description          | Full calendar days since the home team's previous completed game               |
| Domain               | Schedule                                                                       |
| Entity               | Home team                                                                      |
| Data source          | Canonical games and results                                                    |
| Data type            | Integer                                                                        |
| Unit                 | Days                                                                           |
| Historical window    | Previous completed game                                                        |
| Prediction context   | PREGAME_60_MINUTES                                                             |
| Cutoff rule          | Only games completed before cutoff                                             |
| Minimum sample       | One prior completed game                                                       |
| Missing-value policy | Null                                                                           |
| Fallback             | Use capped league-average rest value for model input and add missing indicator |
| Transformation       | Cap at 5 days                                                                  |
| Intended model       | Moneyline and Totals                                                           |
| Feature version      | baseball_features_v1                                                           |
| Leakage risk         | Medium                                                                         |
| Validation           | Confirm current game is never included                                         |

## away_rest_days

| Attribute            | Definition                                                                     |
| -------------------- | ------------------------------------------------------------------------------ |
| Description          | Full calendar days since the away team's previous completed game               |
| Domain               | Schedule                                                                       |
| Entity               | Away team                                                                      |
| Data source          | Canonical games and results                                                    |
| Data type            | Integer                                                                        |
| Unit                 | Days                                                                           |
| Historical window    | Previous completed game                                                        |
| Prediction context   | PREGAME_60_MINUTES                                                             |
| Cutoff rule          | Only games completed before cutoff                                             |
| Minimum sample       | One prior completed game                                                       |
| Missing-value policy | Null                                                                           |
| Fallback             | Use capped league-average rest value for model input and add missing indicator |
| Transformation       | Cap at 5 days                                                                  |
| Intended model       | Moneyline and Totals                                                           |
| Feature version      | baseball_features_v1                                                           |
| Leakage risk         | Medium                                                                         |
| Validation           | Confirm current game is never included                                         |

## home_games_played_7d

| Attribute            | Definition                                                                        |
| -------------------- | --------------------------------------------------------------------------------- |
| Description          | Number of completed games played by the home team during the preceding seven days |
| Domain               | Schedule                                                                          |
| Entity               | Home team                                                                         |
| Data source          | Canonical games and results                                                       |
| Data type            | Integer                                                                           |
| Unit                 | Games                                                                             |
| Historical window    | 7 days                                                                            |
| Prediction context   | PREGAME_60_MINUTES                                                                |
| Cutoff rule          | Completed before cutoff                                                           |
| Minimum sample       | Not applicable                                                                    |
| Missing-value policy | 0 when no games were played                                                       |
| Fallback             | None                                                                              |
| Transformation       | None                                                                              |
| Intended model       | Moneyline and Totals                                                              |
| Feature version      | baseball_features_v1                                                              |
| Leakage risk         | Medium                                                                            |
| Validation           | Test exact inclusive and exclusive date boundaries                                |

## away_games_played_7d

| Attribute            | Definition                                                                        |
| -------------------- | --------------------------------------------------------------------------------- |
| Description          | Number of completed games played by the away team during the preceding seven days |
| Domain               | Schedule                                                                          |
| Entity               | Away team                                                                         |
| Data source          | Canonical games and results                                                       |
| Data type            | Integer                                                                           |
| Unit                 | Games                                                                             |
| Historical window    | 7 days                                                                            |
| Prediction context   | PREGAME_60_MINUTES                                                                |
| Cutoff rule          | Completed before cutoff                                                           |
| Minimum sample       | Not applicable                                                                    |
| Missing-value policy | 0 when no games were played                                                       |
| Fallback             | None                                                                              |
| Transformation       | None                                                                              |
| Intended model       | Moneyline and Totals                                                              |
| Feature version      | baseball_features_v1                                                              |
| Leakage risk         | Medium                                                                            |
| Validation           | Test exact inclusive and exclusive date boundaries                                |

## home_previous_game_extra_innings

| Attribute            | Definition                                                                      |
| -------------------- | ------------------------------------------------------------------------------- |
| Description          | Indicates whether the home team's previous completed game went to extra innings |
| Domain               | Schedule                                                                        |
| Entity               | Home team                                                                       |
| Data source          | Canonical game results                                                          |
| Data type            | Boolean                                                                         |
| Unit                 | 0 or 1                                                                          |
| Historical window    | Previous completed game                                                         |
| Prediction context   | PREGAME_60_MINUTES                                                              |
| Cutoff rule          | Previous game completed before cutoff                                           |
| Minimum sample       | One prior completed game                                                        |
| Missing-value policy | Null                                                                            |
| Fallback             | 0 with missing indicator                                                        |
| Transformation       | Boolean encoding                                                                |
| Intended model       | Moneyline and Totals                                                            |
| Feature version      | baseball_features_v1                                                            |
| Leakage risk         | Medium                                                                          |
| Validation           | Ensure correct previous team game is selected                                   |

## away_previous_game_extra_innings

| Attribute            | Definition                                                                      |
| -------------------- | ------------------------------------------------------------------------------- |
| Description          | Indicates whether the away team's previous completed game went to extra innings |
| Domain               | Schedule                                                                        |
| Entity               | Away team                                                                       |
| Data source          | Canonical game results                                                          |
| Data type            | Boolean                                                                         |
| Unit                 | 0 or 1                                                                          |
| Historical window    | Previous completed game                                                         |
| Prediction context   | PREGAME_60_MINUTES                                                              |
| Cutoff rule          | Previous game completed before cutoff                                           |
| Minimum sample       | One prior completed game                                                        |
| Missing-value policy | Null                                                                            |
| Fallback             | 0 with missing indicator                                                        |
| Transformation       | Boolean encoding                                                                |
| Intended model       | Moneyline and Totals                                                            |
| Feature version      | baseball_features_v1                                                            |
| Leakage risk         | Medium                                                                          |
| Validation           | Ensure correct previous team game is selected                                   |

---

# 6. Starting Pitcher Features

The first Moneyline and Totals models should use starting-pitcher skill, workload, handedness, and sample reliability.

The initial design should avoid over-reliance on ERA or very short recent-start windows.

Candidate starting-pitcher features for `baseball_features_v1`:

```text
home_starter_throws_left
away_starter_throws_left

home_starter_days_rest
away_starter_days_rest

home_starter_batters_faced_season
away_starter_batters_faced_season

home_starter_strikeout_rate_season
away_starter_strikeout_rate_season

home_starter_walk_rate_season
away_starter_walk_rate_season

home_starter_home_run_rate_season
away_starter_home_run_rate_season

home_starter_xwoba_allowed_season
away_starter_xwoba_allowed_season

home_starter_xwoba_allowed_30d
away_starter_xwoba_allowed_30d

home_starter_avg_fastball_velocity_30d
away_starter_avg_fastball_velocity_30d

home_starter_pitch_count_7d
away_starter_pitch_count_7d

home_starter_feature_reliability
away_starter_feature_reliability
```

Difference features:

```text
starter_strikeout_rate_difference
starter_walk_rate_difference
starter_home_run_rate_difference
starter_xwoba_allowed_difference
starter_fastball_velocity_difference
starter_reliability_difference
```

Detailed definitions for these features will be added after confirming the historical data source and the precise aggregation rules.

---

# 7. Team Offense Features

The first model should represent team offense against the opposing starting pitcher's handedness.

Candidate offense features:

```text
home_offense_plate_appearances_season_vs_hand
away_offense_plate_appearances_season_vs_hand

home_offense_woba_season_vs_hand
away_offense_woba_season_vs_hand

home_offense_xwoba_season_vs_hand
away_offense_xwoba_season_vs_hand

home_offense_strikeout_rate_season_vs_hand
away_offense_strikeout_rate_season_vs_hand

home_offense_walk_rate_season_vs_hand
away_offense_walk_rate_season_vs_hand

home_offense_isolated_power_season_vs_hand
away_offense_isolated_power_season_vs_hand

home_offense_hard_hit_rate_30d
away_offense_hard_hit_rate_30d

home_offense_barrel_rate_30d
away_offense_barrel_rate_30d

home_offense_feature_reliability
away_offense_feature_reliability
```

Difference features:

```text
offense_woba_difference
offense_xwoba_difference
offense_strikeout_rate_difference
offense_walk_rate_difference
offense_isolated_power_difference
offense_hard_hit_rate_difference
```

---

# 8. Bullpen Features

The bullpen feature set must distinguish general skill from expected availability.

Candidate bullpen features:

```text
home_bullpen_strikeout_rate_season
away_bullpen_strikeout_rate_season

home_bullpen_walk_rate_season
away_bullpen_walk_rate_season

home_bullpen_home_run_rate_season
away_bullpen_home_run_rate_season

home_bullpen_xwoba_allowed_season
away_bullpen_xwoba_allowed_season

home_bullpen_innings_1d
away_bullpen_innings_1d

home_bullpen_innings_3d
away_bullpen_innings_3d

home_bullpen_pitch_count_3d
away_bullpen_pitch_count_3d

home_bullpen_relief_appearances_2d
away_bullpen_relief_appearances_2d

home_bullpen_fatigue_score
away_bullpen_fatigue_score

home_bullpen_available_quality
away_bullpen_available_quality
```

Difference features:

```text
bullpen_xwoba_allowed_difference
bullpen_strikeout_rate_difference
bullpen_walk_rate_difference
bullpen_fatigue_difference
bullpen_available_quality_difference
```

The exact fatigue and availability formulas must be documented before implementation.

---

# 9. Venue and Environment Features

Candidate venue features:

```text
venue_run_factor
venue_home_run_factor
venue_elevation_feet
venue_is_dome
venue_roof_closed
season_league_runs_per_game
```

Park factors must:

* Use only seasons available before the target game
* Use multi-season samples
* Be shrunk toward league average
* Record the park-factor version

---

# 10. Weather Features

Candidate weather features:

```text
weather_temperature_f
weather_humidity_pct
weather_wind_speed_mph
weather_wind_out_component_mph
weather_precipitation_probability
weather_pressure
weather_is_missing
```

Weather features are expected to be more important for Totals than Moneyline.

Historical weather must represent a forecast available before the cutoff whenever possible.

Observed postgame weather must not be silently substituted for a historical pregame forecast.

---

# 11. Missing-Data Indicators

The initial feature set should include explicit indicators for material missing data:

```text
home_starter_features_missing
away_starter_features_missing
home_offense_features_missing
away_offense_features_missing
home_bullpen_features_missing
away_bullpen_features_missing
weather_is_missing
lineup_is_missing
```

Fallback values and missing indicators must both be retained.

---

# 12. Excluded Initial Features

The following features are intentionally excluded from `baseball_features_v1`:

* Batter-versus-pitcher history
* Individual batter pitch-type matchup scores
* Umpire strike-zone effects
* Injury-news sentiment
* Proprietary projection-system outputs
* Sportsbook odds
* Consensus probability
* Line movement
* Closing prices
* Public betting percentages
* Run Line-specific features
* First Five-specific features
* Player Prop features

Market information will be used downstream for evaluation and bet selection, not as input to the initial baseball-only model.

---

# 13. Open Design Decisions

The following decisions must be resolved before implementation:

1. Historical Statcast source and ingestion method
2. Historical schedule and probable-starter source
3. Historical weather source
4. Exact park-factor methodology
5. Starting-pitcher shrinkage formula
6. Team-offense shrinkage formula
7. Bullpen fatigue formula
8. Bullpen available-quality formula
9. Minimum sample thresholds
10. Rookie and debut fallback rules
11. Treatment of shortened historical doubleheaders
12. Treatment of openers and bullpen games
13. Treatment of postseason games
14. Exact historical training start year
15. Whether 2026 is excluded entirely from model fitting during initial evaluation

These decisions must be documented before the corresponding feature pipelines are written.
