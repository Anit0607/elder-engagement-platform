#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidateSet('Start', 'Verify')] [string]$Action,
    [Parameter(Mandatory)] [ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]$')] [string]$Project,
    [Parameter(Mandatory)] [ValidatePattern('^[a-z]+-[a-z]+[0-9]$')] [string]$Region,
    [Parameter(Mandatory)] [ValidatePattern('^[0-9a-f]{40}$')] [string]$ExpectedRevision,
    [Parameter(Mandatory)] [ValidatePattern('^[0-9a-f]{40}$')] [string]$ImageSourceRevision,
    [Parameter(Mandatory)] [string]$ExpectedImage,
    [Parameter(Mandatory)] [string]$ReviewedPlan,
    [Parameter(Mandatory)] [ValidatePattern('^[0-9a-f]{64}$')] [string]$ExpectedPlanSha256,
    [Parameter(Mandatory)] [ValidatePattern('^[0-9]+$')] [string]$BackupId,
    [string]$Confirmation
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$jobName = 'ee-development-fictional-staff-setup'
$instanceName = 'ee-development-postgres'
$jobResource = "projects/$Project/locations/$Region/jobs/$jobName"
$controlDirectory = Join-Path $root 'secure-runtime\staff-setup-execution'
$markerPath = Join-Path $controlDirectory 'fictional-staff-setup.json'
$oldConfig = $env:CLOUDSDK_CONFIG
$env:CLOUDSDK_CONFIG = Join-Path $root 'secure-runtime\gcloud-config'

function Invoke-SetupCloud {
    param([string]$Method, [string]$Uri, $Body)
    $arguments = @{ Method = $Method; Uri = $Uri; TimeoutSec = 30; MaximumRedirection = 0
        Headers = @{ Authorization = "Bearer $script:accessToken"; 'x-goog-user-project' = $script:Project } }
    if ($null -ne $Body) { $arguments.Body = $Body | ConvertTo-Json -Depth 100 -Compress; $arguments.ContentType = 'application/json' }
    try { return Invoke-RestMethod @arguments }
    catch { throw 'Google Cloud request did not complete. Private details suppressed; never restart an uncertain setup.' }
}

function Assert-SetupPlan {
    param($Plan, [string]$Image, [string]$Revision)
    $changes = @($Plan.resource_changes | Where-Object { (@($_.change.actions) -join ',') -cne 'no-op' })
    $outputs = @($Plan.output_changes.PSObject.Properties | Where-Object { (@($_.Value.actions) -join ',') -cne 'no-op' })
    if ($changes.Count -ne 1 -or $changes[0].address -cne 'google_cloud_run_v2_job.fictional_staff_setup[0]' -or
        (@($changes[0].change.actions) -join ',') -cne 'create' -or $outputs.Count -ne 0) {
        throw 'Only the reviewed new fictional setup job may change in this plan.'
    }
    $job = $changes[0].change.after
    $container = $job.template[0].template[0].containers[0]
    $source = @($container.env | Where-Object name -CEQ 'SOURCE_REVISION')
    if ($container.image -cne $Image -or $source.Count -ne 1 -or $source[0].value -cne $Revision) {
        throw 'The saved job plan does not match the reviewed image/source.'
    }
    return $job
}

