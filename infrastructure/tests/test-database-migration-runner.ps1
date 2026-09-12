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
    'Assert-ExactEnvironmentMap',
    'Assert-ExactPropertyNames',
    'Assert-LiveJobMatchesPlan',
    'Assert-EffectiveRunPermission'
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

function Start-Sleep { param([int]$Seconds) }
$principal = 'user:operator@example.invalid'
$script:mockResponse = [pscustomobject]@{
    fullyExplored = $true
    mainAnalysis = [pscustomobject]@{
        fullyExplored = $true
        nonCriticalErrors = @()
        analysisResults = @()
    }
}
Assert-EffectiveRunPermission -RequireNoPrincipal
$emptyExactRejected = $false
try {
    Assert-EffectiveRunPermission -OnlyAllowedPrincipal $principal -RequireAllowedPrincipal
}
catch { $emptyExactRejected = $true }
if (-not $emptyExactRejected) { throw 'An empty post-grant analysis was accepted.' }

$script:mockResponse.mainAnalysis.analysisResults = @([pscustomobject]@{
    identityList = [pscustomobject]@{
        identities = @([pscustomobject]@{ name = $principal })
    }
})
Assert-EffectiveRunPermission -OnlyAllowedPrincipal $principal -RequireAllowedPrincipal
$retainedPrincipalRejected = $false
try { Assert-EffectiveRunPermission -RequireNoPrincipal }
catch { $retainedPrincipalRejected = $true }
if (-not $retainedPrincipalRejected) { throw 'A retained effective principal was accepted.' }

Write-Output 'Database migration runner regression tests passed.'
