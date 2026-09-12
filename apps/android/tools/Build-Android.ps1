[CmdletBinding()]
param([switch]$ConnectedDevelopment)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
if (-not $taskRoot.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'This project requires D-drive tool and cache directories.'
}
$taskNames = @('JAVA_HOME', 'JAVA_TOOL_OPTIONS', 'ANDROID_HOME', 'ANDROID_USER_HOME', 'GRADLE_USER_HOME',
    'TEMP', 'TMP', 'AMIKO_FIREBASE_API_KEY', 'AMIKO_FIREBASE_APP_ID', 'AMIKO_FIREBASE_PROJECT', 'AMIKO_API_ORIGIN')
$taskPrevious = @{}
foreach ($taskName in $taskNames) { $taskPrevious[$taskName] = [Environment]::GetEnvironmentVariable($taskName) }
try {
    $taskJdk = @(Get-ChildItem (Join-Path $taskRoot 'tools-runtime\android-java') -Directory)
    if ($taskJdk.Count -ne 1) { throw 'Exactly one approved D-drive Android JDK installation is required.' }
    $env:JAVA_HOME = $taskJdk[0].FullName
    $env:ANDROID_HOME = Join-Path $taskRoot 'tools-runtime\android-sdk'
    $env:ANDROID_USER_HOME = Join-Path $taskRoot 'secure-runtime\android-user'
    $env:GRADLE_USER_HOME = Join-Path $taskRoot 'tools-runtime\gradle-cache'
    $env:TEMP = Join-Path $taskRoot 'tools-runtime\temp'
    $env:TMP = $env:TEMP
    $taskJavaUser = Join-Path $taskRoot 'secure-runtime\java-user'
    New-Item -ItemType Directory -Force -Path $env:ANDROID_USER_HOME, $env:GRADLE_USER_HOME, $env:TEMP,
        $taskJavaUser | Out-Null
    $env:JAVA_TOOL_OPTIONS = "-Duser.home=`"$taskJavaUser`" -Djava.io.tmpdir=`"$env:TEMP`""
    if ($ConnectedDevelopment) {
        $taskResponse = Get-Content (Join-Path $taskRoot 'secure-runtime\amiko-android-config-response.json') -Raw |
            ConvertFrom-Json
        $taskConfig = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($taskResponse.configFileContents)) |
            ConvertFrom-Json
        $taskClient = @($taskConfig.client | Where-Object {
            $_.client_info.android_client_info.package_name -eq 'com.eldercaresaathi.amiko'
        })
        if ($taskClient.Count -ne 1) { throw 'Downloaded Google configuration does not match the approved package.' }
        $env:AMIKO_FIREBASE_API_KEY = $taskClient[0].api_key[0].current_key
        $env:AMIKO_FIREBASE_APP_ID = $taskClient[0].client_info.mobilesdk_app_id
        $env:AMIKO_FIREBASE_PROJECT = $taskConfig.project_info.project_id
        $env:AMIKO_API_ORIGIN = 'http://127.0.0.1:8787'
        if (@($env:AMIKO_FIREBASE_API_KEY, $env:AMIKO_FIREBASE_APP_ID, $env:AMIKO_FIREBASE_PROJECT) |
            Where-Object { [string]::IsNullOrWhiteSpace($_) }) { throw 'Downloaded identity configuration is incomplete.' }
    }
    $taskGradle = Join-Path $taskRoot 'tools-runtime\gradle-8.13\bin\gradle.bat'
    & $taskGradle '-p' (Join-Path $taskRoot 'apps\android') '--no-daemon' '-Pkotlin.compiler.execution.strategy=in-process' `
        ':app:testDebugUnitTest' ':app:lintDebug' ':app:assembleDebug' `
        *> (Join-Path $taskRoot 'tracker-runtime\ee009-android-build.log')
    if ($LASTEXITCODE -ne 0) { throw 'Android build failed; diagnostic details remain in the private D-drive log.' }
    Write-Output 'Android compile, unit tests and lint passed. Debug APK is in apps/android/app/build/outputs/apk/debug.'
} finally {
    foreach ($taskName in $taskNames) {
        [Environment]::SetEnvironmentVariable($taskName, $taskPrevious[$taskName])
    }
}
