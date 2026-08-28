# NFL Moneyline Forward Operations

Protocol: `nfl_moneyline_forward_0.1.0`

This is the manual operating procedure for immutable 2026+ NFL model-prediction
evidence. It does not use odds and is not a betting workflow. Preview means a
model prediction snapshot only.

## Official slate policy

The authoritative selector is an explicit half-open UTC kickoff window:
`slate_start <= scheduled_start_time < slate_end`. NFL week is descriptive and
must never select the official slate.

Calendar examples remain illustrative. Before every operation, obtain the real
UTC bounds from the current canonical schedule and verify its source provenance:

1. Use the smallest non-overlapping UTC window that contains exactly the games
   intended for that official observation.
2. Normally use a separate window for an early standalone game and one window
   for the main Sunday-Monday slate. Give international, Saturday, holiday, or
   other exceptional games their own explicit window when that reduces risk.
3. Run preflight 60-120 minutes before the first kickoff in the window, review
   every target, then execute immediately. Never proceed if the first kickoff is
   imminent enough that review cannot finish safely.
4. Games must be canonical, unplayed, season 2026 or later, and strictly before
   kickoff. One official observation is allowed per protocol/game. Preview rows
   never satisfy or replace this requirement.

Before live use, obtain the real UTC bounds from the canonical schedule. Do not
copy the illustrative timestamps below without verifying them.

## Session setup and health

Use the production environment only for genuine operations. Never set the
destructive test acknowledgement in a production session.

```powershell
$python = '.venv\Scripts\python.exe'
$season = 2026
$slateStart = '2026-09-10T00:00:00Z' # illustrative; verify canonical schedule
$slateEnd = '2026-09-11T12:00:00Z'   # exclusive; illustrative

& $python scripts/migrate_database.py
```

The migration command must report that the database is current. Inspect the
canonical games in the chosen window before continuing.

## Two-step official workflow

Preflight runs inference in a read-only repeatable snapshot and writes zero rows:

```powershell
& $python scripts/predict_nfl_moneyline.py `
  --season $season `
  --slate-start $slateStart `
  --slate-end $slateEnd `
  --official `
  --preflight
```

Review target count, every away/home team and kickoff, prior-game counts, route,
frozen model/schema, probability, predicted side, and blockers. Continue only
when the final line is `READY FOR OFFICIAL RUN`.

Create and retain a UUID in the operator log or transcript:

```powershell
$runKey = [guid]::NewGuid().ToString()
$runKey
```

Execute the same reviewed window deliberately:

```powershell
& $python scripts/predict_nfl_moneyline.py `
  --season $season `
  --slate-start $slateStart `
  --slate-end $slateEnd `
  --official `
  --run-key $runKey `
  --confirm-official
```

The CLI also supports `--generate-run-key`, which prints the generated key before
writing. Retain the transcript. Verify the completed run ID/key, protocol, counts,
slate fingerprint, per-game route/model/probability, and prediction-set hash.

A completed same-key retry is idempotent. A failed run is permanent evidence and
requires a new key after the cause is understood. Never use a new key merely to
replace an official probability: official evidence is immutable and unique.

## Official entry-market evaluation

Market evaluation is a separate persisted-evidence step. It does not capture
odds and cannot call a provider. Use it only after an authorized official
prediction and a separately authorized, completed NFL Odds API `entry` run both
exist. Retain both IDs in the operator transcript.

The safe inspection command is dry run by default:

```powershell
$predictionId = 123 # illustrative; obtain from persisted official evidence
$oddsRunId = 456    # illustrative; obtain from a completed NFL entry run

& $python -m sportsmodel.nfl.manual_market_evaluation_cli `
  --prediction-id $predictionId `
  --odds-run-id $oddsRunId
```

This opens a read-only repeatable transaction, performs zero provider calls and
zero writes, and exits 10 when the pair is eligible. Review the exact
prediction/run IDs, route/model/schema, canonical matchup and kickoff, selected
team and stored probability, request/receipt gap, contributors and exclusions,
consensus, best price/provider, edge, model EV, protocol identity, and source-
graph fingerprint. A current production database with no NFL predictions has no
valid pair; do not create a fake prediction to test the command. Run 281 is
naturally rejected because it has no eligible official prediction before its
receipt time.

Creating an evaluation requires a separate explicit authorization and both
write guards:

```powershell
& $python -m sportsmodel.nfl.manual_market_evaluation_cli `
  --prediction-id $predictionId `
  --odds-run-id $oddsRunId `
  --live `
  --confirm-create-evaluation
