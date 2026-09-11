[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('development', 'staging', 'production')]
    [string]$Environment,

    [Parameter(Mandatory)]
    [string]$VarFile,

    [ValidateSet('Plan', 'Apply')]
    [string]$Action = 'Plan',

    [Parameter(Mandatory)]
    [string]$BackendConfig,

    [string]$PlanFile,

    [string]$ConfirmApply
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$foundationDirectory = Join-Path $repositoryRoot 'infrastructure\terraform\foundation'

function Resolve-IgnoredInputFile {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$Label
    )

    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $relative = [IO.Path]::GetRelativePath($repositoryRoot, $resolved).Replace('\', '/')
    if ($relative -eq '..' -or $relative.StartsWith('../')) {
        throw "$Label must stay inside the project workspace."
    }

    & git -C $repositoryRoot check-ignore --quiet -- $relative
    if ($LASTEXITCODE -ne 0) {
        throw "$Label must be excluded by .gitignore before it can be used."
    }

    & git -C $repositoryRoot ls-files --error-unmatch -- $relative 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        throw "$Label is Git-tracked and cannot contain environment-specific cloud values."
    }

    return $resolved
}

function Resolve-GcloudCommand {
    $installed = Get-Command gcloud.cmd, gcloud -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($installed) { return $installed.Source }

    $workspaceInstall = Join-Path $repositoryRoot 'tools-runtime\google-cloud-sdk\bin\gcloud.cmd'
    if (Test-Path -LiteralPath $workspaceInstall -PathType Leaf) { return $workspaceInstall }

    throw 'Google Cloud CLI was not found in PATH or the ignored workspace tools-runtime directory.'
}

$previousCloudSdkConfig = $env:CLOUDSDK_CONFIG
$injectedCloudSdkConfig = [string]::IsNullOrWhiteSpace($previousCloudSdkConfig)
if ($injectedCloudSdkConfig) {
    $workspaceCloudSdkConfig = Join-Path $repositoryRoot 'secure-runtime\gcloud-config'
    if (-not (Test-Path -LiteralPath $workspaceCloudSdkConfig -PathType Container)) {
        throw 'CLOUDSDK_CONFIG must point to an approved non-system-drive configuration directory.'
    }
    $env:CLOUDSDK_CONFIG = $workspaceCloudSdkConfig
}

$previousAccessToken = $env:GOOGLE_OAUTH_ACCESS_TOKEN
$injectedAccessToken = [string]::IsNullOrWhiteSpace($previousAccessToken)
if ($injectedAccessToken) {
    $gcloud = Resolve-GcloudCommand
    $accessToken = (& $gcloud auth print-access-token --quiet)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($accessToken)) {
        throw 'Unable to acquire an ephemeral access token from the authenticated Google Cloud CLI.'
    }
    $env:GOOGLE_OAUTH_ACCESS_TOKEN = $accessToken.Trim()
}

try {

$resolvedVarFile = Resolve-IgnoredInputFile -Path $VarFile -Label 'VarFile'

if ([IO.Path]::GetExtension($resolvedVarFile) -ne '.tfvars') {
    throw 'VarFile must be an ignored .tfvars file, not a committed example or JSON file.'
}

$terraform = Get-Command terraform -ErrorAction Stop
$terraformDirectoryArgument = "-chdir=$foundationDirectory"
& $terraform.Source $terraformDirectoryArgument fmt -check
if ($LASTEXITCODE -ne 0) { throw 'Terraform formatting check failed.' }

$resolvedBackend = Resolve-IgnoredInputFile -Path $BackendConfig -Label 'BackendConfig'
if (-not $resolvedBackend.EndsWith('.backend.hcl', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'BackendConfig must use the ignored .backend.hcl suffix.'
}
$initArguments = @($terraformDirectoryArgument, 'init', '-input=false', "-backend-config=$resolvedBackend")
& $terraform.Source @initArguments
if ($LASTEXITCODE -ne 0) { throw 'Terraform initialisation failed.' }

& $terraform.Source $terraformDirectoryArgument validate
if ($LASTEXITCODE -ne 0) { throw 'Terraform validation failed.' }

if ($Action -eq 'Plan') {
    $targetPlan = if ($PlanFile) { $PlanFile } else { Join-Path $repositoryRoot "tracker-runtime\terraform-$Environment.tfplan" }
    $planParent = Split-Path -Parent $targetPlan
    if ($planParent) { New-Item -ItemType Directory -Path $planParent -Force | Out-Null }
    & $terraform.Source $terraformDirectoryArgument plan -input=false -lock-timeout=5m "-var-file=$resolvedVarFile" "-out=$targetPlan"
    if ($LASTEXITCODE -ne 0) { throw 'Terraform plan failed.' }
    return
}

$requiredConfirmation = "APPLY-$Environment"
if ($ConfirmApply -cne $requiredConfirmation) {
    throw "Apply requires -ConfirmApply $requiredConfirmation."
}

if (-not $PlanFile) {
    throw 'Apply requires a reviewed saved plan through -PlanFile.'
}

$resolvedPlan = Resolve-IgnoredInputFile -Path $PlanFile -Label 'PlanFile'
& $terraform.Source $terraformDirectoryArgument apply -input=false $resolvedPlan
if ($LASTEXITCODE -ne 0) { throw 'Terraform apply failed.' }
} finally {
    if ($injectedAccessToken) {
        Remove-Item Env:GOOGLE_OAUTH_ACCESS_TOKEN -ErrorAction SilentlyContinue
    } else {
        $env:GOOGLE_OAUTH_ACCESS_TOKEN = $previousAccessToken
    }
    if ($injectedCloudSdkConfig) {
        Remove-Item Env:CLOUDSDK_CONFIG -ErrorAction SilentlyContinue
    } else {
        $env:CLOUDSDK_CONFIG = $previousCloudSdkConfig
    }
}
