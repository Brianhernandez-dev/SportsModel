[CmdletBinding()]
param(
    [ValidateSet(
        "Plan",
        "Preflight",
        "Backup",
        "VerifyBackup",
        "CreateRestoreTarget",
        "Restore",
        "VerifyRestore",
        "DropRestoreTarget"
    )]
    [string]$Action = "Plan",

    [string]$EnvironmentPath,

    [string]$PostgreSqlBinPath = "D:\PostgreSQL\16\server\bin",

    [string]$PythonPath,

    [string]$SourcePath,

    [string]$BackupPath,

    [string]$ManifestPath,

    [string]$TargetDatabase,

    [PSCredential]$AdminCredential,

    [switch]$ApproveProductionBackup,

    [switch]$ApproveCreateRestoreTarget,

    [switch]$ApproveRestore,

    [switch]$ApproveDropRestoreTarget
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ExpectedSourceDatabase = "sportsmodel"
$ExpectedSourcePort = 5432
$MinimumCompatibleMigration = 29
$RestoreTargetMarker = "sportsmodel-backup-restore-acceptance-v1"
$RestoreTargetPattern = (
    "^sportsmodel_restore_acceptance_" +
    "[0-9]{8}t[0-9]{6}z(?:_[a-z0-9]{1,8})?$"
)
$BackupFilePattern = "^sportsmodel-native-[0-9]{8}t[0-9]{6}z\.dump$"
$ImportantTables = @(
    "schema_migrations",
    "games",
    "game_results",
    "moneyline_daily_workflow_runs",
    "moneyline_prediction_runs",
    "moneyline_game_predictions",
    "odds_ingestion_runs",
    "odds_provider_event_observations",
    "odds_market_snapshots",
    "moneyline_prediction_market_evaluations",
    "moneyline_paper_candidate_settlements",
    "nfl_moneyline_prediction_runs",
    "nfl_moneyline_game_predictions",
    "nfl_moneyline_market_evaluation_runs",
    "nfl_moneyline_market_evaluations"
)

if ([string]::IsNullOrWhiteSpace($EnvironmentPath)) {
    $EnvironmentPath = Join-Path $RepositoryRoot ".env"
}
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
}
if ([string]::IsNullOrWhiteSpace($SourcePath)) {
    $SourcePath = Join-Path $RepositoryRoot "src"
}


function Write-AcceptanceLog {
    param([Parameter(Mandatory)][string]$Message)

    $Timestamp = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    Write-Host "[$Timestamp] $Message"
}


function Assert-ExplicitApproval {
    param(
        [Parameter(Mandatory)][bool]$Approved,
        [Parameter(Mandatory)][string]$ApprovalName,
        [Parameter(Mandatory)][string]$Operation
    )

    if (-not $Approved) {
        throw (
            "$Operation was refused. Supply -$ApprovalName only after " +
            "that exact consequential phase has been explicitly approved."
        )
    }
}


function Assert-SafeRestoreTarget {
    param([Parameter(Mandatory)][string]$DatabaseName)

    $NormalizedName = $DatabaseName.Trim().ToLowerInvariant()
    $ReservedNames = @(
        "sportsmodel",
        "postgres",
        "template0",
        "template1",
        "production",
        "prod",
        "sportsmodel_prod",
        "sportsmodel_production"
    )

    if ($NormalizedName -in $ReservedNames) {
        throw "Restore target '$DatabaseName' is a protected database name."
    }

    if ($NormalizedName -notmatch $RestoreTargetPattern) {
        throw (
            "Restore target '$DatabaseName' was refused. Disposable restore " +
            "targets must match $RestoreTargetPattern."
        )
    }

    if ($NormalizedName.Length -gt 63) {
        throw "Restore target names must be 63 characters or fewer."
    }

    return $NormalizedName
}


function Import-SportsModelEnvironment {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "SportsModel environment file was not found: $Path"
    }

    $Values = @{}
    foreach ($Line in Get-Content -LiteralPath $Path) {
        $Trimmed = $Line.Trim()
        if (
            [string]::IsNullOrWhiteSpace($Trimmed) -or
            $Trimmed.StartsWith("#")
        ) {
            continue
        }

        $Parts = $Trimmed.Split(@("="), 2, [StringSplitOptions]::None)
        if ($Parts.Count -ne 2) {
            continue
        }

        $Name = $Parts[0].Trim()
        if ($Name -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") {
            continue
        }

        $Value = $Parts[1].Trim()
        if (
            $Value.Length -ge 2 -and
            (
                ($Value.StartsWith('"') -and $Value.EndsWith('"')) -or
                ($Value.StartsWith("'") -and $Value.EndsWith("'"))
            )
        ) {
            $Value = $Value.Substring(1, $Value.Length - 2)
        }
        $Values[$Name] = $Value
    }

    return $Values
}