```

Never add force, protocol-override, model-probability, team, kickoff, price,
contributor, fingerprint, or evaluation-time arguments. The service rederives
those values from persisted evidence and the frozen protocol. A same-graph retry
returns the existing evaluation idempotently. A different graph conflicts and
must be investigated; it must not be replaced. A failed live attempt never
triggers odds recapture or provider retry.

Exit codes are: 0 live success; 2 invalid operator arguments; 10 eligible dry
run; 20 protocol, source, or timing ineligibility; 21 insufficient complete-book
coverage; 22 immutable source-graph conflict; and 30 database or infrastructure
failure. Dry-run failures write nothing. A live failure that reached the
authoritative Phase 4B3 transaction may retain one immutable failed attempt; the
CLI reports that attempt ID when available.

## Stuck `running` run recovery

A hard process interruption can leave the durable parent run at `status =
running`. There is no automatic abandonment timeout or cleanup; recovery is a
manual operator decision. Preserve that evidence and use this procedure:

1. Do not automatically create a new official run key. Locate the existing row
   by the retained `run_key` and inspect its status, `target_count`, committed
   child prediction count, `request_sha256`, `slate_fingerprint`, and source
   snapshot fields (`source_data_as_of` and `source_snapshot_sha256`). Also
   compare the requested UTC window, run type, protocol, routing contract, and
   frozen model identities with the retained operator transcript.
2. If the request identity is exactly the same, the status is still `running`,
   and the child count is zero, rerun the same command with the **same run key**.
   These are the service's supported recovery semantics: it revalidates the
   immutable request/slate identities, locks the parent, rebuilds the current
   canonical slate in one repeatable-read transaction, and atomically writes all
   predictions plus completion.
3. A committed child count other than zero is inconsistent with the supported
   atomic contract. Stop and investigate the database invariants; do not force
   completion or attempt another official run.
4. If the run is definitively failed and the service has transitioned it to
   `failed`, retain it as audit evidence, correct the external cause, and use a
   new run key for a subsequent attempt. Failed keys cannot be reused.

Never edit immutable prediction rows, manually mark a run completed to bypass
lifecycle protections, or manufacture source snapshot identities. If status,
counts, fingerprints, or source identity are internally inconsistent, stop and
investigate rather than forcing recovery.

## Preview snapshots

Previews may be repeated and do not consume official uniqueness:

```powershell
$previewKey = [guid]::NewGuid().ToString()
& $python scripts/predict_nfl_moneyline.py `
  --season $season `
  --slate-start $slateStart `
  --slate-end $slateEnd `
  --preview `
  --run-key $previewKey
```

Preview observations remain immutable and exploratory. Repeating previews does
not promote them or make them official evidence. They are excluded from official
forward metrics unless `--preview` is explicitly supplied to produce a separate,
non-official report. Only persisted `official` runs under the frozen forward
protocol count as forward evidence.

## Read-only forward evaluation

After canonical results become final:

```powershell
& $python scripts/evaluate_nfl_moneyline_forward.py --season 2026

# Explicit non-official preview report
& $python scripts/evaluate_nfl_moneyline_forward.py `
  --season 2026 `
  --preview
```

Optional filters are `--protocol`, `--slate-start`, `--slate-end`, and
`--route early|mature`. The evaluator opens a read-only repeatable transaction,
uses persisted canonical probabilities and route-specific frozen baselines, and
never updates prediction evidence. Pending games remain pending. Final ties are
reported and excluded from probability metrics.

The unfiltered report also prints `routing_distribution` with total, early, and
mature counts and percentages. This is an operational sanity check for an
obvious history-count or routing defect, not a gate: no historical-distribution
threshold may block a valid schedule.

### Frozen report contract

The standard probability-forward report is frozen to include:

- total, resolved, pending, and final-tie counts;
- early and mature counts and percentages, plus route-specific groups;
- model and frozen route-specific home-baseline accuracy, log loss, and Brier
  score on the exact same resolved rows;
- ROC-AUC only when both target classes occur;
- predicted mean, actual home-win rate, calibration summary, and ECE when the
  applicable first-look threshold below has been reached;
- paired model-minus-baseline accuracy, log-loss, and Brier differences;
- deterministic bootstrap confidence intervals when at least one resolved row
  exists, with interpretation governed by the first-look thresholds; and
- protocol, run, model, prediction-set, and filter identities.

The evaluator validates prediction timing, canonical kickoff and team identity,
predicted-side consistency, and final-score completeness before reporting. A
standard successful report therefore has zero data-integrity exceptions. If any
validation fails, the evaluator aborts instead of emitting metrics; retain and
report the exception as a blocking data-integrity finding. Probability reports
must not contain sportsbook ROI, edge, expected value, paper-candidate, or other
market-profitability conclusions.

### Frozen first-look policy

These thresholds govern evidence interpretation and model decisions. They do
not restrict running or inspecting the read-only evaluator.

They were selected without reference to 2026 outcomes. Historical routed volume
over the exposed 2018-2025 seasons was 46-48 early targets and 219-237 mature
targets per complete season. Under a conservative Bernoulli approximation, 50
resolved rows still permit a worst-case standard error near 0.071, while 150
permit one near 0.041; paired losses, calibration, and route-specific dependence
can remain more uncertain. The thresholds below are minimum first looks, not
guarantees of adequate power or stopping rules.

- **Operational monitoring:** allowed continuously for run lifecycle, immutable
  identities, pending/resolved counts, data-integrity validation, and routing
  distribution. It may not trigger model or threshold changes.
- **Descriptive interim reporting:** allowed below the thresholds when labeled
  preliminary and non-inferential. Seasonal early-route summaries are expected
  because accumulating 150 early rows likely spans multiple seasons.
