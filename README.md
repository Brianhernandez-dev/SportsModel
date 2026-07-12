# SportsModel

SportsModel is a modular sports analytics platform built to collect, normalize, analyze, and research sportsbook odds using clean software architecture and reproducible analytics.

The project began as an exploration of sports betting analytics but has evolved into a professional software engineering project focused on:

- Data Engineering
- Software Architecture
- Statistical Analysis
- Automated Testing
- Reproducible Research
- Machine Learning Foundations

The long-term objective is to build a research platform capable of evaluating betting strategies using historical sportsbook data before introducing machine learning models.

---

# Current Status

**Version:** v1.0.0 – Analytics Platform

Completed:

- Live sportsbook odds ingestion
- Historical MLB game ingestion
- PostgreSQL persistence
- Repository pattern
- Automated database migrations
- Complete market normalization
- Line movement analytics
- No-vig probability calculations
- Consensus market generation
- Expected value analytics
- Market timeline analytics
- Closing line value analytics
- Positive Expected Value strategy
- Automated unit testing
- Live validation scripts

Current test suite:

- **41 passing automated tests**

---

# Architecture

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

Each component is intentionally isolated and independently testable.

---

# Project Structure

```
SportsModel/

database/
scripts/
tests/

src/
└── sportsmodel/
    ├── analysis/
    ├── backtesting/
    ├── config/
    ├── database/
    ├── ingest/
    ├── models/
    ├── strategies/
    └── utils/
```

---

# Design Principles

The project emphasizes:

- Clean Architecture
- Immutable domain models
- Repository pattern
- Pure analytics functions
- Layered design
- Automated testing
- Feature branch workflow
- Incremental development
- Reproducible analytics
- Avoidance of look-ahead bias

---

# Technology Stack

- Python
- PostgreSQL
- Docker
- pytest
- Git
- DBeaver

External data sources:

- Odds API
- MLB Stats API

---

# Current Capabilities

SportsModel currently supports:

### Data Collection

- Historical MLB games
- Live sportsbook odds
- Historical result ingestion

### Analytics

- Complete market construction
- Line movement tracking
- Probability utilities
- No-vig calculations
- Consensus probability
- Expected value analysis
- Market timelines
- Closing line value

### Strategy

- Positive Expected Value candidate selection

---

# Roadmap

## Version 1.1

Research & Simulation

- Historical wager settlement
- Backtesting engine
- ROI reporting
- Performance statistics

## Version 2.0

Machine Learning

- Feature store
- Model training
- Strategy optimization
- Automated prediction

Future enhancements include:

- Additional sportsbooks
- Additional sports
- REST API
- Dashboard
- Cloud deployment
- Automated scheduling

---

# Why This Project Exists

SportsModel was designed as a long-term software engineering project demonstrating:

- Object-oriented design
- Data engineering
- Database architecture
- Statistical modeling
- Automated testing
- Version control workflow
- Machine learning preparation

Although the project operates in the sports analytics domain, the engineering principles are broadly applicable to financial analytics, forecasting systems, enterprise data platforms, and machine learning pipelines.

---

# License

This project is currently intended for personal research and portfolio purposes.