function Get-SourceConnection {
    $Values = Import-SportsModelEnvironment -Path $EnvironmentPath
    $RequiredNames = @(
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD"
    )
    foreach ($Name in $RequiredNames) {
        if (
            -not $Values.ContainsKey($Name) -or
            [string]::IsNullOrWhiteSpace($Values[$Name])
        ) {
            throw "Required database setting $Name is absent or empty."
        }
    }

    $HostName = $Values["POSTGRES_HOST"].Trim().ToLowerInvariant()
    if ($HostName -notin @("localhost", "127.0.0.1", "::1")) {
        throw "Production backup source must be a loopback PostgreSQL host."
    }

    $Port = 0
    if (-not [int]::TryParse($Values["POSTGRES_PORT"], [ref]$Port)) {
        throw "POSTGRES_PORT is not a valid integer."
    }
    if ($Port -ne $ExpectedSourcePort) {
        throw "Production backup source must use port $ExpectedSourcePort."
    }

    if ($Values["POSTGRES_DB"] -cne $ExpectedSourceDatabase) {
        throw (
            "Production backup source must be database " +
            "$ExpectedSourceDatabase."
        )
    }

    return @{
        Host = $Values["POSTGRES_HOST"]
        Port = $Port
        Database = $Values["POSTGRES_DB"]
        User = $Values["POSTGRES_USER"]
        Password = $Values["POSTGRES_PASSWORD"]
    }
}


function Get-PostgreSqlTools {
    $Tools = @{}
    foreach ($Name in @("pg_dump", "pg_restore", "psql", "createdb", "dropdb")) {
        $Path = Join-Path $PostgreSqlBinPath "$Name.exe"
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Required PostgreSQL tool was not found: $Path"
        }
        $Tools[$Name] = $Path
    }
    return $Tools
}


function Set-ProcessEnvironmentValue {
    param(
        [Parameter(Mandatory)][string]$Name,
        [AllowNull()][string]$Value
    )

    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}


function Invoke-PostgreSqlTool {
    param(
        [Parameter(Mandatory)][string]$ToolPath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][hashtable]$Connection,
        [bool]$ReadOnly = $false
    )

    $EnvironmentNames = @(
        "PGHOST",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGPASSWORD",
        "PGAPPNAME",
        "PGOPTIONS"
    )
    $PreviousValues = @{}
    foreach ($Name in $EnvironmentNames) {
        $PreviousValues[$Name] = [Environment]::GetEnvironmentVariable(
            $Name,
            "Process"
        )
    }

    try {
        Set-ProcessEnvironmentValue -Name "PGHOST" -Value $Connection.Host
        Set-ProcessEnvironmentValue -Name "PGPORT" -Value ([string]$Connection.Port)
        Set-ProcessEnvironmentValue -Name "PGDATABASE" -Value $Connection.Database
        Set-ProcessEnvironmentValue -Name "PGUSER" -Value $Connection.User
        Set-ProcessEnvironmentValue -Name "PGPASSWORD" -Value $Connection.Password
        Set-ProcessEnvironmentValue `
            -Name "PGAPPNAME" `
            -Value "sportsmodel_backup_restore_acceptance"
        if ($ReadOnly) {
            Set-ProcessEnvironmentValue `
                -Name "PGOPTIONS" `
                -Value "-c default_transaction_read_only=on"
        }
        else {
            Set-ProcessEnvironmentValue -Name "PGOPTIONS" -Value $null
        }

        $Output = @(& $ToolPath @Arguments 2>&1)
        $ExitCode = $LASTEXITCODE
    }
    finally {
        foreach ($Name in $EnvironmentNames) {
            Set-ProcessEnvironmentValue `
                -Name $Name `
                -Value $PreviousValues[$Name]
        }
    }

    if ($ExitCode -ne 0) {
        $Detail = (
            $Output |
                ForEach-Object { $_.ToString() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                Select-Object -Last 8
        ) -join [Environment]::NewLine
        throw (
            "PostgreSQL tool $([IO.Path]::GetFileName($ToolPath)) failed " +
            "with exit code $ExitCode. $Detail"
        )
    }

    return $Output
}


