# NFL Moneyline Forward Operations

Protocol: `nfl_moneyline_forward_0.1.0`

This is the manual operating procedure for immutable 2026+ NFL model-prediction
evidence. It does not use odds and is not a betting workflow. Preview means a
model prediction snapshot only.

## Official slate policy

The authoritative selector is an explicit half-open UTC kickoff window:
`slate_start <= scheduled_start_time < slate_end`. NFL week is descriptive and
must never select the official slate.

Production currently has no canonical 2026 schedule rows, so calendar examples
must remain illustrative until schedule ingestion is complete. Once populated:

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

Preview observations remain immutable. They are excluded from official forward
metrics unless `--preview` is explicitly supplied to the evaluator.

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

Never change a frozen model, schema, fingerprint, routing contract, or protocol
in place. A successor model requires new versioned identities and, when the
evaluation contract changes, a new protocol.
