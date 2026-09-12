#requires -Version 7.0

[CmdletBinding()]
param(
    [ValidateSet('Plan', 'Apply', 'Cleanup')]
    [string]$Action = 'Plan',
    [Parameter(Mandatory)]
    [string]$BackendConfig,
    [string]$ExpectedRevision,
    [ValidateRange(1, 24)]
    [int]$MaximumBackupAgeHours = 4,
    [string]$ConfirmBootstrap
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$foundationDirectory = Join-Path $repositoryRoot 'infrastructure\terraform\foundation'
$templatePath = Join-Path $repositoryRoot 'database\bootstrap\V0001__establish_schema_ownership.sql.template'
$secureRuntime = Join-Path $repositoryRoot 'secure-runtime'
$temporaryDirectory = Join-Path $secureRuntime 'temp'
$recoveryDirectory = Join-Path $secureRuntime 'bootstrap-recovery'
$recoveryMarkerPath = Join-Path $recoveryDirectory 'ee003-development.json'
$bootstrapLockPath = Join-Path $recoveryDirectory 'ee003-development.lock'
$gcloudConfig = Join-Path $secureRuntime 'gcloud-config'
$expectedApplyConfirmation = 'BOOTSTRAP-EE-003-development'
$expectedCleanupConfirmation = 'CLEANUP-EE-003-development'
$DatabaseName = 'engagement'
$ApplicationSchema = 'engagement_app'
$MigrationSchema = 'engagement_migrations'
$BackupDescription = 'Pre-EE-003 approved schema deployment safety backup'

function Resolve-IgnoredInputFile {
    param([Parameter(Mandatory)] [string]$Path, [Parameter(Mandatory)] [string]$Label)
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $relative = [IO.Path]::GetRelativePath($repositoryRoot, $resolved).Replace('\', '/')
    if ($relative -eq '..' -or $relative.StartsWith('../')) {
        throw "$Label must stay inside the project workspace."
    }
    & git -C $repositoryRoot check-ignore --quiet -- $relative
    if ($LASTEXITCODE -ne 0) { throw "$Label must be excluded from Git." }
    & git -C $repositoryRoot ls-files --error-unmatch -- $relative 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { throw "$Label must not be tracked by Git." }
    return $resolved
}

function Resolve-GcloudCommand {
    $workspaceInstall = Join-Path $repositoryRoot 'tools-runtime\google-cloud-sdk\bin\gcloud.cmd'
    if (Test-Path -LiteralPath $workspaceInstall -PathType Leaf) { return $workspaceInstall }
    $installed = Get-Command gcloud.cmd, gcloud -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($installed) { return $installed.Source }
    throw 'Google Cloud command-line tools were not found.'
}

function Resolve-TerraformCommand {
    $workspaceInstall = Join-Path $repositoryRoot 'tools-runtime\terraform-1.16.2\terraform.exe'
    if (Test-Path -LiteralPath $workspaceInstall -PathType Leaf) { return $workspaceInstall }
    $installed = Get-Command terraform -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($installed) { return $installed.Source }
    throw 'Terraform was not found.'
}

function Invoke-GcloudQuiet {
    param([Parameter(Mandatory)] [string[]]$Arguments)
    $output = & $script:gcloud @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw 'A Google Cloud operation failed. Review the protected local Google Cloud log.'
    }
    return $output
}

function Invoke-TerraformQuiet {
    param([Parameter(Mandatory)] [string[]]$Arguments)
    $output = & $script:terraform @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'A protected Terraform state operation failed.' }
    return $output
}

function Read-StateOutput {
    param([Parameter(Mandatory)] [object]$Outputs, [Parameter(Mandatory)] [string]$Name)
    $property = $Outputs.PSObject.Properties[$Name]
    if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value.value)) {
        throw "Protected Terraform output $Name is missing."
    }
    return [string]$property.Value.value
}

function Quote-PostgresIdentifier {
    param([Parameter(Mandatory)] [string]$Value)
    return '"' + $Value.Replace('"', '""') + '"'
}