function Invoke-PsqlScalar {
    param(
        [Parameter(Mandatory)][hashtable]$Tools,
        [Parameter(Mandatory)][hashtable]$Connection,
        [Parameter(Mandatory)][string]$Sql,
        [bool]$ReadOnly = $true
    )

    $Output = Invoke-PostgreSqlTool `
        -ToolPath $Tools["psql"] `
        -Arguments @(
            "--no-password",
            "--no-psqlrc",
            "--set=ON_ERROR_STOP=1",
            "--tuples-only",
            "--no-align",
            "--dbname=$($Connection.Database)",
            "--command=$Sql"
        ) `
        -Connection $Connection `
        -ReadOnly $ReadOnly

    return (($Output | ForEach-Object { $_.ToString() }) -join "`n").Trim()
}


function Quote-SqlIdentifier {
    param([Parameter(Mandatory)][string]$Value)

    return '"' + $Value.Replace('"', '""') + '"'
}


function Assert-DatabaseIdentity {
    param(
        [Parameter(Mandatory)][hashtable]$Tools,
        [Parameter(Mandatory)][hashtable]$Connection,
        [Parameter(Mandatory)][string]$ExpectedDatabase
    )

    $Identity = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql (
            "SELECT concat_ws('|', current_database(), " +
            "inet_server_port(), pg_is_in_recovery());"
        )
    $ExpectedIdentity = "$ExpectedDatabase|$ExpectedSourcePort|f"
    if ($Identity -cne $ExpectedIdentity) {
        throw (
            "PostgreSQL identity check failed for database " +
            "$ExpectedDatabase. Observed: $Identity"
        )
    }
}


