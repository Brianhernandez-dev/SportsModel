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

- protected runtime: `D:\SportsModelOps\native_postgresql_backup`;
- dedicated credential: `<protected runtime>\config\backup.env`;
- backup pairs: `D:\SportsModelBackups\PostgreSQL\backups`;
- durable run logs: `D:\SportsModelBackups\PostgreSQL\logs`;
- lock file: `run_native_postgresql_backup.lock` in the backup directory;
- dump: `sportsmodel-native-YYYYMMDDtHHMMSSz.dump`;
- manifest: the dump name plus `.manifest.json`.

The filename timestamp is UTC. Each invocation creates a separate log whose
name contains a higher-resolution UTC timestamp, launcher PID, and random
nonce. Existing dump, manifest, and log files are never overwritten.

The wrapper requires both directories to exist before it starts. It fails
before opening a log, acquiring its operation lock, or invoking the backup
engine unless each directory has the exact protected ACL described below. The
scheduled identity must also have read-only access to the protected runtime and
credential and Modify access to the backup and log directories. The recurring
path has no dependency on `D:\SportsModel` or `D:\SportsModel\.env`.

Do not let new production dump files inherit broad drive or parent-directory
access. During a separately approved deployment, create the two still-empty
directories and replace their inherited ACLs before the first backup. The
intended owner and only allowed identities are:

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
    "D:\SportsModelBackups\PostgreSQL\backups",
    "D:\SportsModelBackups\PostgreSQL\logs"
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
The wrapper repeats the owner, protected-inheritance, allowed-principal,
child-inheritance, and minimum-rights checks on every invocation. It never
repairs or relaxes an ACL automatically.

## Privilege and protected runtime boundary

The current machine ACLs do not permit a normal medium-integrity
`AI-BETO\Brian` token to traverse `D:\PostgreSQL\16` and reach `pg_dump.exe`.
`Brian` is an administrator, but that group is deny-only without elevation.
Consequently, **Highest would be required by the current PostgreSQL executable
ACL**, not by `pg_dump`, S4U, the application database role, or backup
semantics. Highest is not approved for the recurring design.

Do not register the task at Highest while its action loads code or
configuration from the current repository ACL. The live repository, its
scripts, `.venv`, source tree, and `.env` currently inherit broad modification
rights. Elevating that chain would allow a less-trusted writer to replace code
that Task Scheduler later executes with an administrator token. The `.env`
also contains the application database credential; broad read or modification
access can disclose that credential or redirect the backup connection.

The smallest preferred protected-runtime model is:

1. Run the S4U task as `AI-BETO\Brian` at **Limited**, not Highest.
2. In a separate, approved ACL change, grant that identity only the traverse
   and read/execute access needed for the PostgreSQL 16 program directory and
   `pg_dump.exe`, `pg_restore.exe`, and `psql.exe`. Do not grant Modify, access
   to the PostgreSQL data directory, or service-control rights.
3. Stage exactly the wrapper, accepted engine, shared readiness helper, and
   generated SHA-256 manifest in the protected runtime. Python, the application
   source tree, and the live checkout are not part of this closure.
4. Provision a separate `config\backup.env` with exactly the five allowed keys
   described below. Do not copy the canonical application `.env`.
5. Prove the complete read-only Preflight under the exact Limited S4U identity
   before registration. If that proof fails, stop; do not fall back to Highest
   against a broadly writable runtime.

The future PostgreSQL client ACL change should grant `AI-BETO\Brian` traverse
only on `D:\PostgreSQL`, `D:\PostgreSQL\16`, and
`D:\PostgreSQL\16\server`, then Read/Execute on
`D:\PostgreSQL\16\server\bin` and its installed client/DLL contents. Do not
propagate that grant to `D:\PostgreSQL\16\data`; the data directory remains
excluded. Do not copy PostgreSQL executables into the protected runtime.

The protected runtime owner is `BUILTIN\Administrators`, inheritance is
disabled, and the only allow entries are `AI-BETO\Brian` Read/Execute plus
`SYSTEM` and `Administrators` Full Control, inherited by runtime children.
The staging helper creates this runtime only with explicit `-Action Stage` and
`-ApproveProtectedRuntimeStage`; its default is a non-mutating plan. It refuses
an existing target and never copies a credential:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
    -File .\scripts\stage_native_postgresql_backup_runtime.ps1
```

No executable, credential, production storage, or service ACL change is
performed by the recurring wrapper. All deployment ACL work remains separately
approved and must be verified before task registration.

## Authentication and database safety

The recurring wrapper requires `<protected runtime>\config\backup.env` to
contain exactly `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`POSTGRES_USER`, and `POSTGRES_PASSWORD`, each once and non-empty. Unknown,
duplicate, malformed, missing, or empty settings fail before the engine runs.
The file owner must be `Administrators` or `SYSTEM`, inheritance must be
disabled, and its only allow entries are Brian Read plus SYSTEM and
Administrators Full Control. Brian must have no write, delete, ownership, or
permission-change rights. The wrapper validates but never repairs this ACL.

