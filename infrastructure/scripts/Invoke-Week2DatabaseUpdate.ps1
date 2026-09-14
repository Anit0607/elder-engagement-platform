#requires -Version 7.0

[CmdletBinding()]
param(
    [ValidateSet('Plan', 'Start', 'Verify')]
    [string]$Action = 'Plan',
    [Parameter(Mandatory)] [string]$BackendConfig,
    [Parameter(Mandatory)] [string]$ReviewedPlan,
    [Parameter(Mandatory)] [ValidatePattern('^[0-9a-f]{64}$')] [string]$ExpectedPlanSha256,
    [Parameter(Mandatory)] [ValidatePattern('^[0-9a-f]{40}$')] [string]$ExpectedRevision,
    [ValidatePattern('^[0-9a-f]{40}$')] [string]$ExpectedMigrationRevision,
    [Parameter(Mandatory)] [string]$ExpectedImage,
    [string]$ConfirmUpdate
)

# A single development update from V0001 to V0004. This does not update the job,
# create passwords, grant roles, enable a public database or automatically retry.
$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$foundationDirectory = Join-Path $repositoryRoot 'infrastructure\terraform\foundation'
$secureRuntime = Join-Path $repositoryRoot 'secure-runtime'
$controlDirectory = Join-Path $secureRuntime 'migration-execution'
$markerPath = Join-Path $controlDirectory 'week2-v0004.json'
$lockPath = Join-Path $controlDirectory 'ee003-development.lock'
$jobAddress = 'google_cloud_run_v2_job.database_migration[0]'
$baselineRevision = '632b248fb2a9d91cd0e34ec9673a17c2a577e438'
$baselineDigest = '22a90388f73d6d9f6f946b4b42e8366edb8aa8e0075e51c6adf2c4e3d3d70b37'
$pendingIds = @('V0002', 'V0003', 'V0004')
$migrationRevision = if ($ExpectedMigrationRevision) { $ExpectedMigrationRevision } else { $ExpectedRevision }

# Import reviewed pure helpers only; never execute the original one-time runner.
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot 'Invoke-DatabaseMigration.ps1'), [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) { throw 'The baseline helper source does not parse.' }
foreach ($name in @(
    'Resolve-IgnoredInputFile', 'Resolve-GcloudCommand', 'Resolve-TerraformCommand',
    'Invoke-GcloudJson', 'Invoke-TerraformJson', 'Read-StateOutput',
    'Get-EnvironmentMap', 'Get-PlanEnvironmentMap', 'Assert-ExactEnvironmentMap',
    'Assert-ExactPropertyNames', 'Assert-LiveJobMatchesPlan',
    'Get-ExecutionLogFilter', 'Test-ExecutionLogEntry', 'Get-ActiveHumanOperator',
    'Write-RecoveryMarker'
)) {
    $definition = @($ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true))
    if ($definition.Count -ne 1) { throw "Expected one reviewed $name helper." }
    . ([scriptblock]::Create($definition[0].Extent.Text))
}

