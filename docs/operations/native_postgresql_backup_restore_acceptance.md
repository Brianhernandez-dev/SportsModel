# Native PostgreSQL backup and restore acceptance

## Purpose and safety boundary

This procedure proves that a native PostgreSQL production backup can be
restored into an isolated disposable database without changing the production
database. It does not use Docker and does not restart PostgreSQL.

The production source is fixed to `localhost:5432/sportsmodel`. Restore targets
must use the timestamped form
`sportsmodel_restore_acceptance_YYYYMMDDThhmmssZ` (normalized to lowercase by
the example commands) and can never be `sportsmodel`, a PostgreSQL system
database, or a production-like alias. Backup filenames must use the timestamped
form `sportsmodel-native-YYYYMMDDThhmmssZ.dump`.

The script defaults to `Plan`, which performs no database or filesystem action.
Backup creation, disposable-database creation, restore, and cleanup are separate
actions with separate approval switches. Cleanup is never automatic.

Run the acceptance from an elevated PowerShell session because the native
PostgreSQL binaries are protected by host filesystem ACLs. The application
credential is loaded from the existing production `.env` file and is passed to
PostgreSQL clients only through the process environment. It is never printed or
placed in command arguments. Database-administrator credentials must be entered
interactively with `Get-Credential`; they must not be stored in the repository.

## Why custom format is appropriate

Production uses PostgreSQL 16 and the installed `pg_dump` and `pg_restore`
clients are the matching major version. The database is small enough for a
single custom-format artifact. Custom format preserves tables, data, sequences,
indexes, constraints, functions, triggers, and extension declarations while
supporting `pg_restore --list` and a single-transaction restore. The restored
copy deliberately suppresses source ownership and ACL replay so that all
objects are owned by the disposable database owner.

## Required controlled conditions

Perform the acceptance only in a separately authorized maintenance window:

1. Record and temporarily disable the eight MLB writer tasks using the normal
   production maintenance procedure.
2. Confirm no writer is running and no provider/workflow process is active.
3. Record a production evidence baseline.
4. Keep writers frozen until `VerifyRestore` proves that production still
   matches the backup manifest.
5. Restore the task states and verify their definitions and schedules are
   unchanged.

The tool does not change Scheduled Tasks itself.

## Controlled command sequence

Open an elevated PowerShell window in `D:\SportsModel`. Every line marked
**APPROVAL REQUIRED** is a separate consequential authorization boundary.

```powershell
$tool = ".\scripts\invoke_native_postgresql_backup_restore_acceptance.ps1"
$stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ").ToLowerInvariant()
$backupDir = "D:\SportsModelBackups"
$backup = Join-Path $backupDir "sportsmodel-native-$stamp.dump"
$manifest = "$backup.manifest.json"
$restoreDb = "sportsmodel_restore_acceptance_$stamp"
$writerTasks = @(
    "SportsModel - Moneyline Morning Snapshot",
    "SportsModel - Daily Moneyline Postgame",
    "SportsModel - Daily Moneyline Pregame",
    "SportsModel - Moneyline Afternoon Snapshot",
    "SportsModel - Moneyline Opening Snapshot",
    "SportsModel - Moneyline Tomorrow Preview",
    "SportsModel - Moneyline Evening Snapshot",
    "SportsModel - Moneyline Late Night Snapshot"
)
```

### 1. Read-only preflight

```powershell
& $tool -Action Plan -TargetDatabase $restoreDb
& $tool -Action Preflight
```

Require `PREFLIGHT READY`, native PostgreSQL identity success, migration 029
present, the observed migration maximum, zero representative orphans, and
PostgreSQL 16 client versions. Confirm the backup directory already exists;
the tool intentionally does not create it.

Record each writer's definition hash, enabled state, running state, last result,
and next-run time. After separate approval for the maintenance freeze, disable
exactly these tasks and confirm none is running:

```powershell
foreach ($task in $writerTasks) {
    Disable-ScheduledTask -TaskName $task -ErrorAction Stop | Out-Null
}
foreach ($task in $writerTasks) {
    Get-ScheduledTask -TaskName $task |
        Select-Object TaskName, State, @{Name="Enabled"; Expression={$_.Settings.Enabled}}
}
```

