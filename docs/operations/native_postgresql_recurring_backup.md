# Native PostgreSQL recurring production backup

## Purpose and boundaries

`scripts/run_native_postgresql_backup.ps1` is the unattended wrapper for one
local SportsModel production backup. It delegates backup creation and artifact
verification to the accepted
`scripts/invoke_native_postgresql_backup_restore_acceptance.ps1` engine.

The wrapper exposes only the engine's `Backup` and `VerifyBackup` actions. It
does not create or drop databases, restore data, control PostgreSQL or Docker,
run migrations, or invoke an MLB/NFL workflow.

## Locations and naming

Defaults are:

- backup pairs: `D:\SportsModel\backups\postgresql`;
- durable run logs: `D:\SportsModel\logs\postgresql_backup`;
- lock file: `run_native_postgresql_backup.lock` in the log directory;
- dump: `sportsmodel-native-YYYYMMDDtHHMMSSz.dump`;
- manifest: the dump name plus `.manifest.json`.

The filename timestamp is UTC. Each invocation creates a separate log whose
name contains a higher-resolution UTC timestamp, launcher PID, and random
nonce. Existing dump, manifest, and log files are never overwritten.

The wrapper creates its two directories when absent. Before enabling a
production task, inspect their inherited ACLs and confirm that only identities
approved to handle production data can read or modify the backup artifacts.
The scheduled identity must have read access to `D:\SportsModel\.env` and the
repository and modify access to the backup and log directories. Do not grant
access merely to make the task pass.

The current repository root grants inherited modification rights to the broad
`Authenticated Users` principal. Do not let new production dump files retain
that inherited access. During a separately approved deployment, create the two
still-empty directories and replace their inherited ACLs before the first
backup. The intended owner and only allowed identities are:

- owner: `AI-BETO\Brian`;
- `AI-BETO\Brian`: Modify, inherited by child files and directories;
- `NT AUTHORITY\SYSTEM`: Full Control, inherited by children;
- `BUILTIN\Administrators`: Full Control, inherited by children.

There must be no `Authenticated Users`, `BUILTIN\Users`, sandbox group, unknown
SID, or other unreviewed allow entry. The wrapper deliberately does not rewrite
ACLs: a scheduled data operation must not silently change permissions on a
configurable or pre-existing path.

For newly created, empty directories only, the recommended deployment-time
procedure is:

```powershell
$directories = @(
    "D:\SportsModel\backups\postgresql",
    "D:\SportsModel\logs\postgresql_backup"
)
$owner = [Security.Principal.NTAccount]"AI-BETO\Brian"
$inheritance = (
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
    [Security.AccessControl.InheritanceFlags]::ObjectInherit
)
$propagation = [Security.AccessControl.PropagationFlags]::None
$allow = [Security.AccessControl.AccessControlType]::Allow

foreach ($directory in $directories) {
    if (Test-Path -LiteralPath $directory) {
        if (@(Get-ChildItem -LiteralPath $directory -Force).Count -ne 0) {
            throw "Refusing to replace ACLs on non-empty directory: $directory"
        }
    }
    else {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }

    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($owner)
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $owner,
        [Security.AccessControl.FileSystemRights]::Modify,
        $inheritance,
        $propagation,
        $allow
    ))
    foreach ($identity in @("NT AUTHORITY\SYSTEM", "BUILTIN\Administrators")) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.NTAccount]$identity,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            $propagation,
            $allow
        ))
    }
    Set-Acl -LiteralPath $directory -AclObject $acl
}
```

Afterward, use `Get-Acl` to verify the owner, protected inheritance, and exact
three-principal allow list. Under the intended `Brian` identity, create and
remove one harmless sentinel file in each directory to prove write/delete
access before registering the task. Stop if the ACL differs; do not weaken it.

## Authentication and database safety

The accepted engine reads the ordinary application connection from
`D:\SportsModel\.env`. The scheduled wrapper does not accept an administrator
credential and does not create `.pgpass` or another credential file. The
engine provides the application password to PostgreSQL tools only through the
child-process environment and uses `--no-password`.

Before `pg_dump`, the engine proves the native service, listener, database,
writable-primary state, required migration, and representative database
integrity. `pg_dump` takes a consistent read-only custom-format backup; it does
not stop PostgreSQL or take an exclusive database lock.

The wrapper does not persist engine output or exception messages. Its durable
log contains only stages, exit status, artifact lifecycle, retention counts,
and final success or failure. It never records environment contents, a DSN,
connection string, user password, or provider credential.

## Execution sequence and failure behavior