function Assert-UpdatePlan {
    param([object]$Plan, [string]$Image, [string]$Revision, [string]$PreviousImage, [string]$PreviousRevision)
    $changes = @($Plan.resource_changes | Where-Object { (@($_.change.actions) -join ',') -ne 'no-op' })
    $outputs = @($Plan.output_changes.PSObject.Properties | Where-Object {
        (@($_.Value.actions) -join ',') -ne 'no-op'
    })
    if ($changes.Count -ne 1 -or $changes[0].address -cne $script:jobAddress -or
        (@($changes[0].change.actions) -join ',') -cne 'update' -or $outputs.Count -ne 0) {
        throw 'Only an in-place update to the dormant migration job is allowed.'
    }
    $before = $changes[0].change.before
    $after = $changes[0].change.after
    $beforeContainer = $before.template[0].template[0].containers[0]
    $afterContainer = $after.template[0].template[0].containers[0]
    $beforeEnvironment = Get-PlanEnvironmentMap -Entries $beforeContainer.env
    $afterEnvironment = Get-PlanEnvironmentMap -Entries $afterContainer.env
    if ($beforeContainer.image -cne $PreviousImage -or $afterContainer.image -cne $Image -or
        $beforeEnvironment.SOURCE_REVISION -cne $PreviousRevision -or
        $afterEnvironment.SOURCE_REVISION -cne $Revision) {
        throw 'The plan does not match the reviewed old and new image/source pins.'
    }
    $comparison = $before.template | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100
    $comparison[0].template[0].containers[0].image = $Image
    $sourceEntry = @($comparison[0].template[0].containers[0].env | Where-Object { $_.name -ceq 'SOURCE_REVISION' })
    if ($sourceEntry.Count -ne 1) { throw 'The old template has no unique source revision.' }
    $sourceEntry[0].value = $Revision
    if (($comparison | ConvertTo-Json -Depth 100 -Compress) -cne
        ($after.template | ConvertTo-Json -Depth 100 -Compress)) {
        throw 'A task option other than image/source changed in the saved plan.'
    }
    return $after
}