function Get-DatabaseContentSnapshot {
    param(
        [Parameter(Mandatory)][hashtable]$Tools,
        [Parameter(Mandatory)][hashtable]$Connection
    )

    $ServerVersion = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql "SELECT version();"
    $MigrationVersions = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql (
            "SELECT COALESCE(string_agg(version::text, ',' ORDER BY version), '') " +
            "FROM schema_migrations;"
        )
    $MigrationMax = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql "SELECT COALESCE(MAX(version), 0) FROM schema_migrations;"
    $RequiredMigrationPresent = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql (
            "SELECT EXISTS (SELECT 1 FROM schema_migrations " +
            "WHERE version = $MinimumCompatibleMigration);"
        )

    $TableCounts = [ordered]@{}
    foreach ($Table in $ImportantTables) {
        $Identifier = Quote-SqlIdentifier -Value $Table
        $Count = Invoke-PsqlScalar `
            -Tools $Tools `
            -Connection $Connection `
            -Sql "SELECT COUNT(*) FROM $Identifier;"
        $TableCounts[$Table] = [long]$Count
    }

    $Extensions = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql (
            "SELECT COALESCE(string_agg(extname || '=' || extversion, ',' " +
            "ORDER BY extname), '') FROM pg_extension;"
        )
    $Relations = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql (
            "SELECT COALESCE(string_agg(relkind::text || '=' || amount, ',' " +
            "ORDER BY relkind), '') FROM (SELECT relkind, COUNT(*)::text " +
            "AS amount FROM pg_class c JOIN pg_namespace n ON n.oid = " +
            "c.relnamespace WHERE n.nspname = 'public' GROUP BY relkind) s;"
        )
    $Sequences = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql (
            "SELECT COALESCE(string_agg(sequencename || '=' || " +
            "COALESCE(last_value::text, 'NULL'), ',' ORDER BY sequencename), " +
            "'') FROM pg_sequences WHERE schemaname = 'public';"
        )
    $InvalidConstraints = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql (
            "SELECT COALESCE(string_agg(conname, ',' ORDER BY conname), '') " +
            "FROM pg_constraint c JOIN pg_namespace n ON n.oid = " +
            "c.connamespace WHERE n.nspname = 'public' AND NOT convalidated;"
        )
    $Functions = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql (
            "SELECT COALESCE(string_agg(p.proname || '(' || " +
            "pg_get_function_identity_arguments(p.oid) || ')', ',' " +
            "ORDER BY p.proname, pg_get_function_identity_arguments(p.oid)), " +
            "'') FROM pg_proc p JOIN pg_namespace n ON n.oid = " +
            "p.pronamespace WHERE n.nspname = 'public';"
        )
    $Triggers = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql (
            "SELECT COALESCE(string_agg(c.relname || '.' || t.tgname, ',' " +
            "ORDER BY c.relname, t.tgname), '') FROM pg_trigger t JOIN " +
            "pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON " +
            "n.oid = c.relnamespace WHERE n.nspname = 'public' " +
            "AND NOT t.tgisinternal;"
        )
    $OrphanCount = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql @"
SELECT
    (SELECT COUNT(*) FROM moneyline_game_predictions p
        LEFT JOIN moneyline_prediction_runs r
            ON r.moneyline_prediction_run_id = p.moneyline_prediction_run_id
        WHERE r.moneyline_prediction_run_id IS NULL)
  + (SELECT COUNT(*) FROM odds_market_snapshots s
        LEFT JOIN odds_ingestion_runs r
            ON r.odds_ingestion_run_id = s.odds_ingestion_run_id
        WHERE r.odds_ingestion_run_id IS NULL)
  + (SELECT COUNT(*) FROM moneyline_prediction_market_evaluations e
        LEFT JOIN moneyline_game_predictions p
            ON p.moneyline_game_prediction_id = e.moneyline_game_prediction_id
        LEFT JOIN odds_ingestion_runs r
            ON r.odds_ingestion_run_id = e.odds_ingestion_run_id
        LEFT JOIN odds_market_snapshots s
            ON s.odds_market_snapshot_id = e.odds_market_snapshot_id
        WHERE p.moneyline_game_prediction_id IS NULL
           OR r.odds_ingestion_run_id IS NULL
           OR s.odds_market_snapshot_id IS NULL)
  + (SELECT COUNT(*) FROM moneyline_paper_candidate_settlements s
        LEFT JOIN moneyline_prediction_market_evaluations e
            ON e.moneyline_prediction_market_evaluation_id =
               s.moneyline_prediction_market_evaluation_id
        WHERE e.moneyline_prediction_market_evaluation_id IS NULL);
"@

    return [pscustomobject][ordered]@{
        ServerVersion = $ServerVersion
        MigrationVersions = $MigrationVersions
        MigrationMax = [int]$MigrationMax
        RequiredMigrationPresent = ($RequiredMigrationPresent -eq "t")
        Extensions = $Extensions
        PublicRelations = $Relations
        PublicSequences = $Sequences
        InvalidConstraints = $InvalidConstraints
        PublicFunctions = $Functions
        PublicTriggers = $Triggers
        ImportantTableCounts = [pscustomobject]$TableCounts
        RepresentativeOrphanCount = [long]$OrphanCount
    }
}


function ConvertTo-StableJson {
    param([Parameter(Mandatory)]$Value)

    return ($Value | ConvertTo-Json -Depth 12 -Compress)
}


function Assert-ContentMatches {
    param(
        [Parameter(Mandatory)]$Expected,
        [Parameter(Mandatory)]$Actual,
        [Parameter(Mandatory)][string]$Description
    )

    if ((ConvertTo-StableJson $Expected) -cne (ConvertTo-StableJson $Actual)) {
        throw "$Description does not match the accepted source snapshot."
    }
}


function Invoke-NativeReadinessPreflight {
    $HelperPath = Join-Path $PSScriptRoot "wait_for_sportsmodel_database.ps1"
    if (-not (Test-Path -LiteralPath $HelperPath -PathType Leaf)) {
        throw "Shared database readiness helper was not found: $HelperPath"
    }

    $PreviousEnvironmentFile = $env:SPORTSMODEL_ENV_FILE
    try {
        $env:SPORTSMODEL_ENV_FILE = $EnvironmentPath
        . $HelperPath
        Wait-SportsModelDatabaseReady `
            -PythonPath $PythonPath `
            -SourcePath $SourcePath `
            -TimeoutSeconds 30 `
            -PollSeconds 2
    }
    finally {
        Set-ProcessEnvironmentValue `
            -Name "SPORTSMODEL_ENV_FILE" `
            -Value $PreviousEnvironmentFile
    }
}


function Get-ToolVersions {
    param([Parameter(Mandatory)][hashtable]$Tools)

    $Versions = [ordered]@{}
    foreach ($Name in @("pg_dump", "pg_restore", "psql", "createdb", "dropdb")) {
        $Output = @(& $Tools[$Name] --version 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to read the version of $($Tools[$Name])."
        }
        $Versions[$Name] = ($Output -join " ").Trim()
    }
    return [pscustomobject]$Versions
}


function Invoke-Preflight {
    Write-AcceptanceLog "Running read-only native PostgreSQL preflight."
    $Connection = Get-SourceConnection
    $Tools = Get-PostgreSqlTools
    Invoke-NativeReadinessPreflight
    Assert-DatabaseIdentity `
        -Tools $Tools `
        -Connection $Connection `
        -ExpectedDatabase $ExpectedSourceDatabase

    $Content = Get-DatabaseContentSnapshot `
        -Tools $Tools `
        -Connection $Connection
    if (
        -not $Content.RequiredMigrationPresent -or
        $Content.MigrationMax -lt $MinimumCompatibleMigration
    ) {
        throw (
            "Source migration compatibility failed: required migration " +
            "$MinimumCompatibleMigration, observed max " +
            "$($Content.MigrationMax)."
        )
    }
    if ($Content.RepresentativeOrphanCount -ne 0) {
        throw "Representative source integrity checks found orphan rows."
    }

    $Size = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql (
            "SELECT pg_database_size(current_database()) || '|' || " +
            "pg_size_pretty(pg_database_size(current_database()));"
        )
    $RoleCapability = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql (
            "SELECT concat_ws('|', current_user, rolsuper, rolcreatedb) " +
            "FROM pg_roles WHERE rolname = current_user;"
        )
    $Versions = Get-ToolVersions -Tools $Tools

    Write-AcceptanceLog (
        "PREFLIGHT READY: source=localhost:$ExpectedSourcePort/" +
        "$ExpectedSourceDatabase migration=$($Content.MigrationMax) " +
        "size=$Size role=$RoleCapability"
    )
    Write-Host (ConvertTo-StableJson $Versions)
}


function Assert-BackupInputs {
    if ([string]::IsNullOrWhiteSpace($BackupPath)) {
        throw "BackupPath is required for action $Action."
    }
    $script:BackupPath = [IO.Path]::GetFullPath($BackupPath)
    if ([IO.Path]::GetExtension($script:BackupPath) -cne ".dump") {
        throw "BackupPath must use the .dump extension."
    }
    $BackupFileName = [IO.Path]::GetFileName($script:BackupPath)
    if ($BackupFileName -cnotmatch $BackupFilePattern) {
        throw (
            "Backup filename '$BackupFileName' was refused. Timestamped " +
            "backup filenames must match $BackupFilePattern."
        )
    }

    if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
        $script:ManifestPath = "$($script:BackupPath).manifest.json"
    }
    else {
        $script:ManifestPath = [IO.Path]::GetFullPath($ManifestPath)
    }
}


