#requires -Version 7.0
$ErrorActionPreference = 'Stop'
$script:jobAddress = 'google_cloud_run_v2_job.database_migration[0]'
$runnerPath = Join-Path $PSScriptRoot '..\scripts\Invoke-ProfilePhotoDatabaseUpdate.ps1'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($runnerPath, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw ($errors | Out-String) }
$baseline = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot '..\scripts\Invoke-DatabaseMigration.ps1'), [ref]$tokens, [ref]$errors
)
foreach ($name in @('Get-PlanEnvironmentMap', 'Test-ExecutionLogEntry', 'Get-ExecutionLogFilter')) {
    $definition = $baseline.FindAll({ param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true)
    . ([scriptblock]::Create($definition[0].Extent.Text))
}
foreach ($name in @('Assert-UpdatePlan', 'Assert-BackupRecord', 'Assert-SuccessRecord', 'Convert-EmptyJobDefaults',
    'Get-CompletionLogRequest', 'Assert-UpdateMarker')) {
    $definition = $ast.FindAll({ param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true)
    if ($definition.Count -ne 1) { throw "Expected one $name definition." }
    . ([scriptblock]::Create($definition[0].Extent.Text))
}
$script:cases = 0
function Expect-Rejected {
    param([scriptblock]$Check)
    $rejected = $false
    try { & $Check | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw 'A deliberately unsafe input was accepted.' }
    $script:cases++
}
function Copy-Object { param($Value) return ($Value | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100) }
$oldImage = 'registry.invalid/migration@sha256:' + ('a' * 64)
$newImage = 'registry.invalid/migration@sha256:' + ('b' * 64)
$oldRevision = 'c' * 40
$newRevision = 'd' * 40
$before = [pscustomobject]@{ template = @([pscustomobject]@{
    task_count = 1; parallelism = 1; template = @([pscustomobject]@{
        max_retries = 0; service_account = 'migration-identity'; timeout = '900s'
        containers = @([pscustomobject]@{ image = $oldImage; env = @(
            [pscustomobject]@{ name = 'SOURCE_REVISION'; value = $oldRevision },
            [pscustomobject]@{ name = 'DB_NAME'; value = 'engagement' }
        ) })
    })
}) }
$after = Copy-Object $before
$after.template[0].template[0].containers[0].image = $newImage
$after.template[0].template[0].containers[0].env[0].value = $newRevision
$plan = [pscustomobject]@{
    resource_changes = @([pscustomobject]@{ address = $script:jobAddress; change = [pscustomobject]@{
        actions = @('update'); before = $before; after = $after
    } })
    output_changes = [pscustomobject]@{}
}
function Check-Plan { param($Value)
    Assert-UpdatePlan -Plan $Value -Image $newImage -Revision $newRevision -PreviousImage $oldImage -PreviousRevision $oldRevision
}
$null = Check-Plan $plan
$cases++
${defaultJob} = Copy-Object $before
${defaultJob}.template[0] | Add-Member annotations ([pscustomobject]@{})
${defaultJob}.template[0] | Add-Member labels ([pscustomobject]@{})
${defaultJob}.template[0].template[0] | Add-Member encryption_key ''
${defaultJob}.template[0].template[0] | Add-Member gpu_zonal_redundancy_disabled $false
${defaultJob}.template[0].template[0].containers[0] | Add-Member working_dir ''
${defaultJob}.template[0].template[0].containers[0] | Add-Member name ''
${defaultJob}.template[0].template[0].containers[0] | Add-Member depends_on @()
${normalizedJob} = Convert-EmptyJobDefaults ${defaultJob}
if ($null -ne ${normalizedJob}.template[0].annotations -or $null -ne ${normalizedJob}.template[0].labels -or
    $null -ne ${normalizedJob}.template[0].template[0].encryption_key -or
    $null -ne ${normalizedJob}.template[0].template[0].gpu_zonal_redundancy_disabled -or
    $null -ne ${normalizedJob}.template[0].template[0].containers[0].working_dir -or
    $null -ne ${normalizedJob}.template[0].template[0].containers[0].name -or
    $null -ne ${normalizedJob}.template[0].template[0].containers[0].depends_on) { throw 'Empty defaults were not normalized.' }
if (${defaultJob}.template[0].template[0].containers[0].working_dir -cne '') { throw 'Normalization modified the input.' }
$cases++
${defaultJob}.template[0].template[0].containers[0].working_dir = '/unexpected'
${defaultJob}.template[0].template[0].containers[0].name = 'custom-container'
${defaultJob}.template[0].template[0].containers[0].depends_on = @('custom-container')
${defaultJob}.template[0].template[0].encryption_key = 'custom-key'
${defaultJob}.template[0].template[0].gpu_zonal_redundancy_disabled = $true
${defaultJob}.template[0].annotations = [pscustomobject]@{ unexpected = 'setting' }
${defaultJob}.template[0].labels = [pscustomobject]@{ unexpected = 'setting' }
${normalizedJob} = Convert-EmptyJobDefaults ${defaultJob}
if (${normalizedJob}.template[0].template[0].containers[0].working_dir -cne '/unexpected' -or
    ${normalizedJob}.template[0].template[0].containers[0].name -cne 'custom-container' -or
    ${normalizedJob}.template[0].template[0].containers[0].depends_on[0] -cne 'custom-container' -or
    ${normalizedJob}.template[0].template[0].encryption_key -cne 'custom-key' -or
    ${normalizedJob}.template[0].template[0].gpu_zonal_redundancy_disabled -ne $true -or
    ${normalizedJob}.template[0].annotations.unexpected -cne 'setting' -or
    ${normalizedJob}.template[0].labels.unexpected -cne 'setting') { throw 'A real override was hidden.' }
$cases++
foreach ($action in @('create', 'delete', 'delete,create')) {
    $bad = Copy-Object $plan
    $bad.resource_changes[0].change.actions = $action.Split(',')
    Expect-Rejected { Check-Plan $bad }
}
$bad = Copy-Object $plan
$bad.resource_changes[0].address = 'google_sql_database_instance.postgres'
Expect-Rejected { Check-Plan $bad }
$bad = Copy-Object $plan
$bad.resource_changes += Copy-Object $bad.resource_changes[0]
Expect-Rejected { Check-Plan $bad }
$bad = Copy-Object $plan
$bad.output_changes = [pscustomobject]@{ connection = [pscustomobject]@{ actions = @('update') } }
Expect-Rejected { Check-Plan $bad }
foreach ($field in @('max_retries', 'timeout', 'service_account')) {
    $bad = Copy-Object $plan
    $bad.resource_changes[0].change.after.template[0].template[0].$field = 'unexpected'
    Expect-Rejected { Check-Plan $bad }
}
$bad = Copy-Object $plan
$bad.resource_changes[0].change.after.template[0].template[0].containers[0].env[1].value = 'different_database'
Expect-Rejected { Check-Plan $bad }
foreach ($position in @('before', 'after')) {
    $bad = Copy-Object $plan
    $bad.resource_changes[0].change.$position.template[0].template[0].containers[0].image = 'wrong-image'
    Expect-Rejected { Check-Plan $bad }
    $bad = Copy-Object $plan
    $bad.resource_changes[0].change.$position.template[0].template[0].containers[0].env[0].value = 'wrong-source'
    Expect-Rejected { Check-Plan $bad }
}
$now = [datetimeoffset]'2026-09-14T18:00:00Z'
$backup = [pscustomobject]@{
    id = '123'; status = 'SUCCESSFUL'; type = 'ON_DEMAND'
    description = 'Pre-EE-013 profile photo table update'; endTime = '2026-09-14T17:30:00Z'
}
if ((Assert-BackupRecord @($backup) $now).id -cne '123') { throw 'A recent successful backup was not accepted.' }
$cases++
$typedBackup = Copy-Object $backup
$typedBackup.endTime = [datetime]::SpecifyKind([datetime]::new(2026, 9, 14, 17, 30, 0), [DateTimeKind]::Utc)
if ((Assert-BackupRecord @($typedBackup) $now).id -cne '123') { throw 'A UTC DateTime backup was not accepted.' }
$cases++
$typedBackup.endTime = $typedBackup.endTime.ToLocalTime()
if ((Assert-BackupRecord @($typedBackup) $now).id -cne '123') { throw 'A local DateTime lost its correct offset.' }
$cases++
$typedBackup.endTime = [datetimeoffset]'2026-09-14T23:00:00+05:30'
if ((Assert-BackupRecord @($typedBackup) $now).id -cne '123') { throw 'An offset DateTime backup was not accepted.' }
$cases++
$typedBackup.endTime = [datetime]::new(2026, 9, 14, 17, 30, 0)
Expect-Rejected { Assert-BackupRecord @($typedBackup) $now }
$typedBackup.endTime = '2026-09-14T17:30:00'
Expect-Rejected { Assert-BackupRecord @($typedBackup) $now }
foreach ($change in @(
    @{ field = 'status'; value = 'RUNNING' }, @{ field = 'status'; value = 'FAILED' },
    @{ field = 'type'; value = 'AUTOMATED' }, @{ field = 'description'; value = 'different-update' },
    @{ field = 'endTime'; value = '2026-09-14T13:59:59Z' },
    @{ field = 'endTime'; value = '2026-09-14T18:00:01Z' },
    @{ field = 'endTime'; value = 'not-a-date' }, @{ field = 'endTime'; value = $null }
)) {
    $bad = Copy-Object $backup
    $bad.($change.field) = $change.value
    Expect-Rejected { Assert-BackupRecord @($bad) $now }
}
Expect-Rejected { Assert-BackupRecord @() $now }
$entry = [pscustomobject]@{
    labels = [pscustomobject]@{ 'run.googleapis.com/execution_name' = 'migration-job-run1' }
    jsonPayload = [pscustomobject]@{ status = 'ok'; applied = @('V0005') }
}
Assert-SuccessRecord @($entry) 'migration-job-run1'
$cases++
Expect-Rejected { Assert-SuccessRecord @($entry) 'migration-job-run2' }
Expect-Rejected { Assert-SuccessRecord @($entry, $entry) 'migration-job-run1' }
$bad = Copy-Object $entry
$bad.jsonPayload.applied = @('V0004', 'V0005')
Expect-Rejected { Assert-SuccessRecord @($bad) 'migration-job-run1' }
$bad.jsonPayload.applied = @('V0004')
Expect-Rejected { Assert-SuccessRecord @($bad) 'migration-job-run1' }
$bad = Copy-Object $entry
$bad.jsonPayload.status = 'failed'
Expect-Rejected { Assert-SuccessRecord @($bad) 'migration-job-run1' }
$textEntry = [pscustomobject]@{ labels = $entry.labels; textPayload = ($entry.jsonPayload | ConvertTo-Json -Compress) }
Assert-SuccessRecord @($textEntry) 'migration-job-run1'
$cases++
$request = Get-CompletionLogRequest 'sample-project' 'asia-south1' 'migration-job' 'migration-job-run1'
$roundTrip = $request | ConvertTo-Json | ConvertFrom-Json
if ($roundTrip.resourceNames.Count -ne 1 -or $roundTrip.resourceNames[0] -cne 'projects/sample-project' -or
    $roundTrip.filter -cne 'resource.type="cloud_run_job" AND resource.labels.job_name="migration-job" AND resource.labels.location="asia-south1" AND labels."run.googleapis.com/execution_name"="migration-job-run1"' -or
    $roundTrip.pageSize -ne 100 -or $roundTrip.orderBy -cne 'timestamp desc') { throw 'Log request lost its exact scope or literal label key.' }
$cases++
Expect-Rejected { Get-CompletionLogRequest 'bad/project' 'asia-south1' 'migration-job' 'migration-job-run1' }
Expect-Rejected { Get-CompletionLogRequest 'sample-project' 'bad/region' 'migration-job' 'migration-job-run1' }
Expect-Rejected { Get-CompletionLogRequest 'sample-project' 'asia-south1' 'migration-job' 'another-job-run1' }
Expect-Rejected { Get-CompletionLogRequest 'sample-project' 'asia-south1' 'migration-job' 'migration-job-run1" OR severity>=ERROR' }
$marker = [pscustomobject]@{
    projectId = 'sample-project'; region = 'asia-south1'; jobName = 'migration-job'
    revision = 'e' * 40; migrationRevision = $newRevision; image = $newImage; planSha256 = 'f' * 64
    previousExecutions = @('migration-job-old1', 'migration-job-old2')
}
function Check-Marker { param($Value)
    Assert-UpdateMarker $Value 'sample-project' 'asia-south1' 'migration-job' $newRevision $newImage ('f' * 64)
}
if ((Check-Marker $marker) -cne ('e' * 40)) { throw 'The original controller revision was not retained.' }
$cases++
foreach ($field in @('projectId', 'region', 'jobName', 'revision', 'migrationRevision', 'image', 'planSha256', 'previousExecutions')) {
    $bad = Copy-Object $marker
    $bad.$field = 'different-release'
    Expect-Rejected { Check-Marker $bad }
}
Write-Output "Profile-photo update safeguards passed: $cases cases; no cloud access or mutation."

