#requires -Version 7.0

[CmdletBinding()]
param(
    [ValidateSet('Plan', 'Apply', 'Cleanup')]
    [string]$Action = 'Plan',
    [Parameter(Mandatory)]
    [string]$BackendConfig,
    [string]$ReviewedPlan,
    [string]$ExpectedPlanSha256,
    [string]$ExpectedRevision,
    [string]$ConfirmMigration
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$foundationDirectory = Join-Path $repositoryRoot 'infrastructure\terraform\foundation'
$secureRuntime = Join-Path $repositoryRoot 'secure-runtime'
$controlDirectory = Join-Path $secureRuntime 'migration-execution'
$lockPath = Join-Path $controlDirectory 'ee003-development.lock'
$markerPath = Join-Path $controlDirectory 'ee003-development.json'
$gcloudConfig = Join-Path $secureRuntime 'gcloud-config'
$expectedApplyConfirmation = 'MIGRATE-EE-003-development'
$expectedCleanupConfirmation = 'CLEANUP-MIGRATION-EE-003-development'
$expectedJobAddress = 'google_cloud_run_v2_job.database_migration[0]'
$expectedOutputName = 'database_migration_job'
$expectedAppliedMigration = 'V0001'
$expectedDatabaseName = 'engagement'
$expectedBackupDescription = 'Pre-EE-003 application table migration safety backup'
$maximumBackupAgeHours = 4
$expectedApplicationSchema = 'engagement_app'
$expectedMigrationSchema = 'engagement_migrations'
$expectedMigrationSourceRevision = '632b248fb2a9d91cd0e34ec9673a17c2a577e438'
$expectedMigrationImageDigest = '22a90388f73d6d9f6f946b4b42e8366edb8aa8e0075e51c6adf2c4e3d3d70b37'

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

function Invoke-GcloudJson {
    param([Parameter(Mandatory)] [string[]]$Arguments, [string]$FailureMessage = 'A Google Cloud read failed.')
    $stderrPath = Join-Path $controlDirectory ("gcloud-{0}.stderr" -f [guid]::NewGuid())
    try {
        $stdout = & $script:gcloud @Arguments 2> $stderrPath
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) { throw $FailureMessage }
        try { return (($stdout -join "`n") | ConvertFrom-Json -Depth 100) }
        catch { throw 'Google Cloud returned an unreadable JSON response.' }
    }
    finally {
        if (Test-Path -LiteralPath $stderrPath) {
            try { Remove-Item -LiteralPath $stderrPath -Force -ErrorAction Stop }
            catch { }
        }
    }
}

function Invoke-GcloudMutation {
    param([Parameter(Mandatory)] [string[]]$Arguments, [string]$FailureMessage)
    return Invoke-GcloudJson -Arguments $Arguments -FailureMessage $FailureMessage
}

function Invoke-TerraformJson {
    param([Parameter(Mandatory)] [string[]]$Arguments, [string]$FailureMessage)
    $stdout = & $script:terraform @Arguments 2>$null
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw $FailureMessage }
    try { return (($stdout -join "`n") | ConvertFrom-Json -Depth 100) }
    catch { throw 'Terraform returned unreadable JSON.' }
}

function Read-StateOutput {
    param([Parameter(Mandatory)] [object]$Outputs, [Parameter(Mandatory)] [string]$Name)
    $property = $Outputs.PSObject.Properties[$Name]
    if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value.value)) {
        throw "Protected Terraform output $Name is missing."
    }
    return [string]$property.Value.value
}

function Get-EnvironmentMap {
    param([object[]]$Entries)
    $map = @{}
    foreach ($entry in @($Entries)) {
        if ([string]::IsNullOrWhiteSpace([string]$entry.name) -or $map.ContainsKey([string]$entry.name)) {
            throw 'The migration job contains a missing or duplicate environment key.'
        }
        if ($null -ne $entry.PSObject.Properties['valueFrom'] -and $null -ne $entry.valueFrom) {
            throw 'The migration job must not use secret-backed environment values.'
        }
        $map[[string]$entry.name] = [string]$entry.value
    }
    return $map
}

function Get-PlanEnvironmentMap {
    param([object[]]$Entries)
    $map = @{}
    foreach ($entry in @($Entries)) {
        if ([string]::IsNullOrWhiteSpace([string]$entry.name) -or $map.ContainsKey([string]$entry.name)) {
            throw 'The reviewed plan contains a missing or duplicate environment key.'
        }
        if (@($entry.value_source | Where-Object { $null -ne $_ }).Count -ne 0) {
            throw 'The reviewed plan must not use secret-backed environment values.'
        }
        $map[[string]$entry.name] = [string]$entry.value
    }
    return $map
}