function Quote-PostgresLiteralContent {
    param([Parameter(Mandatory)] [string]$Value)
    return $Value.Replace("'", "''")
}

function Assert-SafeRoleName {
    param([Parameter(Mandatory)] [string]$Value, [Parameter(Mandatory)] [string]$Label)
    if ($Value -notmatch '^[a-z0-9_.@-]{1,63}$') {
        throw "$Label in protected Terraform state is not a safe PostgreSQL role name."
    }
}

function Get-DatabaseStatusCode {
    param([object]$Status)
    if ($null -eq $Status -or $null -eq $Status.PSObject.Properties['code']) { return 0 }
    $rawCode = [string]$Status.code
    if ([string]::IsNullOrWhiteSpace($rawCode)) { return 0 }
    $code = 0
    if (-not [int]::TryParse($rawCode, [ref]$code)) {
        throw 'Google Cloud returned an invalid database status code.'
    }
    return $code
}

function Assert-ExecuteSqlResponse {
    param([Parameter(Mandatory)] [object]$Response)
    if ((Get-DatabaseStatusCode -Status $Response.status) -ne 0) {
        throw 'The database rejected the reviewed bootstrap transaction.'
    }
    if ([bool]$Response.partialResult) {
        throw 'Google Cloud returned an incomplete database result.'
    }

    $results = @($Response.results)
    if ($results.Count -eq 0) {
        throw 'Google Cloud returned no database results for the bootstrap transaction.'
    }
    foreach ($result in $results) {
        if ((Get-DatabaseStatusCode -Status $result.status) -ne 0) {
            throw 'One database statement in the bootstrap transaction failed.'
        }
        if ([bool]$result.partialResult) {
            throw 'One database statement returned an incomplete result.'
        }
    }

    $finalResult = $results[-1]
    $expectedColumns = @('correct_database', 'application_schema_ready', 'migration_schema_ready')
    $actualColumns = @($finalResult.columns | ForEach-Object { [string]$_.name })
    if ($actualColumns.Count -ne $expectedColumns.Count -or
        (Compare-Object -ReferenceObject $expectedColumns -DifferenceObject $actualColumns -SyncWindow 0)) {
        throw 'The final database verification result has unexpected columns.'
    }
    $rows = @($finalResult.rows)
    if ($rows.Count -ne 1) {
        throw 'The final database verification did not return exactly one row.'
    }
    $values = @($rows[0].values)
    if ($values.Count -ne 3) {
        throw 'The final database verification did not return all three checks.'
    }
    foreach ($value in $values) {
        if ([bool]$value.nullValue -or ([string]$value.value).ToLowerInvariant() -notin @('true', 't')) {
            throw 'The final database verification did not confirm every required condition.'
        }
    }
}

if (-not (Test-Path -LiteralPath $gcloudConfig -PathType Container)) {
    throw 'The protected D-drive Google Cloud configuration is missing.'
}
if (-not (Test-Path -LiteralPath $templatePath -PathType Leaf)) {
    throw 'The reviewed database bootstrap template is missing.'
}

$resolvedBackend = Resolve-IgnoredInputFile -Path $BackendConfig -Label 'BackendConfig'
$previousCloudSdkConfig = $env:CLOUDSDK_CONFIG
$previousAccessToken = $env:GOOGLE_OAUTH_ACCESS_TOKEN
$env:CLOUDSDK_CONFIG = $gcloudConfig
$bootstrapLockHandle = $null
$temporarySqlPath = $null
$temporaryOperator = $null
$temporaryDatabaseUserMayExist = $false
$dataApiMayBeEnabled = $false
$recoveryMarkerCreatedThisRun = $false
$cloudMutationAttempted = $false
$dataApiClosureAttempted = $false
$operatorClosureAttempted = $false
$finalCleanupVerified = $false
$bootstrapCommitted = $false
$cleanupErrors = [System.Collections.Generic.List[string]]::new()