function Read-AcceptanceManifest {
    Assert-BackupInputs
    if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) {
        throw "Backup file was not found: $BackupPath"
    }
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "Backup manifest was not found: $ManifestPath"
    }
    return (Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json)
}


function Test-BackupArtifact {
    param(
        [Parameter(Mandatory)][hashtable]$Tools,
        [Parameter(Mandatory)]$Manifest
    )

    $File = Get-Item -LiteralPath $BackupPath
    if ($File.Length -le 0) {
        throw "Backup file is empty: $BackupPath"
    }

    $ActualHash = (Get-FileHash -LiteralPath $BackupPath -Algorithm SHA256).Hash
    if ($ActualHash -cne $Manifest.BackupSha256) {
        throw "Backup SHA-256 does not match the acceptance manifest."
    }
    if ([long]$File.Length -ne [long]$Manifest.BackupSizeBytes) {
        throw "Backup size does not match the acceptance manifest."
    }

    $Toc = @(& $Tools["pg_restore"] --list $BackupPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $Toc.Count -eq 0) {
        throw "pg_restore --list rejected the backup artifact."
    }

    Write-AcceptanceLog (
        "BACKUP VERIFIED: bytes=$($File.Length) sha256=$ActualHash " +
        "toc_lines=$($Toc.Count)"
    )
}