function Assert-BackupRecord {
    param([object[]]$Records, [datetimeoffset]$Now)
    $valid = @($Records | Where-Object {
        if ($_.status -cne 'SUCCESSFUL' -or $_.type -cne 'ON_DEMAND' -or
            $_.description -cne 'Pre-Week-2 staff and English profile update' -or -not $_.endTime) { return $false }
        $ended = [datetimeoffset]::MinValue
        if ($_.endTime -is [datetimeoffset]) { $ended = $_.endTime }
        elseif ($_.endTime -is [datetime]) {
            # Invoke-RestMethod may parse ISO timestamps into DateTime. Casting
            # to string drops the UTC kind and wrongly assumes local time.
            if ($_.endTime.Kind -eq [DateTimeKind]::Unspecified) { return $false }
            $ended = [datetimeoffset]$_.endTime
        }
        elseif ($_.endTime -is [string]) {
            if ($_.endTime -notmatch '(?:Z|[+-][0-9]{2}:[0-9]{2})$' -or
                -not [datetimeoffset]::TryParse($_.endTime,
                    [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$ended)) {
                return $false
            }
        }
        else { return $false }
        $age = ($Now - $ended).TotalHours
        return $age -ge 0 -and $age -le 4
    } | Sort-Object endTime -Descending)
    if ($valid.Count -eq 0) { throw 'A successful on-demand backup from the last four hours is required.' }
    return $valid[0]
}

function Convert-EmptyJobDefaults {
    param([object]$Job)
    # Terraform's refreshed update plan represents absent options with empty
    # strings/maps/lists or false. Preserve any real override so the strict
    # baseline helper still rejects it. Never alter the saved plan or live job.
    $copy = $Job | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100
    foreach ($execution in @($copy.template)) {
        foreach ($field in @('annotations', 'labels')) {
            if ($null -ne $execution.$field -and @($execution.$field.PSObject.Properties).Count -eq 0) {
                $execution.$field = $null
            }
        }
        foreach ($task in @($execution.template)) {
            if ($task.encryption_key -ceq '') { $task.encryption_key = $null }
            if ($task.gpu_zonal_redundancy_disabled -eq $false) { $task.gpu_zonal_redundancy_disabled = $null }
            foreach ($container in @($task.containers)) {
                foreach ($field in @('working_dir', 'name')) {
                    if ($container.$field -ceq '') { $container.$field = $null }
                }
                if ($null -ne $container.depends_on -and @($container.depends_on).Count -eq 0) {
                    $container.depends_on = $null
                }
            }
        }
    }
    return $copy
}

function Invoke-SqlRead {
    param([string]$Suffix)
    # The approved private SQL instance only; credentials stay in process memory.
    $uri = "https://sqladmin.googleapis.com/sql/v1beta4/projects/$script:projectId/instances/$script:databaseInstance$Suffix"
    try { return Invoke-RestMethod -Uri $uri -Headers @{ Authorization = "Bearer $script:accessToken" } -TimeoutSec 30 }
    catch { throw 'The approved Cloud SQL resource could not be read. No update was started.' }
}

function Read-UpdateHistory {
    $history = @(Invoke-GcloudJson -Arguments @(
        'run', 'jobs', 'executions', 'list', "--job=$script:jobName",
        "--project=$script:projectId", "--region=$script:region", '--format=json', '--quiet'
    ) -FailureMessage 'The database-update execution history could not be read.')
    return ,$history
}

function Assert-SuccessRecord {
    param([object[]]$Logs, [string]$Execution)
    $matches = @()
    foreach ($entry in $Logs) {
        if (-not (Test-ExecutionLogEntry -Entry $entry -ExecutionName $Execution)) { continue }
        $record = $null
        if ($entry.jsonPayload.status) { $record = $entry.jsonPayload }
        else {
            $candidate = if ($entry.textPayload) { $entry.textPayload } else { $entry.jsonPayload.message }
            if ($candidate) { try { $record = $candidate | ConvertFrom-Json } catch { } }
        }
        if ($record -and $record.status -ceq 'ok' -and (@($record.applied) -join ',') -ceq 'V0002,V0003,V0004') {
            $matches += $record
        }
    }
    if ($matches.Count -ne 1) { throw 'The exact V0002-V0004 completion record is not yet proven. Do not restart.' }
}

$resolvedBackend = Resolve-IgnoredInputFile -Path $BackendConfig -Label 'BackendConfig'
$resolvedPlan = Resolve-IgnoredInputFile -Path $ReviewedPlan -Label 'ReviewedPlan'
if ((Get-FileHash -LiteralPath $resolvedPlan -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedPlanSha256) {
    throw 'The saved plan checksum changed.'
}
$oldConfig = $env:CLOUDSDK_CONFIG
$oldToken = $env:GOOGLE_OAUTH_ACCESS_TOKEN
$env:CLOUDSDK_CONFIG = Join-Path $secureRuntime 'gcloud-config'
$lockHandle = $null
try {
    New-Item -ItemType Directory -Path $controlDirectory -Force | Out-Null
    try { $lockHandle = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw 'Another controlled database update is running.' }
    $gcloud = Resolve-GcloudCommand
    $terraform = Resolve-TerraformCommand
    $null = Get-ActiveHumanOperator
    $accessToken = [string](& $gcloud auth print-access-token --quiet 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($accessToken)) { throw 'Google Cloud sign-in is required.' }
    $accessToken = $accessToken.Trim()
    $env:GOOGLE_OAUTH_ACCESS_TOKEN = $accessToken
    $tfDirectory = "-chdir=$foundationDirectory"
    & $terraform $tfDirectory init -input=false "-backend-config=$resolvedBackend" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'The private infrastructure state could not be initialized.' }
    $state = Invoke-TerraformJson -Arguments @($tfDirectory, 'output', '-json') -FailureMessage 'Private state could not be read.'
    $projectId = Read-StateOutput $state 'deployment_project_id'
    $region = Read-StateOutput $state 'deployment_region'
    $environment = Read-StateOutput $state 'deployment_environment'
    $databaseInstance = Read-StateOutput $state 'database_instance_name'
    $jobName = ((Read-StateOutput $state 'database_migration_job') -split '/')[-1]
    $artifactRepository = Read-StateOutput $state 'artifact_repository'
    if ($environment -cne 'development' -or $projectId -notmatch '^[a-z][a-z0-9-]{4,28}[a-z0-9]$' -or
        $region -notmatch '^[a-z]+-[a-z]+[0-9]$' -or $databaseInstance -cne 'ee-development-postgres' -or
        $jobName -cne 'ee-development-database-migration' -or $artifactRepository -cne 'ee-development-containers') {
        throw 'The private state does not identify the approved development resources.'
    }
    $prefix = "$region-docker.pkg.dev/$projectId/$artifactRepository/engagement-migration@sha256:"
    if ($ExpectedImage -cnotmatch ('^' + [regex]::Escape($prefix) + '[0-9a-f]{64}$') -or
        $ExpectedImage -ceq "$prefix$baselineDigest") { throw 'An approved new immutable migration image is required.' }
    $repositorySlug = Read-StateOutput $state 'github_repository_slug'
    if ($repositorySlug -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'The state has an invalid repository target.' }
    $origin = [string](& git -C $repositoryRoot remote get-url origin)
    if ($LASTEXITCODE -ne 0 -or $origin.Trim() -notmatch ('^https://github\.com/' + [regex]::Escape($repositorySlug) + '(?:\.git)?$')) {
        throw 'The repository origin differs from the approved state.'
    }
    & git -C $repositoryRoot fetch --quiet origin main
    if ($LASTEXITCODE -ne 0) { throw 'The reviewed main revision could not be refreshed.' }
    $branch = [string](& git -C $repositoryRoot branch --show-current)
    $head = [string](& git -C $repositoryRoot rev-parse HEAD)
    $remoteHead = [string](& git -C $repositoryRoot rev-parse origin/main)
    if ($branch.Trim() -cne 'main' -or $head.Trim() -cne $ExpectedRevision -or $remoteHead.Trim() -cne $ExpectedRevision -or
        @(& git -C $repositoryRoot status --porcelain --untracked-files=all).Count -ne 0) {
        throw 'Use only the clean, reviewed and tested origin/main revision.'
    }
    & git -C $repositoryRoot merge-base --is-ancestor $migrationRevision HEAD
    if ($LASTEXITCODE -ne 0) { throw 'The image source is not a reviewed ancestor of current main.' }
    & git -C $repositoryRoot diff --quiet $migrationRevision HEAD -- database
    if ($LASTEXITCODE -ne 0) { throw 'Database source changed after the image was built. Rebuild before execution.' }
    $manifest = Get-Content (Join-Path $repositoryRoot 'database\migrations\manifest.json') -Raw | ConvertFrom-Json
    if ((@($manifest.migrations.id) -join ',') -cne 'V0001,V0002,V0003,V0004') { throw 'This runner is only for the agreed Week 2 migration batch.' }
    $plan = Invoke-TerraformJson -Arguments @($tfDirectory, 'show', '-json', $resolvedPlan) -FailureMessage 'The saved plan could not be read.'
    $expectedJob = Assert-UpdatePlan -Plan $plan -Image $ExpectedImage -Revision $migrationRevision `
        -PreviousImage "$prefix$baselineDigest" -PreviousRevision $baselineRevision
    $expectedJob = Convert-EmptyJobDefaults -Job $expectedJob
    $migrationUser = Read-StateOutput $state 'database_migration_iam_user'
    $runtimeUser = Read-StateOutput $state 'database_runtime_iam_user'
    $expectedEnvironment = @{
        MIGRATION_MODE = 'production'; INSTANCE_CONNECTION_NAME = "$projectId`:$region`:$databaseInstance"
        DB_NAME = 'engagement'; DB_MIGRATION_IAM_USER = $migrationUser; DB_RUNTIME_IAM_USER = $runtimeUser
        APP_SCHEMA = 'engagement_app'; MIGRATION_SCHEMA = 'engagement_migrations'; SOURCE_REVISION = $migrationRevision
    }
    if ($migrationUser -cne "ee-development-migration@$projectId.iam" -or
        $runtimeUser -cne "ee-development-runtime@$projectId.iam" -or
        (Read-StateOutput $state 'database_name') -cne 'engagement' -or
        (Read-StateOutput $state 'serverless_network_name') -cne 'ee-development-network' -or
        (Read-StateOutput $state 'serverless_subnetwork_name') -cne 'ee-development-serverless') {
        throw 'The database identities or network differ from the approved resources.'
    }
    Assert-LiveJobMatchesPlan -ExpectedJob $expectedJob -ExpectedEnvironment $expectedEnvironment `
        -ExpectedServiceAccount "$migrationUser.gserviceaccount.com" -ExpectedImage $ExpectedImage `
        -ExpectedNetwork (Read-StateOutput $state 'serverless_network_name') `
        -ExpectedSubnetwork (Read-StateOutput $state 'serverless_subnetwork_name')
    $instance = Invoke-SqlRead ''
    if ($instance.state -cne 'RUNNABLE' -or $instance.databaseVersion -cne 'POSTGRES_16' -or
        $instance.settings.ipConfiguration.ipv4Enabled -ne $false -or
        -not $instance.settings.ipConfiguration.privateNetwork -or
        @($instance.settings.ipConfiguration.authorizedNetworks | Where-Object { $null -ne $_ }).Count -ne 0 -or
        $instance.settings.ipConfiguration.sslMode -cne 'ENCRYPTED_ONLY' -or
        $instance.settings.backupConfiguration.enabled -ne $true -or
        $instance.settings.backupConfiguration.pointInTimeRecoveryEnabled -ne $true) {
        throw 'The private database or its backup settings differ from the agreed protections.'
    }
    $policy = Invoke-GcloudJson -Arguments @('run', 'jobs', 'get-iam-policy', $jobName,
        "--project=$projectId", "--region=$region", '--format=json', '--quiet') -FailureMessage 'Job permissions could not be read.'
    if (@($policy.bindings.members | Where-Object { $_ -in @('allUsers', 'allAuthenticatedUsers') }).Count -ne 0) {
        throw 'The database job must not have public permissions.'
    }
    $history = Read-UpdateHistory
    if ($Action -eq 'Verify') {
        if (-not (Test-Path $markerPath -PathType Leaf)) { throw 'No update-start record exists.' }
        $marker = Get-Content $markerPath -Raw | ConvertFrom-Json
        if ($marker.projectId -cne $projectId -or $marker.region -cne $region -or $marker.jobName -cne $jobName -or
            $marker.revision -cne $ExpectedRevision -or $marker.image -cne $ExpectedImage -or
            $marker.migrationRevision -cne $migrationRevision -or
            $marker.planSha256 -cne $ExpectedPlanSha256) { throw 'The update-start record identifies a different release.' }
        $new = @($history | Where-Object { $_.metadata.name -cne $marker.previousExecution })
        if ($history.Count -ne 2 -or $new.Count -ne 1) { throw 'The one additional execution cannot be isolated. Do not restart.' }
        $executionName = [string]$new[0].metadata.name
        $execution = Invoke-GcloudJson -Arguments @('run', 'jobs', 'executions', 'describe', $executionName,
            "--project=$projectId", "--region=$region", '--format=json', '--quiet') -FailureMessage 'The started execution could not be read. Do not restart.'
        Assert-ExactEnvironmentMap -Expected $expectedEnvironment `
            -Actual (Get-EnvironmentMap -Entries $execution.spec.template.spec.containers[0].env)
        if ($execution.spec.taskCount -ne 1 -or $execution.spec.parallelism -ne 1 -or
            $execution.spec.template.spec.maxRetries -ne 0 -or
            $execution.spec.template.spec.serviceAccountName -cne "$migrationUser.gserviceaccount.com" -or
            $execution.spec.template.spec.timeoutSeconds -ne 900 -or
            @($execution.spec.template.spec.containers).Count -ne 1) {
            throw 'The recorded execution differs from the approved task. Do not restart.'
        }
        $completed = @($execution.status.conditions | Where-Object { $_.type -ceq 'Completed' -and $_.status -ceq 'True' })
        if ($completed.Count -ne 1 -or [int]$execution.status.succeededCount -ne 1 -or [int]$execution.status.failedCount -ne 0) {
            throw 'Successful completion is not yet proven. Verify again; never restart the update.'
        }
        $filter = (Get-ExecutionLogFilter -JobName $jobName) +
            ' AND labels."run.googleapis.com/execution_name"="' + $executionName + '"'
        $logs = @(Invoke-GcloudJson -Arguments @('logging', 'read', $filter,
            "--project=$projectId", '--limit=100', '--format=json', '--quiet') -FailureMessage 'Completion logs could not be read. Do not restart.')
        Assert-SuccessRecord -Logs $logs -Execution $executionName
        Write-Output 'Verified: V0002, V0003 and V0004 completed in one recorded execution, including database postchecks.'
        return
    }
    if (Test-Path $markerPath) { throw 'A previous start attempt is recorded. Use Verify, never Start again.' }
    $completed = @($history[0].status.conditions | Where-Object { $_.type -ceq 'Completed' -and $_.status -ceq 'True' })
    if ($history.Count -ne 1 -or $completed.Count -ne 1 -or [int]$history[0].status.succeededCount -ne 1) {
        throw 'The expected single successful baseline execution is not proven.'
    }
    $baseline = Invoke-GcloudJson -Arguments @('run', 'jobs', 'executions', 'describe', $history[0].metadata.name,
        "--project=$projectId", "--region=$region", '--format=json', '--quiet') -FailureMessage 'The prior baseline execution could not be verified.'
    $baselineEnvironment = Get-EnvironmentMap -Entries $baseline.spec.template.spec.containers[0].env
    if ($baselineEnvironment.SOURCE_REVISION -cne $baselineRevision -or $baselineEnvironment.DB_NAME -cne 'engagement') {
        throw 'The previous execution is not the approved baseline update.'
    }
    if ($Action -eq 'Plan') {
        Write-Output 'Validated: dormant job image/source update only; private database; V0002-V0004 next. No execution started.'
        return
    }
    if ($ConfirmUpdate -cne 'UPDATE-WEEK2-DEVELOPMENT-V0004') { throw 'Start requires the exact Week 2 development confirmation.' }
    $backups = Invoke-SqlRead '/backupRuns'
    $backup = Assert-BackupRecord -Records @($backups.items) -Now ([datetimeoffset]::UtcNow)
    $recheckedHistory = Read-UpdateHistory
    if ($recheckedHistory.Count -ne 1 -or $recheckedHistory[0].metadata.name -cne $history[0].metadata.name) {
        throw 'Execution history changed during preparation. No update requested.'
    }
    Assert-LiveJobMatchesPlan -ExpectedJob $expectedJob -ExpectedEnvironment $expectedEnvironment `
        -ExpectedServiceAccount "$migrationUser.gserviceaccount.com" -ExpectedImage $ExpectedImage `
        -ExpectedNetwork (Read-StateOutput $state 'serverless_network_name') `
        -ExpectedSubnetwork (Read-StateOutput $state 'serverless_subnetwork_name')
    Write-RecoveryMarker -Marker @{
        projectId = $projectId; region = $region; jobName = $jobName
        revision = $ExpectedRevision; migrationRevision = $migrationRevision
        image = $ExpectedImage; planSha256 = $ExpectedPlanSha256
        previousExecution = [string]$history[0].metadata.name; backupId = [string]$backup.id
        createdAtUtc = [datetimeoffset]::UtcNow.ToString('o')
    }
    # Keep this durable marker on ALL outcomes, including a lost acknowledgement.
    # The existing named operator's project permission is used; no role is granted.
    $null = Invoke-GcloudJson -Arguments @('run', 'jobs', 'execute', $jobName,
        "--project=$projectId", "--region=$region", '--format=json', '--quiet') `
        -FailureMessage 'Start acknowledgement is uncertain. Use Verify; do not start again.'
    Write-Output 'One update was requested. Use Verify to confirm completion; never request Start again.'
}
finally {
    $accessToken = $null
    $env:CLOUDSDK_CONFIG = $oldConfig
    $env:GOOGLE_OAUTH_ACCESS_TOKEN = $oldToken
    if ($lockHandle) { $lockHandle.Dispose() }
}
