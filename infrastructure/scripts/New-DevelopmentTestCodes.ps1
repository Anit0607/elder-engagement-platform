[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]$')][string]$ProjectId,
    [Parameter(Mandatory)][string]$VarFile,
    [Parameter(Mandatory)][ValidateSet('ROTATE-development-test-codes')][string]$Confirm
)

$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$taskPath = (Resolve-Path -LiteralPath $VarFile).Path
if (-not $taskRoot.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Generated credential inputs must remain on the approved D drive.'
}
if (-not $taskPath.StartsWith($taskRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Credential input must remain inside the approved D-drive workspace.'
}
$taskRelative = [IO.Path]::GetRelativePath($taskRoot, $taskPath).Replace('\', '/')
if ($taskRelative.StartsWith('../') -or $taskRelative -eq '..' -or
    -not $taskPath.EndsWith('.tfvars', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Use an ignored tfvars input inside this workspace.'
}
& git -C $taskRoot check-ignore --quiet -- $taskRelative
if ($LASTEXITCODE -ne 0) { throw 'Credential input must be Git-ignored.' }
& git -C $taskRoot ls-files --error-unmatch -- $taskRelative 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { throw 'Credential input must not be Git-tracked.' }

$taskContent = [IO.File]::ReadAllText($taskPath)
if ($taskContent -notmatch '(?m)^\s*environment\s*=\s*"development"\s*$' -or
    $taskContent -notmatch ('(?m)^\s*project_id\s*=\s*"' + [regex]::Escape($ProjectId) + '"\s*$')) {
    throw 'Only the matching approved development project may be changed.'
}
$taskPattern = '(?ms)^identity_test_phone_numbers\s*=\s*\{(?<body>.*?)^\}'
$taskBlocks = [regex]::Matches($taskContent, $taskPattern)
if ($taskBlocks.Count -ne 1) { throw 'Exactly one existing test-number map is required.' }
$taskBody = $taskBlocks[0].Groups['body'].Value
$taskPairPattern = '"(?<phone>\+91[0-9]{10})"\s*=\s*"(?<code>[0-9]{6})"'
$taskPairs = [regex]::Matches($taskBody, $taskPairPattern)
if ($taskPairs.Count -lt 1 -or $taskPairs.Count -gt 10 -or
    [regex]::Replace($taskBody, $taskPairPattern, '').Trim().Length -ne 0) {
    throw 'Existing development map must contain only approved India test-number/code pairs.'
}
$taskUsed = [Collections.Generic.HashSet[string]]::new()
foreach ($taskPair in $taskPairs) { [void]$taskUsed.Add($taskPair.Groups['code'].Value) }
$taskLines = foreach ($taskPair in $taskPairs) {
    do {
        $taskNewCode = [Security.Cryptography.RandomNumberGenerator]::GetInt32(100000, 1000000).ToString()
    } while ($taskUsed.Contains($taskNewCode) -or $taskNewCode -match '^([0-9])\1{5}$')
    [void]$taskUsed.Add($taskNewCode)
    '  "' + $taskPair.Groups['phone'].Value + '" = "' + $taskNewCode + '"'
}
$taskReplacement = "identity_test_phone_numbers = {`r`n" + ($taskLines -join "`r`n") + "`r`n}"
$taskUpdated = $taskContent.Substring(0, $taskBlocks[0].Index) + $taskReplacement +
    $taskContent.Substring($taskBlocks[0].Index + $taskBlocks[0].Length)
# Generated credential configuration: never send values to the terminal or public repository.
# This updates only the ignored runtime input; use a reviewed saved Terraform plan to apply it.
[IO.File]::WriteAllText($taskPath, $taskUpdated, [Text.UTF8Encoding]::new($false))
Write-Output "Generated replacement codes for $($taskPairs.Count) existing fictional identities. Values remain private. Cloud configuration has not been applied."
