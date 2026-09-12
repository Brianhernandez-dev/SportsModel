# NFL Historical Probability Evidence Exporter

## Purpose and boundary

The historical probability evidence exporter creates a versioned, outcome-blind
probability package for later independent evaluation. It is an evidence export,
not a prediction-writing or market-evaluation workflow. It performs no provider
requests and no database writes. The PostgreSQL reader requires a caller-owned
`READ ONLY`, `REPEATABLE READ` transaction and fails if either property is absent.

The export is an **event-time point-in-time reconstruction from a pinned current
source snapshot**. For every target, the feature cutoff is its canonical kickoff,
and every feature-source game must have an earlier kickoff. The package separately
records:

- `reconstruction_as_of`: the transaction timestamp of the read-only snapshot;
- `source_snapshot_as_of`: the latest relevant retained source-observation time.

Neither timestamp is represented as a historical prediction timestamp. The
repository does not provide bitemporal knowledge-time reconstruction, so this
package does not claim to recreate exactly what the database contained on each
historical game date.

## Locked population and classifications

Membership is selected without inspecting a target game's result. Ties therefore
remain in the canonical probability population even though their labels are not
usable for binary model fitting or legacy scoring reconciliation.

| Classification | Route | Score seasons | Rows |
| --- | --- | --- | ---: |
| `DEVELOPMENT_OOF` | mature | 2022-2024 | 710 |
| `DEVELOPMENT_OOF` | early | 2021-2024 | 192 |
| `EXPOSED_MODEL_HOLDOUT` | mature | 2025 | 237 |
| `EXPOSED_MODEL_HOLDOUT` | early | 2025 | 48 |
| **Canonical total** | | | **1,187** |

The older 1,184-row non-tie population is reconciliation evidence only and never
controls `probabilities.csv` membership. Already observed 2026 forward evidence
is excluded from historical probabilities and is represented separately in
`exposure_registry.json` as `EXPOSED_FORWARD`. Only completed, persisted
`official` prediction runs are authoritative forward exposure; preview runs are
excluded. This exporter never creates
`PROSPECTIVE_CONFIRMATION` rows. Any future confirmation cohort and evaluation
policy must be declared prospectively before outcomes are observed.

## Model reconstruction

Routing uses the frozen `nfl_moneyline_routing_0.1.0` contract: mature only when
both teams have at least three actual PIT-safe current-season prior games.
Scheduled week is not a routing input.

Mature OOF folds use the frozen ordered 19-feature family and the fixed expanding
training windows 2018-2021 -> 2022, 2018-2022 -> 2023, and 2018-2023 -> 2024.
The frozen minimum-history-3 policy is applied directly; the exporter performs no
policy selection.

Early OOF folds use exactly these four learned inputs, in order:

1. `prior_season_games_played_difference`
2. `prior_season_win_percentage_difference`
3. `prior_season_average_point_differential_difference`
4. `prior_season_average_turnover_differential_difference`

The fixed expanding windows are 2019-2020 -> 2021, 2019-2021 -> 2022,
2019-2022 -> 2023, and 2019-2023 -> 2024. `neutral_site` remains canonical game
identity metadata but is not a learned early input. Current-season values are used
only for routing.

Every OOF fold fits, on training rows only:

```text
SimpleImputer(strategy="median", add_indicator=False)
-> StandardScaler
-> LogisticRegression(C=1.0, solver="lbfgs", max_iter=5000, random_state=42)
```

Each fold receives its own training-game-set, label-bearing training-dataset,
preprocessing, specification, and fitted-model fingerprints. No score-season
label reaches preprocessing or fitting. No policy search, tuning, or score-season
fit is permitted.

All 2025 rows are fit-free. Mature rows use the committed frozen mature artifact;
early rows use the committed frozen early artifact. The ignored local 2025 report
is not a dependency. When supplied explicitly for optional reconciliation, its
fixed SHA-256 is required and its 236 mature non-tie probabilities must match the
fit-free replay. Outcome-bearing report content is never copied.

## Structural leakage controls

Training records and scoring targets are separate immutable types. Only training
records contain `home_win`. Scoring targets contain canonical identity, route
counts, frozen ordered features, and source trace, with no target result fields.

`probabilities.csv` has an explicit field allowlist. The probability, identity,
and source-provenance projections recursively reject target outcome, settlement,
market, price, EV, CLV, evaluation-result, and profit/loss field names. Historical
probability generation imports no odds or market service.

## Source and correction lineage

Canonical games, statistics, source observations, and completed ingestion-run
metadata are read in one database snapshot. A canonical game must have one
unambiguous source identity. Multiple retained observations are accepted as
correction lineage only when their identity and latest selection are deterministic.
Conflicting identities or different rows tied for the latest observation time fail
closed. The package records source file identities, ingestion runs, observation
times, per-row traces, correction findings, and the maximum relevant snapshot
time without copying raw outcome-bearing source payloads. Each statistics trace
retains canonical game and team IDs, provider team external ID, source identity,
raw-row SHA-256, and ingestion/source-file lineage so both team observations for
one game remain independently identifiable. Observation anomaly and override
provenance is retained when its source observation type supplies it.

The current reconstruction is checked against the dataset fingerprints pinned by
the committed frozen artifacts. Unattributable drift fails the export.

## Package contract

The CLI requires an explicit output directory. The directory must be empty. Output
inside the repository is refused unless the operator deliberately supplies the
documented override; stable evidence should normally be retained outside the
working tree.

The package contains:

```text
README.md
MANIFEST.json
protocol.json
probabilities.csv
game_identity.csv
folds.csv
model_fingerprints.json
training_set_fingerprints.csv
source_snapshots.json
source_traces.ndjson
exposure_registry.json
audit/validation_summary.json
audit/row_counts.json
audit/deterministic_rerun.json
audit/source_correction_findings.json
```

An optional `audit/holdout_reconciliation.json` is added only when the pinned 2025
report is explicitly supplied. The manifest records the byte size and SHA-256 of
every other package file and has its own canonical payload fingerprint. Validation
rejects missing files, extra files, changed byte sizes, and hash mismatches.

The manifest also embeds immutable package metadata: repository revision,
exporter and protocol versions, protocol fingerprint, redacted effective database
identity, PostgreSQL server identity, read-only repeatable transaction snapshot,
reconstruction/export-start timestamp, expected and actual canonical row counts,
and overall validation result. Database, server, and snapshot identity are captured
inside the same guarded transaction as the export snapshot.

An initial in-memory build is explicitly `UNVERIFIED` and cannot be written as a
final package. The CLI renders the complete content twice from the identical pinned
input (including optional reconciliation), compares the two render SHA-256 values,
and only then records deterministic-rerun `PASS`. Package writing fails closed if
that retained two-render evidence is missing, malformed, or inconsistent.

A future authorized invocation is:

```powershell
.venv\Scripts\python.exe scripts\export_nfl_historical_probability_evidence.py `
  --output-dir <absolute-directory-outside-the-repository>
```

That command reads the effective configured database. It must be preceded by the
repository's production identity, topology, migration, and health verification.
It is intentionally not part of routine unit-test execution and must not be run
merely to test the exporter.