function Assert-ExactEnvironmentMap {
    param([hashtable]$Expected, [hashtable]$Actual)
    if ($Expected.Count -ne 8 -or $Actual.Count -ne $Expected.Count) {
        throw 'The live migration job has an unexpected environment contract.'
    }
    foreach ($key in $Expected.Keys) {
        if (-not $Actual.ContainsKey($key) -or $Actual[$key] -cne $Expected[$key]) {
            throw 'The live migration job differs from the reviewed environment contract.'
        }
    }
}

function Assert-ExactPropertyNames {
    param(
        [Parameter(Mandatory)] [object]$Object,
        [Parameter(Mandatory)] [string[]]$Expected,
        [Parameter(Mandatory)] [string]$Label
    )
    $actual = @($Object.PSObject.Properties.Name | Sort-Object)
    $wanted = @($Expected | Sort-Object)
    if (($actual -join "`n") -cne ($wanted -join "`n")) {
        throw "$Label contains an unexpected executable field."
    }
}

function Get-ExecutionCount {
    $executions = @(Invoke-GcloudJson -Arguments @(
        'run', 'jobs', 'executions', 'list', "--job=$script:jobName",
        "--project=$script:projectId", "--region=$script:region", '--format=json', '--quiet'
    ) -FailureMessage 'Migration execution history could not be read.')
    return $executions.Count
}

function Get-JobPolicy {
    return Invoke-GcloudJson -Arguments @(
        'run', 'jobs', 'get-iam-policy', $script:jobName,
        "--project=$script:projectId", "--region=$script:region", '--format=json', '--quiet'
    ) -FailureMessage 'Migration job permissions could not be read.'
}

function Get-InvokerMembers {
    param([object]$Policy)
    return @(
        $Policy.bindings |
            Where-Object { $_.role -eq 'roles/run.invoker' } |
            ForEach-Object { @($_.members) }
    )
}

function Get-ActiveHumanOperator {
    $operator = [string](& $script:gcloud auth list '--filter=status:ACTIVE' '--format=value(account)' 2>$null)
    if ($LASTEXITCODE -ne 0) { throw 'The active Google Cloud operator could not be read.' }
    $operator = $operator.Trim()
    if ($operator -notmatch '^[a-z0-9.!#$%&''*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}$' -or
        $operator.EndsWith('.gserviceaccount.com')) {
        throw 'The active Google Cloud identity must be one named human operator.'
    }
    return $operator
}

function Assert-EffectiveRunPermission {
    param(
        [string]$OnlyAllowedPrincipal,
        [switch]$RequireAllowedPrincipal,
        [switch]$RequireNoPrincipal
    )
    if ($RequireAllowedPrincipal -eq $RequireNoPrincipal -or
        ($RequireAllowedPrincipal -and [string]::IsNullOrWhiteSpace($OnlyAllowedPrincipal))) {
        throw 'Permission analysis requires exactly one explicit expectation mode.'
    }
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        $analysis = Invoke-GcloudJson -Arguments @(
            'asset', 'analyze-iam-policy', "--organization=$script:organizationId",
            "--full-resource-name=$script:fullJobResourceName", '--permissions=run.jobs.run',
            '--expand-groups', '--expand-roles', '--show-response', '--format=json', '--quiet'
        ) -FailureMessage 'Effective Cloud Run job permission analysis failed.'
        if (-not [bool]$analysis.fullyExplored -or -not [bool]$analysis.mainAnalysis.fullyExplored -or
            @($analysis.mainAnalysis.nonCriticalErrors | Where-Object { $null -ne $_ }).Count -ne 0) {
            throw 'Effective Cloud Run job permission analysis was incomplete.'
        }
        $identities = @(
            $analysis.mainAnalysis.analysisResults |
                ForEach-Object { @($_.identityList.identities) } |
                ForEach-Object { if ($_ -is [string]) { $_ } else { [string]$_.name } } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                Sort-Object -Unique
        )
        if ($RequireNoPrincipal) {
            if ($identities.Count -eq 0) { return }
            if ($attempt -lt 6) {
                Start-Sleep -Seconds 5
                continue
            }
            throw 'An identity still has effective permission to run the migration job.'
        }
        $unexpected = @($identities | Where-Object { $_ -cne $OnlyAllowedPrincipal })
        if ($unexpected.Count -ne 0) {
            throw 'An unapproved identity has effective permission to run the migration job.'
        }
        if ($identities.Count -eq 1 -and $identities[0] -ceq $OnlyAllowedPrincipal) {
            return
        }
        if ($attempt -lt 6) { Start-Sleep -Seconds 5 }
    }
    throw 'Permission analysis did not prove the approved temporary operator.'
}

