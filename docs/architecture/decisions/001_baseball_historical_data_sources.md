# ADR 001: Baseball Historical Data Sources

* **Status:** Accepted
* **Date:** 2026-07-18
* **Feature version affected:** `baseball_features_v1`
* **Prediction context:** `PREGAME_60_MINUTES`

## Context

The Baseball Prediction Engine requires reproducible historical data for:

* MLB games and schedules
* Player identities
* Starting pitcher assignments
* Pitch-level and batted-ball events
* Team offense
* Starting pitcher performance
* Bullpen performance and workload
* Venue information
* Weather
* Historical market evaluation

The selected sources must support:

* Historical backfills
* Incremental updates
* Canonical entity matching
* Point-in-time feature generation
* Raw-data preservation
* Deterministic reprocessing
* Reasonable operational reliability
* Clear separation between source data and derived features

The first implementation must prioritize MLB Moneyline. Totals-specific data may follow after the core baseball feature pipeline is operational.

---

## Decision 1: Baseball Savant is the Primary Statcast Source

Baseball Savant will be the authoritative source for pitch-level Statcast and batted-ball data.

The source provides documented CSV fields including:

* Game date
* Game identifier
* Pitcher identifier
* Batter identifier
* Pitch type
* Release velocity
* Events
* Descriptions
* Launch speed
* Launch angle
* Estimated wOBA values
* Plate appearance and pitch context

Baseball Savant documents its downloadable Statcast fields and distinguishes Statcast-era velocity measurements from earlier PitchFX data.

### Implementation decision

The project will initially access Baseball Savant through `pybaseball`, while treating `pybaseball` as an ingestion adapter rather than the authoritative data source.

`pybaseball` exposes date-range Statcast retrieval and returns pitch-level data in a pandas DataFrame.

### Requirements

The ingestion pipeline must:

* Request data in small date ranges
* Retry transient failures
* Validate expected columns
* Record the requested date range
* Record retrieval time
* Record source and adapter versions
* Preserve raw results before aggregation
* Detect empty or incomplete responses
* Be restartable
* Avoid depending on undocumented DataFrame inference

### Storage

Raw Statcast data will be stored as Parquet:

```text
data/raw/statcast/
    season=YYYY/
        month=MM/
            statcast_YYYY-MM-DD.parquet
```

Each raw partition must have a corresponding manifest containing:

* Source
* Retrieval timestamp
* Start date
* End date
* Row count
* Column list
* File hash
* Adapter version
* Retrieval status

### Rationale

Pitch-level Statcast data is too large and too immutable to require permanent row-level storage in PostgreSQL.

PostgreSQL will store normalized entities, aggregate outputs, manifests, and feature snapshots. Parquet will store raw and processed high-volume analytical data.

---

## Decision 2: MLB Game Data Will Remain the Canonical Schedule Source

The existing MLB historical-results and canonical-game ingestion will remain the primary source for:

* Game identity
* Teams
* Scheduled start time
* Game status
* Final score
* Venue
* Game type
* Doubleheader information
* Innings played

Existing canonical game IDs will remain the central join key.

No parallel game identity system will be created for the prediction engine.

### Requirements

New baseball data must map to:

```text
games.game_id
```

Source identifiers such as MLB game IDs must remain preserved through the existing source-mapping architecture.

Rows that cannot be mapped safely must be quarantined rather than matched through weak assumptions.

---

## Decision 3: Player Identity Will Be Added as a Canonical Entity

The database will add canonical baseball-player identities.

The identity system must support:

* MLB player ID
* Full name
* Batting hand
* Throwing hand
* Primary position
* Active date range
* Source mappings

Starting pitchers, batters, and relievers will reference the same canonical player entity.

Player matching must use source IDs whenever available. Name-only matching is not acceptable as the primary strategy.

---

## Decision 4: Starting Pitchers Must Preserve Point-in-Time History

Starting pitcher assignments must not be stored as only one final value on the game.

The system must preserve:

* Probable starter
* Confirmed starter
* Source timestamp
* Recorded timestamp
* Assignment changes
* Final pitcher who started the game

This is necessary because the starter known 60 minutes before a game may differ from:

* The initially announced starter
* The eventual starter
* A value corrected after the game

Historical model reconstruction must select the most recent valid assignment available at the feature cutoff.

### MVP limitation

Reliable historical announcement timestamps may not be available for every past game.

For the first historical dataset:

* The actual starting pitcher may be used as a documented proxy.
* A field must identify that the starter was reconstructed from final game data.
* This limitation must be included in dataset metadata.
* Future live predictions must use the actual point-in-time starter assignment.

This proxy affects real-world reproducibility when late starter changes occurred. It must not be hidden.

---

## Decision 5: Daily Aggregates Will Be Calculated Internally

The model will not depend primarily on downloaded season leaderboard totals.

Daily historical aggregates will be derived from preserved event-level data.

The initial aggregate domains are:

```text
pitcher_daily_features
team_offense_daily_features
team_bullpen_daily_features
```

Each aggregate row will represent information available through a completed historical date.

Example:

```text
feature_date = 2026-07-17
```

means that the row may use games completed through July 17, but not games played on July 18.

### Rationale

Internally calculated aggregates provide:

* Exact rolling-window control
* Point-in-time correctness
* Consistent metric definitions
* Reproducibility
* Easier leakage testing
* Independence from changing leaderboard interfaces

---

## Decision 6: Park Factors Will Be Calculated Internally

Venue and park factors will be derived from historical game results and, where appropriate, batted-ball outcomes.

Initial park-factor design:

* Multi-season window
* Prior data only
* League-average normalization
* Shrinkage toward neutral
* Versioned methodology
* Separate run and home-run factors

The first version should remain deliberately simple.

Candidate initial window:

```text
Prior three completed seasons
```

For a 2025 game, the feature may use 2022–2024 data, but not final 2025 park outcomes.

In-season park information may be incorporated later through a documented weighted update.

---

## Decision 7: Weather Will Not Block the First Moneyline Model

Weather data is valuable, particularly for Totals, but historical point-in-time forecasts create a separate reconstruction problem.

The National Weather Service API provides forecasts, observations, and related weather data, while official historical observations are generally obtained through NOAA historical-data services.

Historical observations do not prove what forecast information was available 60 minutes before a game.

Therefore:

* Weather is not required for Moneyline dataset version 1.
* Weather schema support may be created during the data-foundation phase.
* Live weather snapshots should begin being collected prospectively.
* Totals model development will require a deliberate historical weather decision.

### Historical forecast candidate

Open-Meteo documents a historical forecast archive that preserves forecast-model output beginning in approximately 2021 or 2022, depending on model availability.

Open-Meteo is the leading candidate for historical Totals weather research, subject to:

* Stadium-coordinate testing
* Coverage verification
* Forecast issue-time semantics
* Rate and licensing review
* Comparison against live captured forecasts
* Reproducibility testing

### Prohibited substitution

Observed postgame weather must not be represented as though it were a pregame forecast.

If observed weather is used as an experimental proxy, the feature and dataset must state this explicitly.

---

## Decision 8: Bullpen Availability Will Begin as an Internal Approximation

Historical bullpen skill will be derived from relief appearances.

The first availability model will use:

* Relief pitches during the prior day
* Relief pitches during the prior three days
* Relief innings during the prior day
* Relief innings during the prior three days
* Appearances on consecutive days
* Number of relievers used
* Previous-game extra innings

The first Moneyline model will not attempt to perfectly identify:

* Closer roles
* Setup roles
* Manager preferences
* Injury availability
* Undisclosed rest decisions

A versioned fatigue formula will be developed after the raw relief-appearance data has been inspected.

General bullpen skill and estimated current availability must remain separate features.

---

## Decision 9: Confirmed Lineups Are Deferred From the First Baseline

Historical confirmed-lineup timestamps are difficult to reconstruct consistently.

Moneyline model version 1 will use:

* Team offense
* Opposing starter handedness
* Historical team batting performance
* Sample reliability

It will not require confirmed individual lineups.

Lineup-aware features will be added later after prospective lineup snapshots have accumulated or a reliable historical source has been established.

The database design should allow lineup snapshots without making them mandatory for the first training dataset.

---

## Decision 10: Market Data Remains Outside the Initial Baseball Feature Set

Historical sportsbook data will be used for:

* Market baselines
* EV calculations
* CLV calculations
* Bet settlement
* Backtesting

It will not be included in `baseball_features_v1`.

The first predictive comparison will eventually include:

```text
Baseball-only model
Market-only baseline
Baseball-plus-market model
```

These must be trained and evaluated separately.

---

## Decision 11: Historical Training Range Will Be 2018–2025

Initial historical scope:

```text
Training candidates: 2018 through 2025
Forward evaluation: 2026
```

Reasons:

* Stronger Statcast-era consistency
* Adequate multi-season sample
* More relevant modern pitcher and bullpen usage
* Reduced dependence on older baseball environments

The initial chronological evaluation plan remains:

```text
Training: 2018–2023
Validation: 2024
Test: 2025
Forward evaluation: 2026
```

Data availability and quality will be measured before this range is treated as final.

The pipeline must produce a coverage report by season.

---

## Decision 12: Shortened Doubleheaders and Nonstandard Games Will Be Excluded Initially

The initial datasets will exclude:

* Seven-inning doubleheader games
* Suspended games with ambiguous feature timing
* Games lacking standard final outcomes
* Spring Training
* Exhibition games
* All-Star games

Postseason games will initially be retained with an explicit postseason indicator, but performance will also be reported separately.

Openers and bullpen games will not automatically be excluded.

They must be marked using a starter-role indicator when reliable classification becomes available.

---

## Consequences

### Positive consequences

* Feature calculations remain reproducible.
* Raw source data remains preserved.
* PostgreSQL is protected from unnecessary pitch-level volume.
* The Moneyline model can proceed without waiting for perfect weather data.
* Totals-specific requirements remain visible rather than being silently approximated.
* Point-in-time limitations are explicitly documented.
* Future source replacements do not require redesigning the entire model.

### Negative consequences

* Historical backfills will require substantial storage and processing.
* `pybaseball` may require defensive handling when upstream interfaces change.
* Historical starter announcement timing may remain incomplete.
* Moneyline version 1 will not include lineup-specific information.
* Totals development will trail Moneyline because weather reconstruction is more demanding.
* Bullpen availability will begin as an approximation.

---

## Immediate Implementation Order

1. Create a Statcast ingestion proof of concept.
2. Inspect one small date range.
3. Validate required fields and identifiers.
4. Design the raw-data manifest.
5. Backfill one complete month.
6. Measure row count, file size, missingness, and retrieval stability.
7. Add canonical player tables.
8. Add starting-pitcher assignment tables.
9. Build pitcher daily aggregates.
10. Build team offense daily aggregates.
11. Build bullpen daily aggregates.
12. Generate the first point-in-time game feature snapshot.

No full 2018–2025 backfill should begin until the proof of concept and one-month validation succeed.
