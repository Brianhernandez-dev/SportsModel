# SportsModel Architecture

## Overview

SportsModel is a modular sports analytics platform focused on collecting, normalizing, and analyzing sportsbook odds data.

The project emphasizes:

- Clean Architecture
- Immutable domain models
- Automated testing
- Reproducible analytics
- Data engineering best practices
- Future machine learning integration

The current implementation focuses on MLB markets while remaining extensible to additional sports.

---

# High-Level Architecture

```
Odds API
    │
    ▼
Market Snapshots
    │
    ▼
Complete Market Builder
    │
    ▼
No-Vig Engine
    │
    ▼
Consensus Engine
    │
    ▼
Expected Value Engine
    │
    ▼
Market Timeline Engine
    │
    ▼
Closing Line Value Engine
    │
    ▼
Strategy Layer
```

Each layer has a single responsibility and operates independently of the others.

---

# Project Structure

```
src/
└── sportsmodel/
    ├── analysis/
    ├── backtesting/
    ├── config/
    ├── database/
    ├── ingest/
    ├── models/
    ├── strategies/
    ├── utils/
```

---

# Layer Responsibilities

## Ingestion

Responsible for collecting raw sportsbook and historical game data.

Current sources:

- Odds API
- MLB Stats API

Responsibilities:

- Normalize timestamps
- Normalize sportsbooks
- Persist raw snapshots
- Preserve historical data

---

## Database

Provides:

- PostgreSQL persistence
- Repository pattern
- Versioned migrations

Database logic is intentionally isolated from analytics.

---

## Analytics

Analytics engines transform sportsbook data into increasingly useful abstractions.

Current engines include:

- Complete Market Builder
- Line Movement
- Probability Utilities
- No-Vig
- Consensus Market
- Expected Value
- Market Timeline
- Closing Line Value

Each engine:

- Accepts immutable models
- Produces immutable models
- Contains no database logic
- Is independently testable

---

## Strategy Layer

Strategies consume analytics outputs and decide which betting opportunities satisfy defined criteria.

Current implementation:

- Positive Expected Value Strategy

Strategies produce immutable `BetCandidate` objects.

Strategies intentionally contain no settlement or bankroll logic.

---

## Testing

Every analytics engine includes:

- Unit tests
- Live validation scripts

Current test count:

- **41 passing tests**

Testing philosophy:

- Deterministic outputs
- Pure functions
- No external dependencies during unit testing

---

# Design Principles

The project follows several core principles:

- Immutable domain models
- Single Responsibility Principle
- Pure analytics functions
- Layered architecture
- Database isolation
- Reproducible research
- Incremental development
- Feature branch workflow

---

# Current Status

SportsModel v1.0 provides:

- Historical MLB ingestion
- Live odds ingestion
- Market normalization
- Expected value analytics
- Closing line value analytics
- Positive EV strategy generation

The next milestone introduces research, settlement, and historical backtesting.