[CmdletBinding()]
param(
    [switch]$Tracked,
    [switch]$WorkingTree
)

$ErrorActionPreference = 'Stop'

if ($Tracked -and $WorkingTree) {
    throw 'Choose either -Tracked or -WorkingTree, not both.'
}

$staged = if ($Tracked) {
    @(git ls-files)
} elseif ($WorkingTree) {
    @(@(git diff --name-only HEAD --diff-filter=ACMR) + @(git ls-files --others --exclude-standard) | Sort-Object -Unique)
} else {
    @(git diff --cached --name-only --diff-filter=ACMR)
}
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to read the Git staging area.'
}
if ($staged.Count -eq 0) {
    throw "No $($(if ($Tracked) { 'tracked' } elseif ($WorkingTree) { 'working-tree' } else { 'staged' })) files were found."
}

$allowed = @(
    '^(\.gitignore|README\.md|SECURITY\.md)$',
    '^\.github/workflows/[^/]+\.ya?ml$',
    '^api/(CHANGELOG\.md|IOS_CONTRACT_NOTIFICATION_LOG\.md|IOS_REST_API_INTEGRATION_CHECKLIST\.md|README\.md)$',
    '^api/contract-tests/',
    '^api/openapi/elder-engage-v1\.openapi\.json$',
    '^api/postman/(Elder_Engage_Week2_Draft\.postman_collection\.json|README\.md)$',
    '^architecture/(Engagement_Deployment_Runbook_Draft|Engagement_Platform_Architecture_v1|Schema_REST_Permission_Mapping)\.md$',
    '^config/engagement/',
    '^database/(ENGAGEMENT_SCHEMA_NOTES\.md|engagement_platform_v1_schema\.sql)$',
    '^database/tests/(requirements\.lock|test_staff_role_concurrency\.py)$',
    '^infrastructure/',
    '^services/engagement-api/',
    '^tools/(check_public_repository\.ps1|generate_engagement_postman\.mjs|validate_engagement_config\.mjs|validate_engagement_openapi\.mjs|validate_engagement_schema\.mjs)$'
)

$forbiddenExtension = '(?i)\.(docx?|pdf|xlsx?|pptx?|apk|aab|jks|keystore|p12|pfx|pem|key|db|sqlite|sqlite3)$'
$contentRules = [ordered]@{
    'private key' = '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'
    'GitHub token' = 'gh[pousr]_[A-Za-z0-9]{20,}'
    'Google API key' = 'AIza[0-9A-Za-z_-]{30,}'
    'Amazon access key' = 'AKIA[0-9A-Z]{16}'
    'Slack token' = 'xox[baprs]-[A-Za-z0-9-]{10,}'
    'personal or client identity' = '(?i)Amit\s+Hazari|Abhisek|Bandhan\s+Bank|ANIT\s+BOSE'
    'local user path' = '(?i)[A-Z]:\\Users\\'
    'commercial amount' = '(?i)\u20B9|\bINR\b|\blakh\b|\bcrore\b|fixed\s+development\s+fee'
}

$failures = [System.Collections.Generic.List[string]]::new()
foreach ($path in $staged) {
    $normalized = $path -replace '\\', '/'
    if (-not ($allowed | Where-Object { $normalized -match $_ })) {
        $failures.Add("Path is outside the public allowlist: $normalized")
        continue
    }
    if ($normalized -match $forbiddenExtension) {
        $failures.Add("Binary or sensitive file type is forbidden: $normalized")
        continue
    }
    if ($normalized -eq 'tools/check_public_repository.ps1') {
        continue
    }

    $content = if ($WorkingTree) {
        Get-Content -LiteralPath (Join-Path (Get-Location) $normalized)
    } elseif ($Tracked) {
        git show "HEAD:$normalized"
    } else {
        git show ":$normalized"
    }
    if ($LASTEXITCODE -ne 0) {
        $failures.Add("Unable to inspect staged content: $normalized")
        continue
    }
    $text = $content -join "`n"
    foreach ($rule in $contentRules.GetEnumerator()) {
        if ($text -match $rule.Value) {
            $failures.Add("$($rule.Key) pattern found: $normalized")
        }
    }
}

if ($failures.Count -gt 0) {
    $failures | Sort-Object -Unique | ForEach-Object { Write-Error $_ }
    throw "Public repository check failed with $($failures.Count) finding(s)."
}

$source = if ($Tracked) { 'tracked' } elseif ($WorkingTree) { 'working-tree' } else { 'staged' }
Write-Host "Public repository check passed for $($staged.Count) $source file(s)."