One invocation performs these steps:

1. Create a unique durable log and acquire an exclusive local file lock.
2. Refuse an existing dump or manifest at the generated timestamp.
3. Invoke the accepted engine with `-Action Backup` and
   `-ApproveProductionBackup`.
4. Invoke the engine again with the separate `-Action VerifyBackup` against
   the resulting dump and manifest.
5. Validate the complete managed artifact set and apply retention.
6. Record `FINAL SUCCESS` and exit zero.

Readiness, backup, manifest, verification, malformed-artifact, retention, and
overlap failures exit nonzero. Verification failure prevents retention. The
lock is an open file handle with exclusive sharing; Windows releases it if the
wrapper exits or is terminated, so a stale lock filename does not block a
later run.

## Retention

Retention runs only after the new pair passes the separate verification step.
The newest 30 verified pairs are kept, ordered by the UTC timestamp embedded
in the exact filename. Before deleting anything, the wrapper:

- rejects any `sportsmodel-native-*` file that does not match the exact dump
  or manifest convention;
- rejects every unpaired dump or manifest;
- re-runs the accepted engine's `VerifyBackup` action for every older pair.

Only complete, exactly named dump/manifest pairs beyond the newest 30 are
deleted. Unrelated files are ignored. Any malformed, unpaired, or unverifiable
artifact stops retention without blindly deleting another pair. A filesystem
failure while deleting a pair fails the run nonzero and requires operator
review.

## Proposed Scheduled Task

The current production writer schedule leaves the cleanest recurring window
after the 11:00 PM Pacific Late Night Snapshot and before the 6:00 AM Morning
Snapshot. Schedule the backup for **2:30 AM Pacific daily**. This is after the
Late Night task's one-hour retry window ends at midnight and leaves 90 minutes
after the two-hour backup timeout before Morning.

The current Windows task history showed AppList backup work around 1:27–1:29
AM, so 1:00 AM is not preferred. The 2:30 AM slot avoids those backup jobs.
Recent nearby activity at 2:21 and 2:42 AM was limited to Edge update and
certificate/cache maintenance rather than a competing backup. Re-audit task
schedules before registration because Windows maintenance timing can move.

Use the established local `Brian` identity with S4U, highest run level, local
paths only, `IgnoreNew`, no catch-up, and a two-hour execution limit. S4U is
appropriate because the operation needs no network resource or interactive
desktop and the accepted engine uses the application credential from `.env`.

The following is a future registration definition. Do not run it until task
creation and the directory ACLs have been separately reviewed and approved:

```powershell
$taskName = "SportsModel - Native PostgreSQL Backup"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw "Task already exists; inspect it instead of overwriting it."
}
$action = New-ScheduledTaskAction `
    -Execute "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden ' +
        '-ExecutionPolicy Bypass -File ' +
        '"D:\SportsModel\scripts\run_native_postgresql_backup.ps1"') `
    -WorkingDirectory "D:\SportsModel"
$trigger = New-ScheduledTaskTrigger -Daily -At "2:30 AM"
$principal = New-ScheduledTaskPrincipal `
    -UserId "AI-BETO\Brian" `
    -LogonType S4U `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable:$false
$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Verified native PostgreSQL production backup."
Register-ScheduledTask `
    -TaskName $taskName `
    -InputObject $task
```

Before registration, confirm that 2:30 AM does not conflict with a newly added
SportsModel or system backup task. After registration, inspect the exported
task definition and use a separately approved controlled first run; do not
wait for the first unattended run to discover permission or path errors.

## Identifying the latest verified backup

List the wrapper logs newest first and locate the newest log containing
`FINAL SUCCESS`. Its attempt time corresponds to one exactly named dump and
manifest pair in the backup directory. Confirmation should include both files,
the successful `Backup` and `VerifyBackup` stage records, and the retention
success record.

For an additional non-mutating check, invoke the accepted engine directly:

```powershell
$backup = "D:\SportsModel\backups\postgresql\sportsmodel-native-YYYYMMDDtHHMMSSz.dump"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
    -File .\scripts\invoke_native_postgresql_backup_restore_acceptance.ps1 `
    -Action VerifyBackup `
    -BackupPath $backup `
    -ManifestPath "$backup.manifest.json"
```

`VerifyBackup` checks the manifest hash and size and requires `pg_restore
--list` to accept the archive. Full restore proof remains the separate,
explicitly approved manual procedure in
`docs/operations/native_postgresql_backup_restore_acceptance.md`. The recurring
wrapper never exposes or performs restore-target creation, restore,
verification of a restored database, or cleanup.