function Ensure-OrganizationContext {
    if (-not [string]::IsNullOrWhiteSpace([string]$script:organizationId)) { return }
    $ancestry = @(Invoke-GcloudJson -Arguments @(
        'projects', 'get-ancestors', $script:projectId, '--format=json', '--quiet'
    ) -FailureMessage 'Project ancestry could not be read.')
    $organizations = @($ancestry | Where-Object { $_.type -eq 'organization' })
    if ($organizations.Count -ne 1) {
        throw 'The project must belong to exactly one approved organization.'
    }
    $script:organizationId = [string]$organizations[0].id
}

function Assert-FreshBackup {
    $backups = @(Invoke-GcloudJson -Arguments @(
        'sql', 'backups', 'list', "--instance=$script:databaseInstance",
        "--project=$script:projectId", '--limit=20', '--format=json', '--quiet'
    ) -FailureMessage 'Cloud SQL safety backups could not be read.')
    $freshBackup = $backups |
        Where-Object {
            $_.status -eq 'SUCCESSFUL' -and $_.type -eq 'ON_DEMAND' -and
            $_.description -eq $script:expectedBackupDescription
        } |
        Sort-Object { [datetime]$_.endTime } -Descending |
        Select-Object -First 1
    if ($null -eq $freshBackup -or
        [datetime]$freshBackup.endTime -lt [datetime]::UtcNow.AddHours(-$script:maximumBackupAgeHours)) {
        throw 'A recent successful on-demand pre-migration backup is required.'
    }
}