The scheduled wrapper does not accept an administrator credential and does not
create `.pgpass`. The engine provides the application password to PostgreSQL
tools only through the child-process environment and uses `--no-password`.

The recurring `Backup` action resolves only `pg_dump.exe`, `pg_restore.exe`,
and `psql.exe`; `VerifyBackup` resolves only `pg_restore.exe`. The separate
operator `Preflight` continues to require all five accepted tools, and the
create/restore/drop actions resolve `createdb.exe`, `pg_restore.exe`, or
`dropdb.exe` only where their existing approved operation requires them.

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

1. Validate both artifact-directory ACLs, create a unique durable log, and
   acquire an exclusive operation lock in the backup directory.
2. Refuse an existing dump or manifest at the generated timestamp.
3. Invoke the accepted engine with `-Action Backup` and
   `-ApproveProductionBackup`.
4. Invoke the engine again with the separate `-Action VerifyBackup` against
   the resulting dump and manifest.
5. Validate the complete managed artifact set and apply retention.
6. Record `FINAL SUCCESS` and exit zero.

Readiness, backup, manifest, verification, malformed-artifact, retention, and
overlap failures exit nonzero. Verification failure prevents retention. The
lock is tied to the backup directory rather than the configurable log
directory. Two invocations targeting the same backup set therefore conflict
even if they use different log directories. It is an open file handle with
exclusive sharing; Windows releases it if the wrapper exits or is terminated,
so a stale lock filename does not block a later run.

## Retention

Retention runs only after the new pair passes the separate verification step.
The newest 30 verified pairs are kept, ordered by the UTC timestamp embedded
in the exact filename. Before deleting anything, the wrapper:

- rejects any `sportsmodel-native-*` file that does not match the exact dump
  or manifest convention;
- rejects every unpaired dump or manifest;
- re-runs the accepted engine's `VerifyBackup` action for every older pair.

The separately verified current backup is always retained, even if another
artifact has an accidentally future-dated filename. The remaining 29 retained
pairs are the newest other pairs by embedded UTC timestamp. Only complete,
exactly named pairs outside that set are deleted. Unrelated files are ignored.
Any malformed, unpaired, or unverifiable artifact stops retention without
blindly deleting another pair. A filesystem failure while deleting a pair
fails the run nonzero and requires operator review.

## Proposed Scheduled Task

The current production writer schedule leaves the cleanest recurring window
after the 11:00 PM Pacific Late Night Snapshot and before the 6:00 AM Morning
Snapshot. The provisional deployment choice is **12:30 AM Pacific daily**.
This begins after Late Night's one-hour retry window ends at midnight and
finishes before the known Windows backup activity around 1:27-1:40 AM when the
normal run is short. The two-hour execution limit is a kill boundary, not a
claim that two hours of overlap is safe.

Re-audit every SportsModel, Windows backup, maintenance, and system task before
registration. If the 12:30 AM window is no longer clear, stop and choose a new
window through a separate review; do not silently register at another time.

Use the established local `Brian` identity with S4U, **Limited** run level,
local paths only, `IgnoreNew`, no catch-up, and a two-hour execution limit—but
only after the protected-runtime and least-privilege PostgreSQL executable
preflight described above passes. S4U is appropriate because the operation
needs no network resource or interactive desktop and the accepted engine uses
the dedicated protected credential.

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
        '"D:\SportsModelOps\native_postgresql_backup\' +
        'run_native_postgresql_backup.ps1"') `
    -WorkingDirectory "D:\SportsModelOps\native_postgresql_backup"
$trigger = New-ScheduledTaskTrigger -Daily -At "12:30 AM"
$principal = New-ScheduledTaskPrincipal `
    -UserId "AI-BETO\Brian" `
    -LogonType S4U `
    -RunLevel Limited
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

Before registration, confirm that 12:30 AM does not conflict with a newly added
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
$backup = "D:\SportsModelBackups\PostgreSQL\backups\sportsmodel-native-YYYYMMDDtHHMMSSz.dump"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
    -File "D:\SportsModelOps\native_postgresql_backup\invoke_native_postgresql_backup_restore_acceptance.ps1" `
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

## Controlled deployment and rollback prerequisites

Deployment is a separate approved change. In order: re-inventory the 12:30 AM
window; stage from the exact reviewed clean commit; inspect the manifest; grant
only the documented PostgreSQL client traversal/Read-Execute access; provision
the five-key credential with the protected file ACL; create the two empty
storage directories with their protected ACLs; run Plan and read-only Preflight
as the exact Limited S4U identity; perform a separately approved controlled
backup and verification; then register the task and compare its exported
definition with the reviewed definition.

Rollback does not touch PostgreSQL or any backup contents: disable and remove
only the new task, preserve its logs and dump/manifest pairs for review, and
retire the protected runtime only through a separately approved file operation.
Do not automatically remove the credential, runtime, storage, or PostgreSQL
client ACL entries from the wrapper or staging helper.
