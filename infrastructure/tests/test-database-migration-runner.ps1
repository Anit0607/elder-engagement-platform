#requires -Version 7.0

$ErrorActionPreference = 'Stop'
$runnerPath = (Resolve-Path (Join-Path $PSScriptRoot '..\scripts\Invoke-DatabaseMigration.ps1')).Path
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $runnerPath, [ref]$tokens, [ref]$errors
)
if ($errors.Count -ne 0) { throw 'The migration runner does not parse.' }

$requiredFunctions = @(
    'Get-EnvironmentMap',
    'Get-PlanEnvironmentMap',
    'Get-ExpectedMigrationImage',
    'Get-ExecutionLogFilter',
    'Test-ExecutionLogEntry',
    'Assert-ExactEnvironmentMap',
    'Assert-ExactPropertyNames',
    'Assert-LiveJobMatchesPlan'
)
foreach ($name in $requiredFunctions) {
    $definition = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($definition.Count -ne 1) { throw "Expected exactly one $name function." }
    . ([scriptblock]::Create($definition[0].Extent.Text))
}

$expectedLogFilter = 'resource.type="cloud_run_job" AND resource.labels.job_name="migration-job"'
if ((Get-ExecutionLogFilter -JobName 'migration-job') -cne $expectedLogFilter) {
    throw 'The execution log filter is not limited to the protected Cloud Run job.'
}
$matchingEntry = [pscustomobject]@{ labels = [pscustomobject]@{
    'run.googleapis.com/execution_name' = 'migration-job-run1'
} }
$differentEntry = [pscustomobject]@{ labels = [pscustomobject]@{
    'run.googleapis.com/execution_name' = 'migration-job-run2'
} }
if (-not (Test-ExecutionLogEntry -Entry $matchingEntry -ExecutionName 'migration-job-run1') -or
    (Test-ExecutionLogEntry -Entry $differentEntry -ExecutionName 'migration-job-run1')) {
    throw 'Execution log entries are not isolated to the exact Cloud Run execution.'
}

$script:expectedMigrationImageDigest = 'b' * 64
$derivedImage = Get-ExpectedMigrationImage `
    -ProjectId 'sample-project' `
    -Region 'test-region1' `
    -Environment 'development' `
    -ArtifactRepository 'ee-development-containers'
$expectedDerivedImage = 'test-region1-docker.pkg.dev/sample-project/ee-development-containers/' +
    'engagement-migration@sha256:' + ('b' * 64)
if ($derivedImage -cne $expectedDerivedImage) {
    throw 'The short protected artifact repository name was not expanded correctly.'
}
$longRepositoryRejected = $false
try {
    Get-ExpectedMigrationImage `
        -ProjectId 'sample-project' `
        -Region 'test-region1' `
        -Environment 'development' `
        -ArtifactRepository 'projects/sample-project/locations/test-region1/repositories/ee-development-containers' |
        Out-Null
}
catch { $longRepositoryRejected = $true }
if (-not $longRepositoryRejected) { throw 'An unexpected long artifact repository value was accepted.' }

$environment = @{
    MIGRATION_MODE = 'production'
    INSTANCE_CONNECTION_NAME = 'project:region:database'
    DB_NAME = 'engagement'
    DB_MIGRATION_IAM_USER = 'migration@project.iam'
    DB_RUNTIME_IAM_USER = 'runtime@project.iam'
    APP_SCHEMA = 'engagement_app'
    MIGRATION_SCHEMA = 'engagement_migrations'
    SOURCE_REVISION = 'a' * 40
}
$environmentEntries = @(
    $environment.GetEnumerator() | ForEach-Object {
        [pscustomobject]@{ name = $_.Key; value = $_.Value; value_source = @() }
    }
)
$image = 'region-docker.pkg.dev/project/repository/migration@sha256:' + ('b' * 64)
$serviceAccount = 'migration@project.iam.gserviceaccount.com'
$network = 'private-network'
$subnetwork = 'private-subnetwork'
$plannedContainer = [pscustomobject]@{
    args = $null
    command = $null
    depends_on = $null
    env = $environmentEntries
    image = $image
    name = $null
    ports = @()
    resources = @([pscustomobject]@{
        limits = [pscustomobject]@{ cpu = '1'; memory = '512Mi' }
    })
    volume_mounts = @()
    working_dir = $null
}
$plannedTask = [pscustomobject]@{
    containers = @($plannedContainer)
    encryption_key = $null
    execution_environment = 'EXECUTION_ENVIRONMENT_GEN2'
    gpu_zonal_redundancy_disabled = $null
    max_retries = 0
    node_selector = @()
    service_account = $serviceAccount
    timeout = '900s'
    volumes = @()
    vpc_access = @([pscustomobject]@{
        egress = 'PRIVATE_RANGES_ONLY'
        network_interfaces = @([pscustomobject]@{
            network = $network
            subnetwork = $subnetwork
        })
    })
}
$plannedJob = [pscustomobject]@{
    template = @([pscustomobject]@{
        annotations = $null
        labels = $null
        parallelism = 1
        task_count = 1
        template = @($plannedTask)
    })
}
$liveEnvironment = @(
    $environment.GetEnumerator() | ForEach-Object {
        [pscustomobject]@{ name = $_.Key; value = $_.Value }
    }
)
$liveContainer = [pscustomobject]@{
    env = $liveEnvironment
    image = $image
    resources = [pscustomobject]@{
        limits = [pscustomobject]@{ cpu = '1'; memory = '512Mi' }
    }
}
$liveTask = [pscustomobject]@{
    containers = @($liveContainer)
    maxRetries = 0
    serviceAccountName = $serviceAccount
    timeoutSeconds = '900'
}
$script:mockResponse = [pscustomobject]@{
    spec = [pscustomobject]@{
        template = [pscustomobject]@{
            metadata = [pscustomobject]@{
                annotations = [pscustomobject]@{
                    'run.googleapis.com/execution-environment' = 'gen2'
                    'run.googleapis.com/network-interfaces' = (@([pscustomobject]@{
                        network = $network
                        subnetwork = $subnetwork
                    }) | ConvertTo-Json -Compress)
                    'run.googleapis.com/vpc-access-egress' = 'private-ranges-only'
                }
            }
            spec = [pscustomobject]@{
                parallelism = 1
                taskCount = 1
                template = [pscustomobject]@{ spec = $liveTask }
            }
        }
    }
}
function Invoke-GcloudJson { return $script:mockResponse }

$script:jobName = 'migration-job'
$script:projectId = 'project'
$script:region = 'region'
Assert-LiveJobMatchesPlan `
    -ExpectedJob $plannedJob `
    -ExpectedEnvironment $environment `
    -ExpectedServiceAccount $serviceAccount `
    -ExpectedImage $image `
    -ExpectedNetwork $network `
    -ExpectedSubnetwork $subnetwork

$plannedContainer.args = @('unapproved')
$overrideRejected = $false
try {
    Assert-LiveJobMatchesPlan `
        -ExpectedJob $plannedJob `
        -ExpectedEnvironment $environment `
        -ExpectedServiceAccount $serviceAccount `
        -ExpectedImage $image `
        -ExpectedNetwork $network `
        -ExpectedSubnetwork $subnetwork
}
catch { $overrideRejected = $true }
if (-not $overrideRejected) { throw 'A planned command override was not rejected.' }
$plannedContainer.args = $null

Write-Output 'Database migration runner regression tests passed.'