function Assert-LiveJobMatchesPlan {
    param(
        [Parameter(Mandatory)] [object]$ExpectedJob,
        [Parameter(Mandatory)] [hashtable]$ExpectedEnvironment,
        [Parameter(Mandatory)] [string]$ExpectedServiceAccount,
        [Parameter(Mandatory)] [string]$ExpectedImage,
        [Parameter(Mandatory)] [string]$ExpectedNetwork,
        [Parameter(Mandatory)] [string]$ExpectedSubnetwork
    )
    $live = Invoke-GcloudJson -Arguments @(
        'run', 'jobs', 'describe', $script:jobName,
        "--project=$script:projectId", "--region=$script:region", '--format=json', '--quiet'
    ) -FailureMessage 'The live migration job could not be read.'
    $expectedExecution = $ExpectedJob.template[0]
    $expectedTask = $expectedExecution.template[0]
    $expectedContainer = $expectedTask.containers[0]
    $liveExecution = $live.spec.template.spec
    $liveTask = $liveExecution.template.spec
    $liveContainer = $liveTask.containers[0]
    Assert-ExactPropertyNames -Object $liveExecution -Expected @('parallelism', 'taskCount', 'template') -Label 'Live execution template'
    Assert-ExactPropertyNames -Object $liveTask -Expected @('containers', 'maxRetries', 'serviceAccountName', 'timeoutSeconds') -Label 'Live task template'
    Assert-ExactPropertyNames -Object $liveContainer -Expected @('env', 'image', 'resources') -Label 'Live container'
    Assert-ExactPropertyNames -Object $liveContainer.resources -Expected @('limits') -Label 'Live container resources'
    $planEnvironment = Get-PlanEnvironmentMap -Entries $expectedContainer.env
    Assert-ExactEnvironmentMap -Expected $ExpectedEnvironment -Actual $planEnvironment
    $unexpectedPlanExecutableFields = @(
        $expectedContainer.command,
        $expectedContainer.commands,
        $expectedContainer.args,
        $expectedContainer.working_dir,
        $expectedContainer.ports
    ) | Where-Object { $null -ne $_ -and @($_).Count -ne 0 }
    $unexpectedLiveExecutableFields = @(
        $liveContainer.command,
        $liveContainer.args,
        $liveContainer.workingDir,
        $liveContainer.ports
    ) | Where-Object { $null -ne $_ -and @($_).Count -ne 0 }
    if ($expectedExecution.task_count -ne 1 -or $expectedExecution.parallelism -ne 1 -or
        $liveExecution.taskCount -ne 1 -or $liveExecution.parallelism -ne 1 -or
        $expectedTask.max_retries -ne 0 -or $liveTask.maxRetries -ne 0 -or
        $expectedTask.timeout -ne '900s' -or $liveTask.timeoutSeconds -ne '900' -or
        @($expectedTask.containers).Count -ne 1 -or @($liveTask.containers).Count -ne 1 -or
        @($expectedTask.volumes | Where-Object { $null -ne $_ }).Count -ne 0 -or
        @($liveTask.volumes | Where-Object { $null -ne $_ }).Count -ne 0 -or
        @($expectedContainer.volume_mounts | Where-Object { $null -ne $_ }).Count -ne 0 -or
        @($liveContainer.volumeMounts | Where-Object { $null -ne $_ }).Count -ne 0 -or
        @($unexpectedPlanExecutableFields).Count -ne 0 -or
        @($unexpectedLiveExecutableFields).Count -ne 0) {
        throw 'The live migration job execution limits differ from the reviewed plan.'
    }
    if ($null -ne $expectedTask.encryption_key -or
        $null -ne $expectedTask.gpu_zonal_redundancy_disabled -or
        @($expectedTask.node_selector | Where-Object { $null -ne $_ }).Count -ne 0 -or
        $null -ne $expectedContainer.name -or $null -ne $expectedContainer.depends_on -or
        $null -ne $expectedExecution.annotations -or $null -ne $expectedExecution.labels) {
        throw 'The reviewed plan contains an unapproved executable option.'
    }
    $expectedLimits = $expectedContainer.resources[0].limits
    $liveLimits = $liveContainer.resources.limits
    if (@($expectedContainer.resources).Count -ne 1 -or
        @($expectedLimits.PSObject.Properties).Count -ne 2 -or
        [string]$expectedLimits.cpu -cne '1' -or [string]$expectedLimits.memory -cne '512Mi' -or
        @($liveLimits.PSObject.Properties).Count -ne 2 -or
        [string]$liveLimits.cpu -cne '1' -or [string]$liveLimits.memory -cne '512Mi') {
        throw 'The live migration job resource limits differ from the approved limits.'
    }
    if ([string]$expectedContainer.image -cne $ExpectedImage -or
        [string]$expectedTask.service_account -cne $ExpectedServiceAccount -or
        [string]$liveContainer.image -cne [string]$expectedContainer.image -or
        [string]$liveTask.serviceAccountName -cne [string]$expectedTask.service_account) {
        throw 'The live migration image or service identity differs from the reviewed plan.'
    }
    $expectedVPC = $expectedTask.vpc_access[0]
    $annotations = $live.spec.template.metadata.annotations
    Assert-ExactPropertyNames -Object $annotations -Expected @(
        'run.googleapis.com/execution-environment',
        'run.googleapis.com/network-interfaces',
        'run.googleapis.com/vpc-access-egress'
    ) -Label 'Live execution annotations'
    $liveInterfaces = @(([string]$annotations.'run.googleapis.com/network-interfaces' | ConvertFrom-Json))
    if (@($expectedTask.vpc_access).Count -ne 1 -or
        @($expectedVPC.network_interfaces).Count -ne 1 -or
        $expectedVPC.egress -ne 'PRIVATE_RANGES_ONLY' -or
        [string]$expectedVPC.network_interfaces[0].network -cne $ExpectedNetwork -or
        [string]$expectedVPC.network_interfaces[0].subnetwork -cne $ExpectedSubnetwork -or
        [string]$expectedTask.execution_environment -cne 'EXECUTION_ENVIRONMENT_GEN2' -or
        [string]$annotations.'run.googleapis.com/execution-environment' -cne 'gen2' -or
        [string]$annotations.'run.googleapis.com/vpc-access-egress' -ne 'private-ranges-only' -or
        $liveInterfaces.Count -ne 1 -or
        [string]$liveInterfaces[0].network -cne [string]$expectedVPC.network_interfaces[0].network -or
        [string]$liveInterfaces[0].subnetwork -cne [string]$expectedVPC.network_interfaces[0].subnetwork) {
        throw 'The live migration job network differs from the reviewed private network.'
    }
    Assert-ExactEnvironmentMap `
        -Expected $planEnvironment `
        -Actual (Get-EnvironmentMap -Entries $liveContainer.env)
}

function Write-RecoveryMarker {
    param([Parameter(Mandatory)] [hashtable]$Marker)
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($Marker | ConvertTo-Json))
    $stream = [IO.File]::Open(
        $markerPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally { $stream.Dispose() }
}

function Clear-TemporaryInvokerBinding {
    param([switch]$SkipEffectiveAnalysis)
    if (-not $script:bindingCleanupArmed -or
        [string]::IsNullOrWhiteSpace([string]$script:temporaryOperator)) {
        return
    }
    $script:bindingCleanupAttempted = $true
    $principal = "user:$script:temporaryOperator"
    try {
        $policy = Get-JobPolicy
        if (@(Get-InvokerMembers -Policy $policy) -contains $principal) {
            Invoke-GcloudMutation -Arguments @(
                'run', 'jobs', 'remove-iam-policy-binding', $script:jobName,
                "--project=$script:projectId", "--region=$script:region", "--member=$principal",
                '--role=roles/run.invoker', '--format=json', '--quiet'
            ) -FailureMessage 'Temporary migration permission could not be removed.' | Out-Null
        }
        if (@(Get-InvokerMembers -Policy (Get-JobPolicy)).Count -ne 0) {
            throw 'An explicit migration invoker binding remains.'
        }
        if (-not $SkipEffectiveAnalysis) {
            Ensure-OrganizationContext
            Assert-EffectiveRunPermission -RequireNoPrincipal
        }
        $script:bindingCleanupVerified = $true
    }
    catch { $script:cleanupErrors.Add('Temporary migration execution permission cleanup failed.') }
}