function Invoke-Backup {
    Assert-ExplicitApproval `
        -Approved $ApproveProductionBackup.IsPresent `
        -ApprovalName "ApproveProductionBackup" `
        -Operation "Production backup creation"
    Assert-BackupInputs

    $Directory = Split-Path -Parent $BackupPath
    if (-not (Test-Path -LiteralPath $Directory -PathType Container)) {
        throw "Backup directory must already exist: $Directory"
    }
    if (Test-Path -LiteralPath $BackupPath) {
        throw "BackupPath already exists; overwrite is refused: $BackupPath"
    }
    if (Test-Path -LiteralPath $ManifestPath) {
        throw "ManifestPath already exists; overwrite is refused: $ManifestPath"
    }

    $Connection = Get-SourceConnection
    $Tools = Get-PostgreSqlTools
    Invoke-NativeReadinessPreflight
    Assert-DatabaseIdentity `
        -Tools $Tools `
        -Connection $Connection `
        -ExpectedDatabase $ExpectedSourceDatabase

    $Before = Get-DatabaseContentSnapshot `
        -Tools $Tools `
        -Connection $Connection
    if ($Before.RepresentativeOrphanCount -ne 0) {
        throw "Backup refused because source integrity checks failed."
    }

    Write-AcceptanceLog "Creating custom-format production backup."
    Invoke-PostgreSqlTool `
        -ToolPath $Tools["pg_dump"] `
        -Arguments @(
            "--format=custom",
            "--compress=6",
            "--no-password",
            "--file=$BackupPath",
            "--dbname=$ExpectedSourceDatabase"
        ) `
        -Connection $Connection `
        -ReadOnly $true | Out-Null

    $After = Get-DatabaseContentSnapshot `
        -Tools $Tools `
        -Connection $Connection
    Assert-ContentMatches `
        -Expected $Before `
        -Actual $After `
        -Description "Production source after pg_dump"

    $File = Get-Item -LiteralPath $BackupPath
    if ($File.Length -le 0) {
        throw "pg_dump produced an empty backup artifact."
    }

    $Manifest = [pscustomobject][ordered]@{
        AcceptanceFormatVersion = 1
        CreatedAtUtc = [DateTimeOffset]::UtcNow.ToString("o")
        SourceHost = "localhost"
        SourcePort = $ExpectedSourcePort
        SourceDatabase = $ExpectedSourceDatabase
        SourceContent = $Before
        SourceDatabaseSizeBytes = [long](Invoke-PsqlScalar `
            -Tools $Tools `
            -Connection $Connection `
            -Sql "SELECT pg_database_size(current_database());")
        ToolVersions = Get-ToolVersions -Tools $Tools
        BackupFileName = $File.Name
        BackupSizeBytes = [long]$File.Length
        BackupSha256 = (Get-FileHash `
            -LiteralPath $BackupPath `
            -Algorithm SHA256).Hash
    }
    $Manifest | ConvertTo-Json -Depth 12 |
        Set-Content -LiteralPath $ManifestPath -Encoding utf8

    Test-BackupArtifact -Tools $Tools -Manifest $Manifest
}


function Invoke-VerifyBackup {
    $Tools = Get-PostgreSqlTools
    $Manifest = Read-AcceptanceManifest
    Test-BackupArtifact -Tools $Tools -Manifest $Manifest
}


function Get-AdminConnection {
    param([Parameter(Mandatory)][hashtable]$SourceConnection)

    if ($null -eq $AdminCredential) {
        throw (
            "AdminCredential is required for disposable database creation " +
            "or cleanup. Supply it interactively; never place it in source."
        )
    }
    return @{
        Host = $SourceConnection.Host
        Port = $SourceConnection.Port
        Database = "postgres"
        User = $AdminCredential.UserName
        Password = $AdminCredential.GetNetworkCredential().Password
    }
}


