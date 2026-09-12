[CmdletBinding()]
param([Parameter(Mandatory)][ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]$')][string]$ProjectId)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
if (-not $taskRoot.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'D-drive workspace required.' }
$taskOldConfig = $env:CLOUDSDK_CONFIG
try {
    $env:CLOUDSDK_CONFIG = Join-Path $taskRoot 'secure-runtime\gcloud-config'
    $taskToken = (& (Join-Path $taskRoot 'tools-runtime\google-cloud-sdk\bin\gcloud.cmd') auth print-access-token --quiet)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($taskToken)) { throw 'Cloud authentication unavailable.' }
    $taskHeaders = @{Authorization="Bearer $taskToken"; 'x-goog-user-project'=$ProjectId}
    $taskApps = Invoke-RestMethod "https://firebase.googleapis.com/v1beta1/projects/$ProjectId/androidApps" `
        -Headers $taskHeaders
    $taskApp = @($taskApps.apps | Where-Object {
        $_.packageName -eq 'com.eldercaresaathi.amiko' -and $_.state -eq 'ACTIVE'
    })
    if ($taskApp.Count -ne 1) { throw 'Exactly one active approved Android registration is required.' }
    $taskKeys = @(@(
        (Join-Path $taskRoot 'secure-runtime\android-user\debug.keystore'),
        (Join-Path $taskRoot 'secure-runtime\java-user\.android\debug.keystore')
    ) | Where-Object { Test-Path -LiteralPath $_ })
    if (@($taskKeys).Count -ne 1) { throw 'Build the D-drive debug app first; exactly one debug keystore is required.' }
    $taskJdk = @(Get-ChildItem (Join-Path $taskRoot 'tools-runtime\android-java') -Directory)
    if ($taskJdk.Count -ne 1) { throw 'Exactly one approved D-drive JDK is required.' }
    # Android's standard generated debug-keystore password is public, not a client/production secret.
    $taskCertificate = (& (Join-Path $taskJdk[0].FullName 'bin\keytool.exe') '-J-Duser.language=en' `
        '-J-Duser.country=US' '-list' '-v' '-keystore' $taskKeys[0] '-storepass' 'android' 2>$null) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the debug public certificate.' }
    $taskExisting = Invoke-RestMethod "https://firebase.googleapis.com/v1beta1/$($taskApp[0].name)/sha" `
        -Headers $taskHeaders
    foreach ($taskItem in @(@{label='SHA1';type='SHA_1'}, @{label='SHA256';type='SHA_256'})) {
        $taskMatch = [regex]::Match($taskCertificate, "$($taskItem.label):\s*([A-Fa-f0-9:]+)")
        if (-not $taskMatch.Success) { throw 'Public signing fingerprint unavailable.' }
        $taskHash = $taskMatch.Groups[1].Value.Replace(':','').ToUpperInvariant()
        $taskFound = @($taskExisting.certificates | Where-Object {
            $_.certType -eq $taskItem.type -and $_.shaHash.Replace(':','').ToUpperInvariant() -eq $taskHash
        })
        if ($taskFound.Count -eq 0) {
            $taskBody = @{shaHash=$taskHash;certType=$taskItem.type} | ConvertTo-Json -Compress
            Invoke-RestMethod -Method Post "https://firebase.googleapis.com/v1beta1/$($taskApp[0].name)/sha" `
                -Headers $taskHeaders -ContentType 'application/json' -Body $taskBody | Out-Null
        }
    }
    Write-Output 'Both public debug signing fingerprints are registered with the approved Google Android app.'
} finally {
    $env:CLOUDSDK_CONFIG = $taskOldConfig
    $taskToken = $null
}