$resolvedBackend = Resolve-IgnoredInputFile -Path $BackendConfig -Label 'BackendConfig'
$resolvedPlan = $null
if ($Action -ne 'Cleanup') {
    if ([string]::IsNullOrWhiteSpace($ReviewedPlan)) {
        throw 'Plan and Apply require the reviewed dormant-job plan file.'
    }
    $resolvedPlan = Resolve-IgnoredInputFile -Path $ReviewedPlan -Label 'ReviewedPlan'
    if ($ExpectedPlanSha256 -notmatch '^[0-9a-f]{64}$' -or
        (Get-FileHash -LiteralPath $resolvedPlan -Algorithm SHA256).Hash.ToLowerInvariant() -cne
            $ExpectedPlanSha256.ToLowerInvariant()) {
        throw 'The reviewed migration plan does not match its approved SHA-256 fingerprint.'
    }
}
if (-not (Test-Path -LiteralPath $gcloudConfig -PathType Container)) {
    throw 'The protected D-drive Google Cloud configuration is missing.'
}

$previousCloudSdkConfig = $env:CLOUDSDK_CONFIG
$previousAccessToken = $env:GOOGLE_OAUTH_ACCESS_TOKEN
$env:CLOUDSDK_CONFIG = $gcloudConfig
$lockHandle = $null
$markerCreatedThisRun = $false
$iamMutationAttempted = $false
$bindingCleanupArmed = $false
$bindingCleanupAttempted = $false
$bindingCleanupVerified = $false
$temporaryOperator = $null
$executionResponse = $null
$executionExitCode = $null
$executionVerified = $false
$cleanupErrors = [System.Collections.Generic.List[string]]::new()

