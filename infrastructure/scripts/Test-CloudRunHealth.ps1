[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]$')]
    [string]$ProjectId,

    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z]+-[a-z]+[0-9]+$')]
    [string]$Region,

    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z][a-z0-9-]{0,61}[a-z0-9]$')]
    [string]$ServiceName,

    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$')]
    [string]$VerifierServiceAccount
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

function Resolve-GcloudCommand {
    $installed = Get-Command gcloud.cmd, gcloud -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($installed) { return $installed.Source }

    $workspaceInstall = Join-Path $repositoryRoot 'tools-runtime\google-cloud-sdk\bin\gcloud.cmd'
    if (Test-Path -LiteralPath $workspaceInstall -PathType Leaf) { return $workspaceInstall }

    throw 'Google Cloud CLI was not found in PATH or the ignored workspace tools-runtime directory.'
}

function Read-JwtAudience {
    param([Parameter(Mandatory)][string]$Token)

    $segments = $Token.Split('.')
    if ($segments.Count -ne 3) { throw 'The identity token is not a valid JSON Web Token.' }
    $payload = $segments[1].Replace('-', '+').Replace('_', '/')
    switch ($payload.Length % 4) {
        0 { }
        2 { $payload += '==' }
        3 { $payload += '=' }
        default { throw 'The identity token payload has invalid encoding.' }
    }
    try {
        return ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json).aud
    } catch {
        throw 'The identity token audience could not be verified.'
    }
}

$previousCloudSdkConfig = $env:CLOUDSDK_CONFIG
$injectedCloudSdkConfig = [string]::IsNullOrWhiteSpace($previousCloudSdkConfig)
$identityToken = $null
try {
    if ($injectedCloudSdkConfig) {
        $workspaceCloudSdkConfig = Join-Path $repositoryRoot 'secure-runtime\gcloud-config'
        if (-not (Test-Path -LiteralPath $workspaceCloudSdkConfig -PathType Container)) {
            throw 'CLOUDSDK_CONFIG must point to an approved non-system-drive configuration directory.'
        }
        $env:CLOUDSDK_CONFIG = $workspaceCloudSdkConfig
    }

    $gcloud = Resolve-GcloudCommand
    $serviceUrl = (& $gcloud run services describe $ServiceName "--project=$ProjectId" "--region=$Region" '--format=value(status.url)' --quiet)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($serviceUrl)) {
        throw 'Unable to resolve the Cloud Run service URL from the selected project and region.'
    }

    $parsedUrl = [Uri]$serviceUrl.Trim()
    if ($parsedUrl.Scheme -ne 'https' -or -not $parsedUrl.Host -or $parsedUrl.UserInfo -or $parsedUrl.Query -or $parsedUrl.Fragment) {
        throw 'Google Cloud returned an invalid Cloud Run service origin.'
    }
    if ($parsedUrl.AbsolutePath -notin @('', '/')) {
        throw 'Google Cloud returned a Cloud Run URL containing an unexpected path.'
    }
    $origin = $parsedUrl.GetLeftPart([UriPartial]::Authority)
    if (-not $VerifierServiceAccount.EndsWith("@$ProjectId.iam.gserviceaccount.com", [StringComparison]::OrdinalIgnoreCase)) {
        throw 'VerifierServiceAccount must belong to the selected project.'
    }

    $identityToken = (& $gcloud auth print-identity-token "--impersonate-service-account=$VerifierServiceAccount" "--audiences=$origin" --quiet)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityToken)) {
        throw 'Unable to acquire a short-lived identity token for the Cloud Run service.'
    }
    $audiences = @(Read-JwtAudience -Token $identityToken.Trim())
    if ($origin -notin $audiences) {
        throw 'The identity token audience does not match the resolved Cloud Run service.'
    }

    $headers = @{ Authorization = "Bearer $($identityToken.Trim())" }
    $response = Invoke-WebRequest -Uri "$origin/health" -Headers $headers -Method Get -TimeoutSec 20 -MaximumRedirection 0
    if ($response.StatusCode -ne 200) { throw "Health endpoint returned HTTP $($response.StatusCode)." }
    $body = $response.Content | ConvertFrom-Json
    if ($body.status -ne 'ok') { throw 'Health endpoint did not return the required status.' }
    $cacheControl = $response.Headers['Cache-Control'] -join ','
    $contentTypeOptions = $response.Headers['X-Content-Type-Options'] -join ','
    if ($cacheControl -notmatch '(^|,)\s*no-store\s*(,|$)') { throw 'Health response is missing Cache-Control: no-store.' }
    if ($contentTypeOptions -notmatch '(^|,)\s*nosniff\s*(,|$)') { throw 'Health response is missing X-Content-Type-Options: nosniff.' }

    Write-Host "Cloud Run health verification passed for $origin/health."
} finally {
    $identityToken = $null
    if ($injectedCloudSdkConfig) {
        Remove-Item Env:CLOUDSDK_CONFIG -ErrorAction SilentlyContinue
    } else {
        $env:CLOUDSDK_CONFIG = $previousCloudSdkConfig
    }
}