function Assert-SetupJob {
    param($Live, $Expected, [string]$ProjectId, [string]$Location, [string]$Image, [string]$Revision)
    $execution = $Live.template
    $task = $execution.template
    $container = $task.containers[0]
    if ($Live.name -cne "projects/$ProjectId/locations/$Location/jobs/ee-development-fictional-staff-setup" -or
        $execution.taskCount -ne 1 -or $execution.parallelism -ne 1 -or $task.maxRetries -ne 0 -or
        $task.timeout -cne '300s' -or $task.executionEnvironment -cne 'EXECUTION_ENVIRONMENT_GEN2' -or
        $task.serviceAccount -cne "ee-development-runtime@$ProjectId.iam.gserviceaccount.com" -or
        @($task.containers).Count -ne 1 -or $container.image -cne $Image -or
        (@($container.command) -join ',') -cne 'python' -or
        (@($container.args) -join ',') -cne '-m,app.development_staff_setup' -or
        $container.resources.limits.cpu -cne '1' -or $container.resources.limits.memory -cne '512Mi' -or
        @($task.volumes | Where-Object { $null -ne $_ }).Count -ne 0 -or
        @($container.volumeMounts | Where-Object { $null -ne $_ }).Count -ne 0 -or
        $task.vpcAccess.egress -cne 'PRIVATE_RANGES_ONLY' -or @($task.vpcAccess.networkInterfaces).Count -ne 1) {
        throw 'Live fictional job limits, identity, executable or private network differ from the reviewed setup.'
    }
    $network = $task.vpcAccess.networkInterfaces[0]
    if ($network.network -cne "projects/$ProjectId/global/networks/ee-development-network" -or
        $network.subnetwork -cne "projects/$ProjectId/regions/$Location/subnetworks/ee-development-serverless") {
        throw 'The setup job uses an unexpected private network.'
    }
    $wanted = @($Expected.template[0].template[0].containers[0].env)
    $actual = @($container.env)
    if ($actual.Count -ne $wanted.Count -or @($actual.name | Sort-Object -Unique).Count -ne $actual.Count) {
        throw 'The live setup environment differs from the saved plan.'
    }
    foreach ($entry in $wanted) {
        $match = @($actual | Where-Object name -CEQ $entry.name)
        if ($match.Count -ne 1) { throw 'A reviewed setup input is missing.' }
        $secret = @($entry.value_source | Where-Object { $null -ne $_ })
        if ($secret.Count -eq 0) {
            if ($match[0].value -cne $entry.value -or $match[0].valueSource) { throw 'A setup value changed.' }
        } else {
            $ref = $secret[0].secret_key_ref[0]
            $liveRef = $match[0].valueSource.secretKeyRef
            if (($liveRef.secret -split '/')[-1] -cne $ref.secret -or $liveRef.version -cne $ref.version -or
                $liveRef.version -cnotmatch '^[1-9][0-9]*$' -or $match[0].value) { throw 'A pinned secret reference changed.' }
        }
    }
}

function Read-SetupBackupTime {
    param($Value)
    if ($Value -is [DateTimeOffset]) { return $Value.ToUniversalTime() }
    if ($Value -is [DateTime]) {
        if ($Value.Kind -eq [DateTimeKind]::Unspecified) { throw 'Backup time has no timezone.' }
        return ([DateTimeOffset]$Value).ToUniversalTime()
    }
    if ([string]$Value -notmatch '(?:Z|[+-][0-9]{2}:[0-9]{2})$') { throw 'Backup time has no timezone.' }
    return ([DateTimeOffset]::Parse([string]$Value, [Globalization.CultureInfo]::InvariantCulture)).ToUniversalTime()
}

function Assert-SetupCompletion {
    param($Logs, [string]$Execution)
    $found = @()
    foreach ($entry in $Logs) {
        if ($entry.labels.'run.googleapis.com/execution_name' -cne $Execution) { continue }
        $record = $entry.jsonPayload
        if (-not $record.status -and $entry.textPayload) { try { $record = $entry.textPayload | ConvertFrom-Json } catch { continue } }
        if ($record.status -ceq 'ok' -and $record.fictional_only -eq $true -and
            $record.client_authenticator_acceptance -eq $false -and $record.public_route_enabled -eq $false -and
            (@($record.checks) -join ',') -ceq ('fictional_administrator_enrolled_and_two_factor_login_verified,' +
                'administrator_created_contributor_password_login_verified,contributor_cannot_create_staff,setup_test_sessions_signed_out')) {
            $found += $record
        }
    }
    if ($found.Count -ne 1) { throw 'The exact fictional setup completion record is not proven. Verify again; never restart.' }
}