- **Inferential/model-value claims:** prohibited until the applicable fixed
  route threshold is reached, and still require uncertainty and paired-baseline
  reporting rather than a binary pass based on a point estimate.

- **Mature route:** do not make a formal model-performance decision before 50
  resolved 2026 mature-route official predictions. At 50, produce the first
  formal forward report. Any earlier view is operational/descriptive only, and
  partial 2026 results must not change the frozen mature model.
- **Early route:** report each season descriptively, but do not make strong
  claims from one season. The first formal early-route model-value look is fixed
  at 150 resolved official predictions accumulated under this protocol. Before
  then, calibration, ECE, and paired model-versus-baseline intervals are
  descriptive only. The small early-route sample is expected to require
  multi-season patience; partial small samples must not change the frozen early
  model.

### Routing-distribution monitoring

Every unfiltered operational report records early count, mature count, and both
percentages. The exposed 2018-2025 reference seasons contained 46-48 early and
219-237 mature eligible non-tied targets. Those ranges are descriptive context
for detecting obvious missing-history, schedule, or routing defects; calendar
shape, ties, and incomplete evidence can legitimately move a forward season
outside them. No range is an eligibility gate, and no observed distribution may
be used to retune the min-3 boundary.

### Interpretation limitations frozen before 2026

The early-season model was selected by parsimony after historical candidate
behavior was compared on already-exposed 2019-2024 data. That historical early
data is development/exposed evidence, not independent confirmation. The early
model has **not** demonstrated a confidence-interval-excluding-zero advantage
over the home baseline on genuinely independent forward evidence. The 2026+
period is the first genuine test of whether the frozen early model adds
predictive value, so its 2026 baseline comparison is a real hypothesis test,
not merely a confirmation exercise.

The mature/early boundary of three prior games was also selected historically
by comparing candidate thresholds. It is not independently derived or unbiased.
Its prospective practical justification is that it is frozen, has a clear
operational interpretation, and the mature route subsequently showed genuine
predictive signal on the independent 2025 holdout. Do not retune the min-3
threshold using 2026 results inside the active forward-validation window.

### Historical evidence retirement

All 2019-2025 NFL outcomes are retired for selection or tuning of the current
frozen models and router. The early-route 2019-2024 comparisons are exposed
development evidence, and the mature-route 2025 holdout has been exposed by its
one-time evaluation. Ad hoc historical reruns may diagnose deterministic
implementation or data quality, but they cannot promote, modify, recalibrate, or
refit either current artifact or the min-3 routing threshold. Any future model
generation requires a separately versioned development, freeze, and prospective
evaluation cycle.

### Same-snapshot point-in-time invariant

For an official write, the service sets `REPEATABLE READ` before opening the
write cursor. Target selection, routing prior-game counts, feature-vector
history reads, kickoff checks, official-conflict checks, source tracing, child
inserts, and run completion all use that one caller-owned transaction cursor.
Each target receives one `NFLFeatureDataProvider` backed by that cursor, and its
cache supplies the same current-season history to both routing and feature
construction. A focused contract test pins the isolation level, cursor identity,
and shared production-provider behavior so a split-snapshot regression fails.
Parent-run creation may first compute the expected slate identity in a short
transaction, but that read never supplies inference data: the authoritative
slate is reselected inside the repeatable-read write snapshot and the operation
fails if its fingerprint or target count differs.

## No mid-season model changes

During the active 2026 forward-evaluation window, do not modify the frozen
mature artifact, frozen early artifact, routing threshold, or feature schema;
do not recalibrate, refit, or silently replace model files, regardless of
whether partial results look unusually good or bad.

Any successor must receive a new model/version identity, use a new documented
protocol when its evaluation contract requires one, preserve all earlier
official evidence unchanged, and be evaluated prospectively as a separate model
generation.

## Historical source-correction limitation

The frozen model artifact identity is authoritative for production inference,
and each forward prediction's source trace and fingerprints preserve what was
used at prediction time. If canonical historical raw sources are corrected
after model freeze, exact reconstruction of the old training-era source state
may be limited unless that raw state was separately archived. This is not a
forward-leakage issue.

The persisted target kickoff and canonical team orientation preserve the values
used for each prediction. If the current canonical kickoff or orientation later
differs, the read-only evaluator raises a data-integrity error rather than
silently evaluating against the changed identity. Artifact, feature-vector,
source-trace, source-snapshot, prediction-set, schema, router, and protocol
fingerprints protect the persisted inference contract, but they do not fully
archive the byte-exact historical raw source state or the meaning of every
upstream statistic at model-freeze time.

**Deferred hardening:** define versioned archival for raw historical source
assets, correction lineage, and statistic semantic/schema changes before exact
training-state reconstruction is claimed. This is a reproducibility limitation,
not permission to rewrite historical predictions or frozen artifacts, and is
not required for the current Phase 3 evidence boundary.

Never change a frozen model, schema, fingerprint, routing contract, or protocol
in place. A successor model requires new versioned identities and, when the
evaluation contract changes, a new protocol.