try {
    $gcloud = Resolve-GcloudCommand
    $terraform = Resolve-TerraformCommand
    New-Item -ItemType Directory -Path $recoveryDirectory -Force | Out-Null
    try {
        $bootstrapLockHandle = [IO.File]::Open(
            $bootstrapLockPath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
    }
    catch [IO.IOException] {
        throw 'Another database bootstrap or cleanup process is already running.'
    }
    $accessToken = [string](Invoke-GcloudQuiet -Arguments @('auth', 'print-access-token', '--quiet'))
    if ([string]::IsNullOrWhiteSpace($accessToken)) {
        throw 'A short-lived Google Cloud access token could not be obtained.'
    }
    $env:GOOGLE_OAUTH_ACCESS_TOKEN = $accessToken.Trim()
    $terraformDirectoryArgument = "-chdir=$foundationDirectory"
    Invoke-TerraformQuiet -Arguments @(
        $terraformDirectoryArgument, 'init', '-input=false', "-backend-config=$resolvedBackend"
    ) | Out-Null
    $stateRaw = Invoke-TerraformQuiet -Arguments @($terraformDirectoryArgument, 'output', '-json')
    $stateOutputs = ($stateRaw -join "`n") | ConvertFrom-Json

    $Environment = Read-StateOutput -Outputs $stateOutputs -Name 'deployment_environment'
    $ProjectId = Read-StateOutput -Outputs $stateOutputs -Name 'deployment_project_id'
    $Region = Read-StateOutput -Outputs $stateOutputs -Name 'deployment_region'
    $InstanceName = Read-StateOutput -Outputs $stateOutputs -Name 'database_instance_name'
    $stateDatabaseName = Read-StateOutput -Outputs $stateOutputs -Name 'database_name'
    $MigrationRole = Read-StateOutput -Outputs $stateOutputs -Name 'database_migration_iam_user'
    $RuntimeRole = Read-StateOutput -Outputs $stateOutputs -Name 'database_runtime_iam_user'
    $repositorySlug = Read-StateOutput -Outputs $stateOutputs -Name 'github_repository_slug'
    $connectionName = Read-StateOutput -Outputs $stateOutputs -Name 'database_connection_name'

    if ($Environment -ne 'development' -or $stateDatabaseName -ne $DatabaseName -or
        $connectionName -ne "${ProjectId}:${Region}:${InstanceName}") {
        throw 'Protected Terraform state does not identify the approved development database.'
    }
    if ($ProjectId -notmatch '^[a-z][a-z0-9-]{4,28}[a-z0-9]$' -or
        $Region -notmatch '^[a-z]+-[a-z]+[0-9]+$' -or
        $InstanceName -notmatch '^[a-z][a-z0-9-]{0,61}[a-z0-9]$' -or
        $repositorySlug -notmatch '^[A-Za-z0-9-]+/[A-Za-z0-9_.-]+$') {
        throw 'A protected Terraform target value is malformed.'
    }
    Assert-SafeRoleName -Value $MigrationRole -Label 'MigrationRole'
    Assert-SafeRoleName -Value $RuntimeRole -Label 'RuntimeRole'
    if ($MigrationRole -eq $RuntimeRole) {
        throw 'The protected migration and runtime roles must be different.'
    }

    $activeOperator = [string](Invoke-GcloudQuiet -Arguments @(
        'auth', 'list', '--filter=status:ACTIVE', '--format=value(account)'
    ))
    $activeOperator = $activeOperator.Trim()
    if ($activeOperator -notmatch '^[a-z0-9.!#$%&''*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}$' -or
        $activeOperator.EndsWith('.gserviceaccount.com')) {
        throw 'The active Google Cloud identity must be one named human operator.'
    }

    if ($Action -eq 'Cleanup') {
        if ($ConfirmBootstrap -cne $expectedCleanupConfirmation) {
            throw "Cleanup requires -ConfirmBootstrap $expectedCleanupConfirmation."
        }
        if (-not (Test-Path -LiteralPath $recoveryMarkerPath -PathType Leaf)) {
            throw 'No protected bootstrap recovery marker exists; automatic deletion is not authorised.'
        }
        $marker = Get-Content -LiteralPath $recoveryMarkerPath -Raw | ConvertFrom-Json
        if ($marker.projectId -ne $ProjectId -or $marker.instanceName -ne $InstanceName -or
            $marker.databaseName -ne $DatabaseName) {
            throw 'The protected recovery marker does not match the approved target.'
        }
        $temporaryOperator = [string]$marker.operator
        if ($temporaryOperator -notmatch '^[a-z0-9.!#$%&''*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}$' -or
            $temporaryOperator.EndsWith('.gserviceaccount.com')) {
            throw 'The protected recovery marker does not identify a valid temporary human operator.'
        }
        $candidateSqlPath = [IO.Path]::GetFullPath([string]$marker.renderedSqlPath)
        $approvedTemporaryRoot = [IO.Path]::GetFullPath($temporaryDirectory) + [IO.Path]::DirectorySeparatorChar
        if (-not $candidateSqlPath.StartsWith($approvedTemporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'The protected recovery marker points outside the approved temporary directory.'
        }
        $temporarySqlPath = $candidateSqlPath
        $temporaryDatabaseUserMayExist = $true
        $dataApiMayBeEnabled = $true
    }
    else {
        $instanceRaw = Invoke-GcloudQuiet -Arguments @(
            'sql', 'instances', 'describe', $InstanceName,
            "--project=$ProjectId", '--format=json'
        )
        $instance = ($instanceRaw -join "`n") | ConvertFrom-Json
        if ($instance.state -ne 'RUNNABLE' -or $instance.databaseVersion -ne 'POSTGRES_16') {
            throw 'The approved PostgreSQL 16 development database is not ready.'
        }
        if ([bool]$instance.settings.ipConfiguration.ipv4Enabled -or
            [string]::IsNullOrWhiteSpace([string]$instance.settings.ipConfiguration.privateNetwork)) {
            throw 'The database must remain private.'
        }
        if (-not [bool]$instance.settings.backupConfiguration.enabled -or
            -not [bool]$instance.settings.backupConfiguration.pointInTimeRecoveryEnabled) {
            throw 'Backup and point-in-time recovery must be enabled.'
        }
        if (Test-Path -LiteralPath $recoveryMarkerPath -PathType Leaf) {
            throw 'A previous bootstrap may have been interrupted. Run the explicit Cleanup action first.'
        }
        if ($instance.settings.dataApiAccess -eq 'ALLOW_DATA_API') {
            throw 'The temporary Data API path must be closed before bootstrap begins.'
        }

        $databaseRaw = Invoke-GcloudQuiet -Arguments @(
            'sql', 'databases', 'list', "--instance=$InstanceName",
            "--project=$ProjectId", '--format=json'
        )
        $databases = @(($databaseRaw -join "`n") | ConvertFrom-Json)
        $unexpectedDatabases = @($databases | Where-Object { $_.name -notin @($DatabaseName, 'postgres') })
        if (-not ($databases.name -contains $DatabaseName) -or $unexpectedDatabases.Count -ne 0) {
            throw 'The Cloud SQL instance is not the approved dedicated development database.'
        }

        $usersRaw = Invoke-GcloudQuiet -Arguments @(
            'sql', 'users', 'list', "--instance=$InstanceName",
            "--project=$ProjectId", '--format=json'
        )
        $databaseUsers = @(($usersRaw -join "`n") | ConvertFrom-Json)
        if ($databaseUsers.name -contains $activeOperator) {
            throw 'The named operator already has a database account; automatic cleanup cannot be proven.'
        }
        $migrationUser = @($databaseUsers | Where-Object {
            $_.name -eq $MigrationRole -and $_.type -eq 'CLOUD_IAM_SERVICE_ACCOUNT'
        })
        $runtimeUser = @($databaseUsers | Where-Object {
            $_.name -eq $RuntimeRole -and $_.type -eq 'CLOUD_IAM_SERVICE_ACCOUNT'
        })
        if ($migrationUser.Count -ne 1 -or $runtimeUser.Count -ne 1) {
            throw 'The approved migration or application database account is missing.'
        }

        $backupsRaw = Invoke-GcloudQuiet -Arguments @(
            'sql', 'backups', 'list', "--instance=$InstanceName",
            "--project=$ProjectId", '--limit=20', '--format=json'
        )
        $backups = @(($backupsRaw -join "`n") | ConvertFrom-Json)
        $freshBackup = $backups |
            Where-Object {
                $_.status -eq 'SUCCESSFUL' -and $_.type -eq 'ON_DEMAND' -and
                $_.description -eq $BackupDescription
            } |
            Sort-Object { [datetime]$_.endTime } -Descending |
            Select-Object -First 1
        if ($null -eq $freshBackup -or
            [datetime]$freshBackup.endTime -lt [datetime]::UtcNow.AddHours(-$MaximumBackupAgeHours)) {
            throw 'A recent successful on-demand safety backup is required before bootstrap.'
        }

        Write-Output 'Safety plan passed: protected state, private PostgreSQL 16, approved accounts and fresh backup.'
        Write-Output 'No database change has been made by the plan check.'
        if ($Action -eq 'Plan') { return }

        if ($ConfirmBootstrap -cne $expectedApplyConfirmation) {
            throw "Apply requires -ConfirmBootstrap $expectedApplyConfirmation."
        }
        if ($ExpectedRevision -notmatch '^[0-9a-f]{40}$') {
            throw 'Apply requires the exact approved 40-character Git revision.'
        }
        $originUrl = (& git -C $repositoryRoot remote get-url origin).Trim().Replace('\', '/')
        $approvedRemotePattern = '^(?i:(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)' +
            [regex]::Escape($repositorySlug) + '(?:\.git)?)$'
        if ($LASTEXITCODE -ne 0 -or $originUrl -notmatch $approvedRemotePattern) {
            throw 'Git origin does not exactly match the repository recorded in protected Terraform state.'
        }
        & git -C $repositoryRoot fetch --quiet origin main
        if ($LASTEXITCODE -ne 0) { throw 'The protected origin/main revision could not be refreshed.' }
        $branch = (& git -C $repositoryRoot branch --show-current).Trim()
        $headRevision = (& git -C $repositoryRoot rev-parse HEAD).Trim()
        $originRevision = (& git -C $repositoryRoot rev-parse origin/main).Trim()
        if ($LASTEXITCODE -ne 0 -or $branch -ne 'main' -or
            $headRevision -ne $ExpectedRevision -or $originRevision -ne $ExpectedRevision) {
            throw 'Live bootstrap requires the exact reviewed commit on protected origin/main.'
        }
        $repositoryChanges = @(& git -C $repositoryRoot status --porcelain --untracked-files=all)
        if ($LASTEXITCODE -ne 0 -or $repositoryChanges.Count -ne 0) {
            throw 'Live bootstrap requires a clean reviewed repository.'
        }
        & git -C $repositoryRoot ls-files --error-unmatch -- 'database/bootstrap/V0001__establish_schema_ownership.sql.template' 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'The bootstrap template must be committed before live use.' }

        New-Item -ItemType Directory -Path $temporaryDirectory -Force | Out-Null
        $temporarySqlPath = Join-Path $temporaryDirectory ("ee003-bootstrap-{0}.sql" -f [guid]::NewGuid())
        $marker = [ordered]@{
            projectId        = $ProjectId
            instanceName     = $InstanceName
            databaseName     = $DatabaseName
            operator         = $activeOperator
            expectedRevision = $ExpectedRevision
            renderedSqlPath  = $temporarySqlPath
            createdAtUtc     = [datetime]::UtcNow.ToString('o')
        }
        $markerBytes = [Text.UTF8Encoding]::new($false).GetBytes(($marker | ConvertTo-Json))
        $markerStream = [IO.File]::Open(
            $recoveryMarkerPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
        )
        try {
            $markerStream.Write($markerBytes, 0, $markerBytes.Length)
            $markerStream.Flush($true)
        }
        finally { $markerStream.Dispose() }
        $recoveryMarkerCreatedThisRun = $true
        $temporaryOperator = $activeOperator

        $template = Get-Content -LiteralPath $templatePath -Raw
        $replacements = [ordered]@{
            '__ADVISORY_LOCK_LITERAL__'         = Quote-PostgresLiteralContent "elder-engagement:${DatabaseName}:${ApplicationSchema}"
            '__DATABASE_LITERAL__'              = Quote-PostgresLiteralContent $DatabaseName
            '__APPLICATION_SCHEMA_LITERAL__'    = Quote-PostgresLiteralContent $ApplicationSchema
            '__MIGRATION_SCHEMA_LITERAL__'      = Quote-PostgresLiteralContent $MigrationSchema
            '__MIGRATION_ROLE_LITERAL__'        = Quote-PostgresLiteralContent $MigrationRole
            '__RUNTIME_ROLE_LITERAL__'          = Quote-PostgresLiteralContent $RuntimeRole
            '__OPERATOR_LITERAL__'              = Quote-PostgresLiteralContent $activeOperator
            '__APPLICATION_SCHEMA_IDENTIFIER__' = Quote-PostgresIdentifier $ApplicationSchema
            '__MIGRATION_SCHEMA_IDENTIFIER__'   = Quote-PostgresIdentifier $MigrationSchema
            '__MIGRATION_ROLE_IDENTIFIER__'     = Quote-PostgresIdentifier $MigrationRole
            '__RUNTIME_ROLE_IDENTIFIER__'       = Quote-PostgresIdentifier $RuntimeRole
            '__OPERATOR_IDENTIFIER__'           = Quote-PostgresIdentifier $activeOperator
        }
        foreach ($entry in $replacements.GetEnumerator()) {
            $template = $template.Replace($entry.Key, $entry.Value)
        }
        if ($template -match '__[A-Z0-9_]+__') {
            throw 'The bootstrap template contains an unresolved placeholder.'
        }
        Set-Content -LiteralPath $temporarySqlPath -Value $template -Encoding utf8NoBOM

        $temporaryDatabaseUserMayExist = $true
        $dataApiMayBeEnabled = $true
        $cloudMutationAttempted = $true
        Invoke-GcloudQuiet -Arguments @(
            'sql', 'users', 'create', $activeOperator,
            "--instance=$InstanceName", "--project=$ProjectId",
            '--type=CLOUD_IAM_USER', "--database-roles=cloudsqlsuperuser,$MigrationRole",
            '--quiet', '--format=none'
        ) | Out-Null

        Invoke-GcloudQuiet -Arguments @(
            'sql', 'instances', 'patch', $InstanceName,
            "--project=$ProjectId", '--data-api-access=ALLOW_DATA_API',
            '--quiet', '--format=none'
        ) | Out-Null

        $sqlArgument = '--sql=@' + $temporarySqlPath
        $executeRaw = Invoke-GcloudQuiet -Arguments @(
            'sql', 'instances', 'execute-sql', $InstanceName,
            "--project=$ProjectId", "--database=$DatabaseName",
            $sqlArgument, '--partial-result-mode=FAIL_PARTIAL_RESULT', '--format=json'
        )
        try { $executeResponse = ($executeRaw -join "`n") | ConvertFrom-Json }
        catch { throw 'Google Cloud returned an unreadable database execution result.' }
        Assert-ExecuteSqlResponse -Response $executeResponse
        $bootstrapCommitted = $true
    }
}
finally {
    if ($dataApiMayBeEnabled) {
        $dataApiClosureAttempted = $true
        try {
            Invoke-GcloudQuiet -Arguments @(
                'sql', 'instances', 'patch', $InstanceName,
                "--project=$ProjectId", '--data-api-access=DISALLOW_DATA_API',
                '--quiet', '--format=none'
            ) | Out-Null
        }
        catch { $cleanupErrors.Add('Temporary Data API access could not be disabled.') }
    }
    if ($temporaryDatabaseUserMayExist) {
        $operatorClosureAttempted = $true
        try {
            $cleanupUsersRaw = Invoke-GcloudQuiet -Arguments @(
                'sql', 'users', 'list', "--instance=$InstanceName",
                "--project=$ProjectId", '--format=json'
            )
            $cleanupUsers = @(($cleanupUsersRaw -join "`n") | ConvertFrom-Json)
            if ($cleanupUsers.name -contains $temporaryOperator) {
                Invoke-GcloudQuiet -Arguments @(
                    'sql', 'users', 'delete', $temporaryOperator,
                    "--instance=$InstanceName", "--project=$ProjectId", '--quiet'
                ) | Out-Null
            }
        }
        catch { $cleanupErrors.Add('The temporary database operator could not be removed.') }
    }
    if ($Action -in @('Apply', 'Cleanup') -and
        -not [string]::IsNullOrWhiteSpace([string]$temporaryOperator)) {
        try {
            $finalInstanceRaw = Invoke-GcloudQuiet -Arguments @(
                'sql', 'instances', 'describe', $InstanceName,
                "--project=$ProjectId", '--format=json'
            )
            $finalInstance = ($finalInstanceRaw -join "`n") | ConvertFrom-Json
            if ($finalInstance.settings.dataApiAccess -eq 'ALLOW_DATA_API' -or
                [bool]$finalInstance.settings.ipConfiguration.ipv4Enabled) {
                $cleanupErrors.Add('The temporary database access path is still open.')
            }
            $finalUsersRaw = Invoke-GcloudQuiet -Arguments @(
                'sql', 'users', 'list', "--instance=$InstanceName",
                "--project=$ProjectId", '--format=json'
            )
            $finalUsers = @(($finalUsersRaw -join "`n") | ConvertFrom-Json)
            if ($finalUsers.name -contains $temporaryOperator) {
                $cleanupErrors.Add('The temporary database operator still exists.')
            }
            if ($cleanupErrors.Count -eq 0) { $finalCleanupVerified = $true }
        }
        catch { $cleanupErrors.Add('Final temporary-access verification could not be completed.') }
    }
    if ($temporarySqlPath -and (Test-Path -LiteralPath $temporarySqlPath)) {
        try { Remove-Item -LiteralPath $temporarySqlPath -Force }
        catch { $cleanupErrors.Add('The protected temporary SQL file could not be removed.') }
    }
    $removeRecoveryMarker = (
        $recoveryMarkerCreatedThisRun -and -not $cloudMutationAttempted
    ) -or (
        $dataApiClosureAttempted -and $operatorClosureAttempted -and
        $finalCleanupVerified -and $cleanupErrors.Count -eq 0
    )
    if ($removeRecoveryMarker -and (Test-Path -LiteralPath $recoveryMarkerPath)) {
        try { Remove-Item -LiteralPath $recoveryMarkerPath -Force }
        catch { $cleanupErrors.Add('The protected recovery marker could not be removed.') }
    }
    if ($null -eq $previousAccessToken) {
        Remove-Item Env:GOOGLE_OAUTH_ACCESS_TOKEN -ErrorAction SilentlyContinue
    }
    else { $env:GOOGLE_OAUTH_ACCESS_TOKEN = $previousAccessToken }
    if ($null -eq $previousCloudSdkConfig) {
        Remove-Item Env:CLOUDSDK_CONFIG -ErrorAction SilentlyContinue
    }
    else { $env:CLOUDSDK_CONFIG = $previousCloudSdkConfig }
    if ($null -ne $bootstrapLockHandle) { $bootstrapLockHandle.Dispose() }
}

if ($cleanupErrors.Count -ne 0) { throw ($cleanupErrors -join ' ') }
if ($Action -eq 'Cleanup') {
    Write-Output 'Emergency cleanup completed: temporary database access is closed and removed.'
    return
}
if (-not $bootstrapCommitted) { throw 'The database bootstrap did not complete.' }

Write-Output 'Bootstrap completed safely: both approved empty schemas were created with limited ownership.'
Write-Output 'The temporary operator access was removed and the temporary Data API path was closed.'