try {
    $gcloud = Resolve-GcloudCommand
    $terraform = Resolve-TerraformCommand
    New-Item -ItemType Directory -Path $controlDirectory -Force | Out-Null
    try {
        $lockHandle = [IO.File]::Open(
            $lockPath, [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite, [IO.FileShare]::None
        )
    }
    catch [IO.IOException] { throw 'Another migration Plan, Apply or Cleanup process is running.' }

    $accessToken = [string](& $gcloud auth print-access-token --quiet 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($accessToken)) {
        throw 'A short-lived Google Cloud access token could not be obtained.'
    }
    $env:GOOGLE_OAUTH_ACCESS_TOKEN = $accessToken.Trim()
    $terraformDirectoryArgument = "-chdir=$foundationDirectory"
    & $terraform $terraformDirectoryArgument init -input=false "-backend-config=$resolvedBackend" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Protected Terraform state could not be initialised.' }
    $stateOutputs = Invoke-TerraformJson -Arguments @(
        $terraformDirectoryArgument, 'output', '-json'
    ) -FailureMessage 'Protected Terraform outputs could not be read.'
    $environment = Read-StateOutput -Outputs $stateOutputs -Name 'deployment_environment'
    $projectId = Read-StateOutput -Outputs $stateOutputs -Name 'deployment_project_id'
    $region = Read-StateOutput -Outputs $stateOutputs -Name 'deployment_region'
    $jobResource = Read-StateOutput -Outputs $stateOutputs -Name 'database_migration_job'
    $expectedNamePrefix = "ee-$environment"
    if ($environment -cne 'development' -or
        $jobResource -notmatch '^(?:.*/jobs/)?([a-z][a-z0-9-]{0,61}[a-z0-9])$') {
        throw 'Protected state does not identify the approved development migration job.'
    }
    $jobName = ($jobResource -split '/')[-1]
    if ($jobName -cne "$expectedNamePrefix-database-migration") {
        throw 'Protected state identifies an unexpected migration job.'
    }
    $fullJobResourceName = "//run.googleapis.com/projects/$projectId/locations/$region/jobs/$jobName"

    if ($Action -eq 'Cleanup') {
        if ($ConfirmMigration -cne $expectedCleanupConfirmation) {
            throw "Cleanup requires -ConfirmMigration $expectedCleanupConfirmation."
        }
        $null = Get-ActiveHumanOperator
        if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
            throw 'No protected migration recovery marker exists.'
        }
        $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
        if ($marker.projectId -ne $projectId -or $marker.region -ne $region -or
            $marker.jobName -ne $jobName) {
            throw 'The migration recovery marker does not match the protected target.'
        }
        $temporaryOperator = [string]$marker.operator
        if ($temporaryOperator -notmatch '^[a-z0-9.!#$%&''*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}$' -or
            $temporaryOperator.EndsWith('.gserviceaccount.com')) {
            throw 'The migration recovery marker has an invalid operator.'
        }
        $bindingCleanupArmed = $true
    }
    else {
        $databaseInstance = Read-StateOutput -Outputs $stateOutputs -Name 'database_instance_name'
        $databaseConnection = Read-StateOutput -Outputs $stateOutputs -Name 'database_connection_name'
        $databaseName = Read-StateOutput -Outputs $stateOutputs -Name 'database_name'
        $migrationIamUser = Read-StateOutput -Outputs $stateOutputs -Name 'database_migration_iam_user'
        $runtimeIamUser = Read-StateOutput -Outputs $stateOutputs -Name 'database_runtime_iam_user'
        $artifactRepository = Read-StateOutput -Outputs $stateOutputs -Name 'artifact_repository'
        $serverlessNetwork = Read-StateOutput -Outputs $stateOutputs -Name 'serverless_network_name'
        $serverlessSubnetwork = Read-StateOutput -Outputs $stateOutputs -Name 'serverless_subnetwork_name'
        $repositorySlug = Read-StateOutput -Outputs $stateOutputs -Name 'github_repository_slug'
        if ($databaseInstance -cne "$expectedNamePrefix-postgres" -or
            $databaseName -cne $expectedDatabaseName -or
            $databaseConnection -cne "$projectId`:$region`:$databaseInstance" -or
            $migrationIamUser -cne "$expectedNamePrefix-migration@$projectId.iam" -or
            $runtimeIamUser -cne "$expectedNamePrefix-runtime@$projectId.iam" -or
            $serverlessNetwork -cne "$expectedNamePrefix-network" -or
            $serverlessSubnetwork -cne "$expectedNamePrefix-serverless" -or
            $artifactRepository -notmatch '^projects/[^/]+/locations/[^/]+/repositories/([^/]+)$') {
            throw 'Protected state does not identify the approved migration dependencies.'
        }
        $artifactParts = @($artifactRepository -split '/')
        if ($artifactParts.Count -ne 6 -or $artifactParts[0] -cne 'projects' -or
            $artifactParts[1] -cne $projectId -or $artifactParts[2] -cne 'locations' -or
            $artifactParts[3] -cne $region -or $artifactParts[4] -cne 'repositories' -or
            $repositorySlug -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
            throw 'Protected state contains an unexpected repository target.'
        }
        $artifactRepositoryId = $artifactParts[-1]
        $expectedImage = "$region-docker.pkg.dev/$projectId/$artifactRepositoryId/engagement-migration@sha256:$expectedMigrationImageDigest"
        $plan = Invoke-TerraformJson -Arguments @(
            $terraformDirectoryArgument, 'show', '-json', $resolvedPlan
        ) -FailureMessage 'The reviewed migration plan could not be read.'
        Ensure-OrganizationContext
        if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
            throw 'A previous migration may have been interrupted. Run Cleanup; never rerun Apply.'
        }
        $changes = @($plan.resource_changes | Where-Object { (@($_.change.actions) -join ',') -ne 'no-op' })
        $outputChanges = @(
            $plan.output_changes.PSObject.Properties |
                Where-Object { (@($_.Value.actions) -join ',') -ne 'no-op' }
        )
        if ($changes.Count -ne 1 -or $changes[0].address -ne $expectedJobAddress -or
            (@($changes[0].change.actions) -join ',') -ne 'create' -or
            $outputChanges.Count -ne 1 -or $outputChanges[0].Name -ne $expectedOutputName) {
            throw 'The reviewed plan is not the approved dormant migration-job creation plan.'
        }
        if ((@($outputChanges[0].Value.actions) -join ',') -ne 'create') {
            throw 'The reviewed migration-job output must be a create-only change.'
        }
        $expectedJob = $changes[0].change.after
        $expectedEnvironment = @{
            MIGRATION_MODE = 'production'
            INSTANCE_CONNECTION_NAME = $databaseConnection
            DB_NAME = $databaseName
            DB_MIGRATION_IAM_USER = $migrationIamUser
            DB_RUNTIME_IAM_USER = $runtimeIamUser
            APP_SCHEMA = $expectedApplicationSchema
            MIGRATION_SCHEMA = $expectedMigrationSchema
            SOURCE_REVISION = $expectedMigrationSourceRevision
        }
        Assert-LiveJobMatchesPlan `
            -ExpectedJob $expectedJob `
            -ExpectedEnvironment $expectedEnvironment `
            -ExpectedServiceAccount "$migrationIamUser.gserviceaccount.com" `
            -ExpectedImage $expectedImage `
            -ExpectedNetwork $serverlessNetwork `
            -ExpectedSubnetwork $serverlessSubnetwork

        $activeOperator = Get-ActiveHumanOperator
        $allowedPrincipal = "user:$activeOperator"
        $invokerMembers = @(Get-InvokerMembers -Policy (Get-JobPolicy))
        if ($invokerMembers.Count -ne 0) {
            throw 'The migration job already has an explicit invoker binding.'
        }
        Assert-EffectiveRunPermission -RequireNoPrincipal
        if ((Get-ExecutionCount) -ne 0) {
            throw 'The one-time migration job has already been executed.'
        }
        Assert-FreshBackup
        Write-Output 'Migration safety plan passed: live job, effective access, backup gate and zero executions are approved.'
        Write-Output 'No migration was executed by the plan check.'
        if ($Action -eq 'Plan') { return }

        if ($ConfirmMigration -cne $expectedApplyConfirmation) {
            throw "Apply requires -ConfirmMigration $expectedApplyConfirmation."
        }
        if ($ExpectedRevision -notmatch '^[0-9a-f]{40}$') {
            throw 'Apply requires the exact reviewed 40-character Git revision.'
        }
        $originUrl = (& git -C $repositoryRoot remote get-url origin).Trim().Replace('\', '/')
        $approvedRemotePattern = '^(?i:(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)' +
            [regex]::Escape($repositorySlug) + '(?:\.git)?)$'
        if ($LASTEXITCODE -ne 0 -or $originUrl -notmatch $approvedRemotePattern) {
            throw 'Git origin does not exactly match protected Terraform state.'
        }
        & git -C $repositoryRoot fetch --quiet origin main
        if ($LASTEXITCODE -ne 0) { throw 'Protected origin/main could not be refreshed.' }
        $branch = (& git -C $repositoryRoot branch --show-current).Trim()
        $headRevision = (& git -C $repositoryRoot rev-parse HEAD).Trim()
        $originRevision = (& git -C $repositoryRoot rev-parse origin/main).Trim()
        $repositoryChanges = @(& git -C $repositoryRoot status --porcelain --untracked-files=all)
        if ($branch -ne 'main' -or $headRevision -ne $ExpectedRevision -or
            $originRevision -ne $ExpectedRevision -or $repositoryChanges.Count -ne 0) {
            throw 'Live migration requires the exact clean reviewed origin/main revision.'
        }

        $temporaryOperator = $activeOperator
        Write-RecoveryMarker -Marker @{
            projectId = $projectId
            region = $region
            jobName = $jobName
            operator = $temporaryOperator
            expectedRevision = $ExpectedRevision
            createdAtUtc = [datetime]::UtcNow.ToString('o')
        }
        $markerCreatedThisRun = $true
        $bindingCleanupArmed = $true
        $iamMutationAttempted = $true
        Invoke-GcloudMutation -Arguments @(
            'run', 'jobs', 'add-iam-policy-binding', $jobName,
            "--project=$projectId", "--region=$region", "--member=$allowedPrincipal",
            '--role=roles/run.invoker', '--format=json', '--quiet'
        ) -FailureMessage 'Temporary migration execution permission could not be added.' | Out-Null
        $membersAfterGrant = @(Get-InvokerMembers -Policy (Get-JobPolicy))
        if ($membersAfterGrant.Count -ne 1 -or $membersAfterGrant[0] -cne $allowedPrincipal) {
            throw 'Temporary migration execution permission does not match the approved operator.'
        }
        Assert-EffectiveRunPermission -OnlyAllowedPrincipal $allowedPrincipal -RequireAllowedPrincipal
        if ((Get-ExecutionCount) -ne 0) {
            throw 'Migration execution history changed before the approved run.'
        }

        $executionResponse = Invoke-GcloudMutation -Arguments @(
            'run', 'jobs', 'execute', $jobName,
            "--project=$projectId", "--region=$region", '--format=json', '--quiet'
        ) -FailureMessage 'The one-time migration execution could not be started.'
        $executionExitCode = 0

        $executionName = [string]$executionResponse.metadata.name
        if ([string]::IsNullOrWhiteSpace($executionName)) { $executionName = [string]$executionResponse.name }
        $executionName = ($executionName -split '/')[-1]
        if ($executionName -notmatch '^[a-z][a-z0-9-]{0,61}[a-z0-9]$' -or
            -not $executionName.StartsWith("$jobName-")) {
            throw 'The migration returned an invalid execution identity.'
        }

        Clear-TemporaryInvokerBinding
        if (-not $bindingCleanupVerified -or $cleanupErrors.Count -ne 0) {
            throw 'Temporary migration execution permission cleanup could not be proven.'
        }
        if ((Get-ExecutionCount) -ne 1) {
            throw 'The exact one-time migration execution could not be isolated.'
        }

        $execution = $null
        for ($attempt = 1; $attempt -le 190; $attempt++) {
            $execution = Invoke-GcloudJson -Arguments @(
                'run', 'jobs', 'executions', 'describe', $executionName,
                "--project=$projectId", "--region=$region", '--format=json', '--quiet'
            ) -FailureMessage 'The migration execution could not be monitored.'
            if ([int]$execution.status.failedCount -gt 0) {
                throw 'The migration execution reported a failed task.'
            }
            $completed = @($execution.status.conditions | Where-Object { $_.type -eq 'Completed' })
            if ($completed.Count -eq 1 -and [string]$completed[0].status -eq 'True') { break }
            if ($attempt -eq 190) { throw 'The migration execution did not finish within its approved time window.' }
            Start-Sleep -Seconds 5
        }
        $completed = @($execution.status.conditions | Where-Object { $_.type -eq 'Completed' })
        if ($completed.Count -ne 1 -or [string]$completed[0].status -ne 'True' -or
            [int]$execution.status.succeededCount -ne 1 -or [int]$execution.status.failedCount -ne 0) {
            throw 'The migration execution did not complete with exactly one successful task.'
        }

        $successRecords = @()
        for ($attempt = 1; $attempt -le 6 -and $successRecords.Count -eq 0; $attempt++) {
            $filter = 'resource.type="cloud_run_job" AND resource.labels.job_name="' + $jobName +
                '" AND labels.execution_name="' + $executionName + '"'
            $logs = @(Invoke-GcloudJson -Arguments @(
                'logging', 'read', $filter, "--project=$projectId", '--limit=100', '--format=json', '--quiet'
            ) -FailureMessage 'Migration execution logs could not be read.')
            foreach ($entry in $logs) {
                $record = $null
                if ($entry.jsonPayload.status) {
                    $record = $entry.jsonPayload
                }
                else {
                    $candidate = if ($entry.textPayload) { [string]$entry.textPayload } elseif ($entry.jsonPayload.message) {
                        [string]$entry.jsonPayload.message
                    }
                    else { $null }
                    if (-not [string]::IsNullOrWhiteSpace($candidate)) {
                        try { $record = $candidate | ConvertFrom-Json }
                        catch { }
                    }
                }
                if ($null -ne $record -and $record.status -eq 'ok' -and
                    @($record.applied).Count -eq 1 -and
                    $record.applied[0] -eq $expectedAppliedMigration) {
                    $successRecords += $record
                }
            }
            if ($successRecords.Count -eq 0 -and $attempt -lt 6) { Start-Sleep -Seconds 5 }
        }
        if ($successRecords.Count -ne 1 -or (Get-ExecutionCount) -ne 1) {
            throw 'The migration success record or one-time execution count could not be proven.'
        }
        $executionVerified = $true
    }
}
finally {
    Clear-TemporaryInvokerBinding -SkipEffectiveAnalysis:($Action -eq 'Cleanup')
    $removeMarker = $markerCreatedThisRun -and -not $iamMutationAttempted
    if ($removeMarker -and (Test-Path -LiteralPath $markerPath)) {
        try { Remove-Item -LiteralPath $markerPath -Force }
        catch { $cleanupErrors.Add('The migration recovery marker could not be removed.') }
    }
    if ($null -eq $previousAccessToken) {
        Remove-Item Env:GOOGLE_OAUTH_ACCESS_TOKEN -ErrorAction SilentlyContinue
    }
    else { $env:GOOGLE_OAUTH_ACCESS_TOKEN = $previousAccessToken }
    if ($null -eq $previousCloudSdkConfig) {
        Remove-Item Env:CLOUDSDK_CONFIG -ErrorAction SilentlyContinue
    }
    else { $env:CLOUDSDK_CONFIG = $previousCloudSdkConfig }
    if ($null -ne $lockHandle) { $lockHandle.Dispose() }
}

if ($cleanupErrors.Count -ne 0) { throw ($cleanupErrors -join ' ') }
if ($Action -eq 'Cleanup') {
    Write-Output 'Migration cleanup completed: the temporary job-level execution permission is absent.'
    Write-Output 'The permanent attempt marker remains by design. Do not rerun the migration.'
    return
}
if ($executionExitCode -ne 0 -or $null -eq $executionResponse -or -not $executionVerified) {
    throw 'The one-time migration did not return a successful execution response.'
}

Write-Output 'Migration completed safely: V0001 was applied once and all database postchecks passed.'
Write-Output 'The temporary job-level execution permission was removed and verified.'