### 2. Production backup creation — APPROVAL REQUIRED

```powershell
& $tool `
    -Action Backup `
    -BackupPath $backup `
    -ManifestPath $manifest `
    -ApproveProductionBackup
```

This performs a custom-format `pg_dump`. It refuses overwrite, records source
counts/migrations/sequences/schema state, requires the source snapshot to stay
unchanged across the dump, and writes a checksum-bearing manifest.

### 3. Backup integrity verification

```powershell
& $tool `
    -Action VerifyBackup `
    -BackupPath $backup `
    -ManifestPath $manifest
```

Require a nonzero file, matching SHA-256 and size, and successful
`pg_restore --list` inspection.

### 4. Create isolated restore target — APPROVAL REQUIRED

The normal `sportsmodel` role intentionally lacks `CREATEDB`. Obtain the
database-administrator credential interactively:

```powershell
$admin = Get-Credential -UserName "postgres" -Message "Native PostgreSQL administrator for disposable restore target"
& $tool `
    -Action CreateRestoreTarget `
    -TargetDatabase $restoreDb `
    -AdminCredential $admin `
    -ApproveCreateRestoreTarget
```

The action fails if the target already exists and creates it owned by the
existing `sportsmodel` application role. It also adds a dedicated acceptance
marker to the database. Restore, verification, and cleanup refuse a target
whose owner or marker does not match, even when its name has the allowed prefix.

### 5. Restore — APPROVAL REQUIRED

```powershell
& $tool `
    -Action Restore `
    -BackupPath $backup `
    -ManifestPath $manifest `
    -TargetDatabase $restoreDb `
    -ApproveRestore
```

The target must be empty. Restore uses `--exit-on-error`,
`--single-transaction`, `--no-owner`, and `--no-privileges`. It never uses
`--clean`, `--create`, or a production database name.

### 6. Source-versus-restored verification

```powershell
& $tool `
    -Action VerifyRestore `
    -BackupPath $backup `
    -ManifestPath $manifest `
    -TargetDatabase $restoreDb
```

Require `RESTORE ACCEPTED`. Verification proves:

- production still matches the accepted source manifest;
- restored migrations exactly match, including migration 029 and max version;
- important table counts and all public sequence states match;
- server version, extensions, relation counts, functions, triggers, and
  invalid-constraint state match;
- representative prediction/odds/evaluation/settlement orphan checks pass;
- the isolated target is a writable primary, not a recovery database.

### 7. Prove production remained unchanged

Keep the writer freeze in place while checking the recorded production evidence
baseline against the manifest and final read-only database state. If production
changed, the script fails `VerifyRestore`; do not describe that run as an
accepted restore test.

Restore the eight task states only after acceptance is complete and separately
verify their definition hashes, next-run times, and absence of an unexpected
launch.

After separate approval to end the maintenance freeze:

```powershell
foreach ($task in $writerTasks) {
    Enable-ScheduledTask -TaskName $task -ErrorAction Stop | Out-Null
}
foreach ($task in $writerTasks) {
    $taskState = Get-ScheduledTask -TaskName $task
    $taskInfo = Get-ScheduledTaskInfo -TaskName $task
    [pscustomobject]@{
        Task = $task
        Enabled = $taskState.Settings.Enabled
        State = $taskState.State
        LastResult = $taskInfo.LastTaskResult
        NextRun = $taskInfo.NextRunTime
    }
}
```

### 8. Optional cleanup — SEPARATE APPROVAL REQUIRED

Cleanup is intentionally a separate command and is never run automatically:

```powershell
& $tool `
    -Action DropRestoreTarget `
    -TargetDatabase $restoreDb `
    -AdminCredential $admin `
    -ApproveDropRestoreTarget
```

The command does not force-disconnect sessions. If the target is in use,
cleanup fails closed. Preserve the backup and manifest according to the future
retention policy; this procedure does not delete backup artifacts.
