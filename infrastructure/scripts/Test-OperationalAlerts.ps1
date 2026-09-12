#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]$')]
    [string]$ProjectId,

    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z]+-[a-z]+[0-9]+$')]
    [string]$Region,

    [string]$ServiceName = 'ee-development-api',

    [Parameter(Mandatory)]
    [ValidateSet('TEST-EE-007-development')]
    [string]$ConfirmTest
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$gcloud = Join-Path $repositoryRoot 'tools-runtime\google-cloud-sdk\bin\gcloud.cmd'
$workspaceConfig = Join-Path $repositoryRoot 'secure-runtime\gcloud-config'

if (-not (Test-Path -LiteralPath $gcloud -PathType Leaf)) {
    throw 'The approved D-drive Google Cloud command-line tools were not found.'
}
if (-not (Test-Path -LiteralPath $workspaceConfig -PathType Container)) {
    throw 'The protected D-drive Google Cloud login was not found.'
}

$previousCloudSdkConfig = $env:CLOUDSDK_CONFIG
$env:CLOUDSDK_CONFIG = $workspaceConfig

function Invoke-GcloudJson {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & $gcloud @Arguments '--format=json' 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Google Cloud command failed: gcloud $($Arguments -join ' ')"
    }
    return ($output | ConvertFrom-Json)
}

try {
    $service = Invoke-GcloudJson -Arguments @(
        'run', 'services', 'describe', $ServiceName,
        "--project=$ProjectId", "--region=$Region"
    )
    if ([string]$service.metadata.name -cne $ServiceName) {
        throw 'The requested Cloud Run service was not found.'
    }

    $revisionName = [string]$service.status.latestReadyRevisionName
    if ([string]::IsNullOrWhiteSpace($revisionName)) {
        throw 'Cloud Run has no ready revision to use for the alert test.'
    }

    $policies = @(Invoke-GcloudJson -Arguments @(
        'monitoring', 'policies', 'list', "--project=$ProjectId"
    ))
    $expectedPolicyNames = @(
        'ee-development-api-error-log',
        'ee-development-api-unavailable'
    )
    foreach ($policyName in $expectedPolicyNames) {
        $matchingPolicies = @($policies | Where-Object { $_.displayName -ceq $policyName })
        if ($matchingPolicies.Count -ne 1) {
            throw "Expected exactly one enabled monitoring policy named $policyName."
        }
        if (-not [bool]$matchingPolicies[0].enabled) {
            throw "Monitoring policy $policyName is disabled."
        }
        if (@($matchingPolicies[0].notificationChannels).Count -lt 1) {
            throw "Monitoring policy $policyName has no client-approved notification recipient."
        }
    }

    $testId = [guid]::NewGuid().ToString('N')
    $payload = @{
        event   = 'EE007_NOTIFICATION_TEST'
        test_id = $testId
        message = 'Controlled Week 1 alert-delivery test; this is not a production failure.'
    } | ConvertTo-Json -Compress

    & $gcloud logging write 'ee-development-operations-test' $payload `
        '--payload-type=json' '--severity=ERROR' `
        '--monitored-resource-type=cloud_run_revision' `
        "--monitored-resource-labels=project_id=$ProjectId,service_name=$ServiceName,revision_name=$revisionName,location=$Region,configuration_name=$ServiceName" `
        "--project=$ProjectId" '--quiet' 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'The controlled test log could not be written.'
    }

    $filter = "resource.type=`"cloud_run_revision`" AND resource.labels.service_name=`"$ServiceName`" AND jsonPayload.event=`"EE007_NOTIFICATION_TEST`" AND jsonPayload.test_id=`"$testId`""
    $visible = $false
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        $entries = @(Invoke-GcloudJson -Arguments @(
            'logging', 'read', $filter,
            "--project=$ProjectId", '--limit=1', '--freshness=10m'
        ))
        if ($entries.Count -eq 1) {
            $visible = $true
            break
        }
        Start-Sleep -Seconds 5
    }
    if (-not $visible) {
        throw 'The controlled error was written but did not become visible in Cloud Logging within 30 seconds.'
    }

    Write-Host 'Controlled error is visible and both monitoring policies have a notification recipient.'
    Write-Host 'Ask the approved recipient to confirm that the test notification arrived before closing EE-007.'
}
finally {
    if ($null -eq $previousCloudSdkConfig) {
        Remove-Item Env:CLOUDSDK_CONFIG -ErrorAction SilentlyContinue
    }
    else {
        $env:CLOUDSDK_CONFIG = $previousCloudSdkConfig
    }
}
