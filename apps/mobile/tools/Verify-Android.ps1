[CmdletBinding()]
param([switch]$BuildPackage, [switch]$ClientTestPackage)

$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
if (-not $taskRoot.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The Amiko local build is configured to keep tools and caches on D:.'
}
$taskNames = @('NPM_CONFIG_CACHE', 'TEMP', 'TMP', 'JAVA_HOME', 'ANDROID_HOME',
    'ANDROID_SDK_ROOT', 'ANDROID_USER_HOME', 'GRADLE_USER_HOME', 'JAVA_TOOL_OPTIONS')
$taskPrevious = @{}
foreach ($taskName in $taskNames) {
    $taskPrevious[$taskName] = [Environment]::GetEnvironmentVariable($taskName)
}
try {
    $env:NPM_CONFIG_CACHE = Join-Path $taskRoot 'tools-runtime\npm-cache'
    $env:TEMP = Join-Path $taskRoot 'tools-runtime\temp'
    $env:TMP = $env:TEMP
    New-Item -ItemType Directory -Force -Path $env:NPM_CONFIG_CACHE, $env:TEMP | Out-Null

    $taskApp = Join-Path $taskRoot 'apps\mobile'
    Push-Location $taskApp
    try {
        & npm.cmd 'test' '--' '--runInBand'
        if ($LASTEXITCODE -ne 0) { throw 'Android screen tests failed.' }
        & npx.cmd 'tsc' '--noEmit'
        if ($LASTEXITCODE -ne 0) { throw 'Android type check failed.' }
        & npm.cmd 'run' 'lint'
        if ($LASTEXITCODE -ne 0) { throw 'Android lint failed.' }
        & npm.cmd 'audit' '--audit-level=moderate'
        if ($LASTEXITCODE -ne 0) { throw 'Android dependency audit failed.' }
    } finally { Pop-Location }

    if ($BuildPackage -or $ClientTestPackage) {
        $taskJdk = @(Get-ChildItem (Join-Path $taskRoot 'tools-runtime\android-java') -Directory)
        if ($taskJdk.Count -ne 1) { throw 'Exactly one D-drive Android JDK is required.' }
        $env:JAVA_HOME = $taskJdk[0].FullName
        $env:ANDROID_HOME = Join-Path $taskRoot 'tools-runtime\android-sdk'
        $env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
        $env:ANDROID_USER_HOME = Join-Path $taskRoot 'secure-runtime\android-user'
        # Short alias prevents Windows' 260-character CMake/Ninja path limit.
        $taskCache = Join-Path $taskRoot 'tools-runtime\gradle-cache'
        $taskShortCache = Join-Path $taskRoot 'g'
        if (-not (Test-Path -LiteralPath $taskShortCache)) {
            New-Item -ItemType Directory -Force -Path $taskCache | Out-Null
            New-Item -ItemType Junction -Path $taskShortCache -Target $taskCache | Out-Null
        }
        $taskAlias = Get-Item -LiteralPath $taskShortCache -Force
        if ($taskAlias.LinkType -ne 'Junction' -or
            $taskAlias.Target -ne $taskCache) {
            throw 'D-drive Gradle cache alias is not the expected project junction.'
        }
        $env:GRADLE_USER_HOME = $taskShortCache
        $taskJavaUser = Join-Path $taskRoot 'secure-runtime\java-user'
        New-Item -ItemType Directory -Force -Path $env:ANDROID_USER_HOME,
            $env:GRADLE_USER_HOME, $taskJavaUser | Out-Null
        $env:JAVA_TOOL_OPTIONS = "-Duser.home=`"$taskJavaUser`" -Djava.io.tmpdir=`"$env:TEMP`""
        Push-Location (Join-Path $taskApp 'android')
        try {
            $taskVariant = if ($ClientTestPackage) { ':app:assembleClientTest' } else { ':app:assembleDebug' }
            & .\gradlew.bat $taskVariant '--no-daemon'
            if ($LASTEXITCODE -ne 0) { throw 'Android package build failed.' }
        } finally { Pop-Location }
    }
} finally {
    foreach ($taskName in $taskNames) {
        [Environment]::SetEnvironmentVariable($taskName, $taskPrevious[$taskName])
    }
}
