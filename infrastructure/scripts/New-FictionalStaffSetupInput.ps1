#requires -Version 7.0
# Generate runtime credentials privately. No values are accepted on a command
# line, printed, committed or sent to a remote QR-code service.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ($root -notmatch '^[Dd]:\\') {throw 'Generate project credentials on D only.'}
$directory=Join-Path $root 'secure-runtime\fictional-staff-private'
if (Test-Path $directory) {throw 'Private staff input already exists. Do not replace or rotate it blindly.'}
New-Item -ItemType Directory -Path $directory | Out-Null
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().User
$acl=[Security.AccessControl.DirectorySecurity]::new()
$acl.SetOwner($identity)
$acl.SetAccessRuleProtection($true,$false)
foreach ($sid in @($identity,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))) {
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
}
Set-Acl -LiteralPath $directory -AclObject $acl
$python=Join-Path $root 'services\engagement-api\.venv\Scripts\python.exe'
$oldCache=$env:PYTHONPYCACHEPREFIX
$env:PYTHONPYCACHEPREFIX=Join-Path $root 'tools-runtime\python-pycache'
try {
    $generated=& $python -c 'import base64,json,secrets; print(json.dumps(dict(administrator_password=secrets.token_urlsafe(32), contributor_password=secrets.token_urlsafe(32), administrator_seed=base64.b32encode(secrets.token_bytes(20)).decode(), encryption_key=base64.b64encode(secrets.token_bytes(32)).decode())))' 2>$null
    if ($LASTEXITCODE -ne 0) {throw 'Private credential generation failed.'}
    $staffPrivateValues=$generated | ConvertFrom-Json
    $payload=@{administrator_password=$staffPrivateValues.administrator_password;contributor_password=$staffPrivateValues.contributor_password;administrator_seed=$staffPrivateValues.administrator_seed} | ConvertTo-Json -Compress
    $html=@"
<!doctype html><html lang="en"><meta charset="utf-8"><title>Private fictional Amiko staff test</title>
<style>body{font:18px system-ui;max-width:850px;margin:40px auto;padding:24px;background:#f3f6fb;color:#142a43}section{background:white;padding:20px;margin:18px 0;border-radius:12px}code{display:block;overflow-wrap:anywhere;padding:12px;background:#edf2f8}h1{font-size:28px}.warning{color:#9c241a}button{padding:10px}</style>
<h1>Private fictional Amiko staff test</h1><p class="warning">Keep this page private. Never upload it, share a screenshot, or put these values in chat or GitHub. These are development test accounts, not client production accounts.</p>
<section><h2>Administrator</h2><p>User name</p><code>fictional.ee010.administrator</code><p>Password</p><code>$($staffPrivateValues.administrator_password)</code>
<p>In your authenticator app, add a time-based account named <strong>Amiko fictional Administrator</strong>, using this setup key:</p><code>$($staffPrivateValues.administrator_seed)</code><p>The app will show a changing six-digit code. Do not share that code in chat. I will guide you through the test after cloud setup is verified.</p></section>
<section><h2>Contributor</h2><p>User name</p><code>fictional.ee010.contributor</code><p>Password</p><code>$($staffPrivateValues.contributor_password)</code><p>No authenticator code is needed for this Contributor test.</p></section>
<p>Generated locally on D. This page loads no remote scripts, images or services. Creating this file does not create cloud accounts or count as a passed client test.</p></html>
"@
    foreach ($entry in @(@{name='setup-input.json';value=$payload},@{name='staff-authenticator-key.base64';value=$staffPrivateValues.encryption_key},@{name='private-staff-test.html';value=$html})) {
        $file=Join-Path $directory $entry.name
        & git -C $root check-ignore --quiet $file
        if ($LASTEXITCODE -ne 0) {throw 'Private generated files must be excluded from Git.'}
        $handle=[IO.File]::Open($file,'CreateNew','Write','None')
        try {$bytes=[Text.Encoding]::UTF8.GetBytes($entry.value);$handle.Write($bytes);$handle.Flush($true)} finally {$handle.Dispose()}
    }
    Write-Host 'Private fictional inputs generated on D with restricted access and Git exclusion. No credentials printed; no cloud accounts created.'
} finally {$env:PYTHONPYCACHEPREFIX=$oldCache;$generated=$null;$staffPrivateValues=$null;$payload=$null;$html=$null}