function Test-DatabaseExists {
    param(
        [Parameter(Mandatory)][hashtable]$Tools,
        [Parameter(Mandatory)][hashtable]$Connection,
        [Parameter(Mandatory)][string]$DatabaseName
    )

    $EscapedName = $DatabaseName.Replace("'", "''")
    return (
        (Invoke-PsqlScalar `
            -Tools $Tools `
            -Connection $Connection `
            -Sql (
                "SELECT EXISTS (SELECT 1 FROM pg_database " +
                "WHERE datname = '$EscapedName');"
            )) -eq "t"
    )
}


function Assert-RestoreTargetMarker {
    param(
        [Parameter(Mandatory)][hashtable]$Tools,
        [Parameter(Mandatory)][hashtable]$Connection,
        [Parameter(Mandatory)][string]$DatabaseName,
        [Parameter(Mandatory)][string]$ExpectedOwner
    )

    $EscapedName = $DatabaseName.Replace("'", "''")
    $Observed = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $Connection `
        -Sql (
            "SELECT concat_ws('|', pg_get_userbyid(datdba), " +
            "COALESCE(shobj_description(oid, 'pg_database'), '')) " +
            "FROM pg_database WHERE datname = '$EscapedName';"
        )
    $Expected = "$ExpectedOwner|$RestoreTargetMarker"
    if ($Observed -cne $Expected) {
        throw (
            "Restore target marker/owner check failed for $DatabaseName. " +
            "Destructive or restore work was refused."
        )
    }
}


function Invoke-CreateRestoreTarget {
    $SafeTarget = Assert-SafeRestoreTarget -DatabaseName $TargetDatabase
    Assert-ExplicitApproval `
        -Approved $ApproveCreateRestoreTarget.IsPresent `
        -ApprovalName "ApproveCreateRestoreTarget" `
        -Operation "Disposable restore database creation"

    $SourceConnection = Get-SourceConnection
    $Tools = Get-PostgreSqlTools
    $AdminConnection = Get-AdminConnection -SourceConnection $SourceConnection
    $AdminCapability = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $AdminConnection `
        -Sql (
            "SELECT rolsuper OR rolcreatedb FROM pg_roles " +
            "WHERE rolname = current_user;"
        )
    if ($AdminCapability -ne "t") {
        throw "Supplied administrator role cannot create databases."
    }
    if (
        Test-DatabaseExists `
            -Tools $Tools `
            -Connection $AdminConnection `
            -DatabaseName $SafeTarget
    ) {
        throw "Restore target already exists; reuse is refused: $SafeTarget"
    }

    Invoke-PostgreSqlTool `
        -ToolPath $Tools["createdb"] `
        -Arguments @(
            "--no-password",
            "--maintenance-db=postgres",
            "--owner=$($SourceConnection.User)",
            $SafeTarget,
            $RestoreTargetMarker
        ) `
        -Connection $AdminConnection | Out-Null
    Assert-RestoreTargetMarker `
        -Tools $Tools `
        -Connection $SourceConnection `
        -DatabaseName $SafeTarget `
        -ExpectedOwner $SourceConnection.User
    Write-AcceptanceLog "Created isolated restore target $SafeTarget."
}


function Invoke-Restore {
    $SafeTarget = Assert-SafeRestoreTarget -DatabaseName $TargetDatabase
    Assert-ExplicitApproval `
        -Approved $ApproveRestore.IsPresent `
        -ApprovalName "ApproveRestore" `
        -Operation "Restore into disposable database"

    $SourceConnection = Get-SourceConnection
    $Tools = Get-PostgreSqlTools
    $Manifest = Read-AcceptanceManifest
    Test-BackupArtifact -Tools $Tools -Manifest $Manifest

    $TargetConnection = $SourceConnection.Clone()
    $TargetConnection.Database = $SafeTarget
    Assert-RestoreTargetMarker `
        -Tools $Tools `
        -Connection $SourceConnection `
        -DatabaseName $SafeTarget `
        -ExpectedOwner $SourceConnection.User
    Assert-DatabaseIdentity `
        -Tools $Tools `
        -Connection $TargetConnection `
        -ExpectedDatabase $SafeTarget
    $ExistingObjects = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $TargetConnection `
        -Sql (
            "SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON " +
            "n.oid = c.relnamespace WHERE n.nspname = 'public' " +
            "AND c.relkind IN ('r','p','S','v','m','f');"
        )
    if ([long]$ExistingObjects -ne 0) {
        throw "Restore target is not empty; destructive cleanup is refused."
    }

    Invoke-PostgreSqlTool `
        -ToolPath $Tools["pg_restore"] `
        -Arguments @(
            "--exit-on-error",
            "--single-transaction",
            "--no-owner",
            "--no-privileges",
            "--no-password",
            "--dbname=$SafeTarget",
            $BackupPath
        ) `
        -Connection $TargetConnection | Out-Null
    Write-AcceptanceLog "Restore completed into isolated target $SafeTarget."
}


function Invoke-VerifyRestore {
    $SafeTarget = Assert-SafeRestoreTarget -DatabaseName $TargetDatabase
    $SourceConnection = Get-SourceConnection
    $Tools = Get-PostgreSqlTools
    $Manifest = Read-AcceptanceManifest
    Test-BackupArtifact -Tools $Tools -Manifest $Manifest

    Assert-DatabaseIdentity `
        -Tools $Tools `
        -Connection $SourceConnection `
        -ExpectedDatabase $ExpectedSourceDatabase
    $CurrentSource = Get-DatabaseContentSnapshot `
        -Tools $Tools `
        -Connection $SourceConnection
    Assert-ContentMatches `
        -Expected $Manifest.SourceContent `
        -Actual $CurrentSource `
        -Description "Current production source"

    $TargetConnection = $SourceConnection.Clone()
    $TargetConnection.Database = $SafeTarget
    Assert-RestoreTargetMarker `
        -Tools $Tools `
        -Connection $SourceConnection `
        -DatabaseName $SafeTarget `
        -ExpectedOwner $SourceConnection.User
    Assert-DatabaseIdentity `
        -Tools $Tools `
        -Connection $TargetConnection `
        -ExpectedDatabase $SafeTarget
    $TargetWriteState = Invoke-PsqlScalar `
        -Tools $Tools `
        -Connection $TargetConnection `
        -ReadOnly $false `
        -Sql (
            "SELECT concat_ws('|', pg_is_in_recovery(), " +
            "current_setting('default_transaction_read_only'));"
        )
    if ($TargetWriteState -cne "f|off") {
        throw "Restored target is not a writable primary database."
    }

    $TargetContent = Get-DatabaseContentSnapshot `
        -Tools $Tools `
        -Connection $TargetConnection
    Assert-ContentMatches `
        -Expected $Manifest.SourceContent `
        -Actual $TargetContent `
        -Description "Restored database"
    if ($TargetContent.RepresentativeOrphanCount -ne 0) {
        throw "Restored database integrity checks found orphan rows."
    }

    Write-AcceptanceLog (
        "RESTORE ACCEPTED: target=$SafeTarget source_unchanged=true " +
        "migration=$($TargetContent.MigrationMax) integrity=passed"
    )
}


function Invoke-DropRestoreTarget {
    $SafeTarget = Assert-SafeRestoreTarget -DatabaseName $TargetDatabase
    Assert-ExplicitApproval `
        -Approved $ApproveDropRestoreTarget.IsPresent `
        -ApprovalName "ApproveDropRestoreTarget" `
        -Operation "Disposable restore database cleanup"

    $SourceConnection = Get-SourceConnection
    $Tools = Get-PostgreSqlTools
    $AdminConnection = Get-AdminConnection -SourceConnection $SourceConnection
    if (
        -not (Test-DatabaseExists `
            -Tools $Tools `
            -Connection $AdminConnection `
            -DatabaseName $SafeTarget)
    ) {
        throw "Restore target does not exist: $SafeTarget"
    }
    Assert-RestoreTargetMarker `
        -Tools $Tools `
        -Connection $AdminConnection `
        -DatabaseName $SafeTarget `
        -ExpectedOwner $SourceConnection.User

    Invoke-PostgreSqlTool `
        -ToolPath $Tools["dropdb"] `
        -Arguments @(
            "--no-password",
            "--maintenance-db=postgres",
            $SafeTarget
        ) `
        -Connection $AdminConnection | Out-Null
    Write-AcceptanceLog "Dropped approved disposable target $SafeTarget."
}


if ($Action -in @(
    "CreateRestoreTarget",
    "Restore",
    "VerifyRestore",
    "DropRestoreTarget"
)) {
    $TargetDatabase = Assert-SafeRestoreTarget -DatabaseName $TargetDatabase
}

switch ($Action) {
    "Plan" {
        if (-not [string]::IsNullOrWhiteSpace($TargetDatabase)) {
            $TargetDatabase = Assert-SafeRestoreTarget `
                -DatabaseName $TargetDatabase
        }
        Write-Host "PLAN ONLY - no database or backup operation was executed."
        Write-Host (
            "Actions are separate: Preflight, Backup, VerifyBackup, " +
            "CreateRestoreTarget, Restore, VerifyRestore, DropRestoreTarget."
        )
        Write-Host (
            "Production is accepted only when its content snapshot remains " +
            "identical through restore verification."
        )
        Write-Host (
            "Disposable targets must match $RestoreTargetPattern; production " +
            "and system database names are always refused."
        )
    }
    "Preflight" { Invoke-Preflight }
    "Backup" { Invoke-Backup }
    "VerifyBackup" { Invoke-VerifyBackup }
    "CreateRestoreTarget" { Invoke-CreateRestoreTarget }
    "Restore" { Invoke-Restore }
    "VerifyRestore" { Invoke-VerifyRestore }
    "DropRestoreTarget" { Invoke-DropRestoreTarget }
}