try {
    if ($root -notmatch '^[Dd]:\\') { throw 'Project execution files must remain on the D drive.' }
    $resolvedPlan = (Resolve-Path -LiteralPath $ReviewedPlan).Path
    if (-not $resolvedPlan.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Use the private plan inside this workspace.' }
    & git -C $root check-ignore --quiet $resolvedPlan
    if ($LASTEXITCODE -ne 0) { throw 'The saved plan must be excluded from Git.' }
    if ((Get-FileHash -LiteralPath $resolvedPlan).Hash.ToLowerInvariant() -cne $ExpectedPlanSha256) { throw 'The saved plan checksum changed.' }
    & git -C $root fetch --quiet origin main
    if ($LASTEXITCODE -ne 0) { throw 'Cannot confirm reviewed main.' }
    if (([string](& git -C $root branch --show-current)).Trim() -cne 'main' -or
        ([string](& git -C $root rev-parse HEAD)).Trim() -cne $ExpectedRevision -or
        ([string](& git -C $root rev-parse origin/main)).Trim() -cne $ExpectedRevision -or
        @(& git -C $root status --porcelain).Count -ne 0) { throw 'Use clean reviewed origin/main only.' }
    & git -C $root merge-base --is-ancestor $ImageSourceRevision HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Image source is not reviewed main history.' }
    & git -C $root diff --quiet $ImageSourceRevision HEAD -- database services/engagement-api/app
    if ($LASTEXITCODE -ne 0) { throw 'App/database source changed since image publication.' }
    $prefix = "$Region-docker.pkg.dev/$Project/ee-development-containers/engagement-api@sha256:"
    if ($ExpectedImage -cnotmatch ('^' + [regex]::Escape($prefix) + '[0-9a-f]{64}$')) { throw 'Unexpected setup image target.' }
    $terraform = Join-Path $root 'tools-runtime\terraform-1.16.2\terraform.exe'
    $planJson = & $terraform "-chdir=$root\infrastructure\terraform\foundation" show -json $resolvedPlan 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Private setup plan cannot be read.' }
    $expectedJob = Assert-SetupPlan ($planJson | ConvertFrom-Json -Depth 100) $ExpectedImage $ImageSourceRevision
    if ($expectedJob.project -cne $Project -or $expectedJob.location -cne $Region -or $expectedJob.name -cne $jobName) { throw 'Saved setup plan targets another environment.' }
    $gcloud = Join-Path $root 'tools-runtime\google-cloud-sdk\bin\gcloud.cmd'
    $accessToken = ([string](& $gcloud auth print-access-token --quiet 2>$null)).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $accessToken) { throw 'Google Cloud sign-in required.' }
    $live = Invoke-SetupCloud GET "https://run.googleapis.com/v2/$jobResource"
    Assert-SetupJob $live $expectedJob $Project $Region $ExpectedImage $ImageSourceRevision
    $policy = Invoke-SetupCloud GET "https://run.googleapis.com/v2/${jobResource}:getIamPolicy"
    if (@($policy.bindings.members | Where-Object { $_ -in 'allUsers', 'allAuthenticatedUsers' }).Count -ne 0) { throw 'Setup job must not allow public access.' }
    $sql = Invoke-SetupCloud GET "https://sqladmin.googleapis.com/sql/v1beta4/projects/$Project/instances/$instanceName"
    if ($sql.state -cne 'RUNNABLE' -or $sql.databaseVersion -cne 'POSTGRES_16' -or
        $sql.settings.ipConfiguration.ipv4Enabled -ne $false -or -not $sql.settings.ipConfiguration.privateNetwork -or
        @($sql.settings.ipConfiguration.authorizedNetworks | Where-Object { $null -ne $_ }).Count -ne 0 -or
        $sql.settings.ipConfiguration.sslMode -cne 'ENCRYPTED_ONLY' -or
        $sql.settings.backupConfiguration.enabled -ne $true -or $sql.settings.backupConfiguration.pointInTimeRecoveryEnabled -ne $true) {
        throw 'The database must remain private, encrypted and backed up.'
    }
    $history = Invoke-SetupCloud GET "https://run.googleapis.com/v2/$jobResource/executions?pageSize=100"
    if ($history.nextPageToken) { throw 'Unexpected setup execution history.' }
    if ($Action -eq 'Start') {
        if ($Confirmation -cne 'START-ONCE-FICTIONAL-DEVELOPMENT-STAFF-SETUP' -or (Test-Path $markerPath) -or
            @($history.executions | Where-Object { $null -ne $_ }).Count -ne 0) {
            throw 'One-time setup confirmation required; never restart an existing or uncertain execution.'
        }
        $backup = Invoke-SetupCloud GET "https://sqladmin.googleapis.com/sql/v1beta4/projects/$Project/instances/$instanceName/backupRuns/$BackupId"
        $time = Read-SetupBackupTime $backup.endTime
        if ($backup.status -cne 'SUCCESSFUL' -or $backup.type -cne 'ON_DEMAND' -or
            $backup.description -cne 'Pre-Week-2 staff and English profile update' -or
            $time -lt [DateTimeOffset]::UtcNow.AddHours(-4) -or $time -gt [DateTimeOffset]::UtcNow) { throw 'A verified recent staff-setup backup is required.' }
        New-Item -ItemType Directory -Path $controlDirectory -Force | Out-Null
        $marker = @{ project=$Project; region=$Region; job=$jobName; image=$ExpectedImage; source=$ImageSourceRevision
            controller=$ExpectedRevision; planSha256=$ExpectedPlanSha256; backupId=$BackupId; at=[DateTimeOffset]::UtcNow.ToString('o') }
        $handle = [IO.File]::Open($markerPath, 'CreateNew', 'Write', 'None')
        try { $bytes=[Text.Encoding]::UTF8.GetBytes(($marker | ConvertTo-Json -Compress)); $handle.Write($bytes); $handle.Flush($true) }
        finally { $handle.Dispose() }
        $null = Invoke-SetupCloud POST "https://run.googleapis.com/v2/${jobResource}:run" @{}
        Write-Host 'One fictional setup request sent. The permanent record prevents restart. Use Verify; client testing remains pending.'
    } else {
        if (-not (Test-Path $markerPath)) { throw 'No recorded setup start exists.' }
        $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
        if ($marker.project -cne $Project -or $marker.region -cne $Region -or $marker.job -cne $jobName -or
            $marker.image -cne $ExpectedImage -or $marker.source -cne $ImageSourceRevision -or
            $marker.planSha256 -cne $ExpectedPlanSha256 -or $marker.backupId -cne $BackupId) { throw 'Setup marker identifies another release.' }
        if ($marker.controller -cnotmatch '^[0-9a-f]{40}$') { throw 'Invalid recorded setup controller.' }
        & git -C $root merge-base --is-ancestor $marker.controller HEAD
        if ($LASTEXITCODE -ne 0) { throw 'Recorded setup controller is not reviewed history.' }
        $executions = @($history.executions)
        if ($executions.Count -ne 1 -or $executions[0].succeededCount -ne 1 -or $executions[0].failedCount -gt 0 -or
            -not @($executions[0].conditions | Where-Object { $_.type -ceq 'Completed' -and $_.state -ceq 'CONDITION_SUCCEEDED' })) { throw 'Exactly one successful setup execution must be proven. Do not restart.' }
        $execution = ($executions[0].name -split '/')[-1]
        if ($executions[0].name -cne "$jobResource/executions/$execution" -or
            $execution -cnotmatch '^[a-z][a-z0-9-]{0,61}[a-z0-9]$' -or
            -not $execution.StartsWith($jobName + '-', [StringComparison]::Ordinal)) { throw 'Unexpected execution target.' }
        $executedJob = $live | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100
        $executedJob.template.template = $executions[0].template
        $executedJob.template.parallelism = $executions[0].parallelism
        $executedJob.template.taskCount = $executions[0].taskCount
        Assert-SetupJob $executedJob $expectedJob $Project $Region $ExpectedImage $ImageSourceRevision
        $request = @{ resourceNames=@("projects/$Project"); pageSize=100; orderBy='timestamp desc'
            filter='resource.type="cloud_run_job" AND resource.labels.job_name="' + $jobName + '" AND resource.labels.location="' + $Region + '" AND labels."run.googleapis.com/execution_name"="' + $execution + '"' }
        $logs = Invoke-SetupCloud POST 'https://logging.googleapis.com/v2/entries:list' $request
        Assert-SetupCompletion $logs.entries $execution
        Write-Host 'Verified fictional Administrator/Contributor setup and signed-out test sessions. Client authenticator acceptance remains pending.'
    }
} finally { $env:CLOUDSDK_CONFIG=$oldConfig; $accessToken=$null }
