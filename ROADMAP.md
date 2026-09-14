# SportsModel Roadmap

## Vision

SportsModel is a reproducible sports market research platform built around point-in-time correctness, canonical identity, source provenance, frozen analytical contracts, and independently reviewable evidence.

The roadmap distinguishes established infrastructure from work that remains gated. Repository capabilities do not by themselves authorize provider access, production execution, or historical model/market/outcome joins.

## MLB Moneyline Program

### Completed / Established

- Canonical historical and current data ingestion
- Point-in-time feature engineering and chronological model evaluation
- Frozen Moneyline model and versioned feature contract
- Pregame prediction, market capture, evaluation, paper-candidate, settlement, and audit workflows
- Read-only dashboard and operational recovery controls
- Production-facing timing, retry, schema-compatibility, and evidence-preservation safeguards

### Current / Next

- Continue prospective forward validation and production hardening
- Preserve failed or expired point-in-time workflows as evidence rather than reconstructing official history
- Evaluate model and policy behavior over meaningful prospective samples

## NFL Moneyline Program

### Completed / Established

- Historical schedule, result, and team-statistics ingestion with canonical identity and source provenance
- Point-in-time early-season and mature feature pipelines
- Frozen early-season and mature Moneyline models with deterministic routing
- Immutable forward prediction and official pregame evidence infrastructure
- Sport-safe odds identity, capture, and market-evaluation foundations
- Historical probability evidence reconstruction and package provenance architecture
- Frozen historical-market base research protocol with independent-review and freeze records

The historical model evidence includes exposed development, confirmation, and holdout periods under their documented classifications. Those periods must not be relabeled as untouched evidence for later model or policy selection.

### Current / Next

- Conduct outcome-blind historical-market provider feasibility research
- Freeze a final provider amendment covering source identity, timestamp semantics, mapping, eligible books, executable prices, settlement rules, licensing, and retention
- Freeze the normative analysis specification and remaining deterministic analysis parameters
- Complete required independent reviews and chain-of-custody gates
- Activate the approved analysis bundle before the first historical model/market/outcome join
- Perform historical market-performance analysis only after explicit authorization

The frozen base protocol alone does not authorize joining historical odds to model probabilities, outcomes, or derived performance. Outcome-blind provider-feasibility research remains permitted under the frozen research boundaries.

### Future

- Continue prospective NFL probability and market validation under frozen protocols
- Expand production operation only after current evidence, identity, timing, and health gates are satisfied
- Consider additional NFL markets only after Moneyline correctness and evidence requirements are met

## Shared Platform Direction

### Completed / Established

- PostgreSQL persistence with ordered migrations and repository boundaries
- Deterministic analytics, versioned artifacts, and immutable evidence contracts
- Cross-sport isolation for shared market infrastructure
- Automated unit and integration testing
- Operational audit, backup, recovery, and scheduler governance

### Future

- Broader reporting and research tooling
- Additional data sources and sportsbooks where licensing and provenance permit
- Additional sports and markets after existing workflows meet their validation gates
- Deployment expansion only with explicit production-readiness and health verification

## Engineering Principles

- Point-in-time correctness and avoidance of look-ahead bias
- Canonical identity and traceable source provenance
- Outcome-blind research design and prospective policy declaration
- Immutable frozen artifacts, protocols, and official evidence
- Explicit authorization boundaries for Git, providers, databases, migrations, tasks, and production
- Testability, maintainability, reproducibility, and independent review

Detailed implementation and research contracts live under `docs/architecture/`; authorized operating procedures live under `docs/operations/`. Root documentation intentionally avoids transient commit IDs, test totals, production status, incident state, and short-run performance results.
