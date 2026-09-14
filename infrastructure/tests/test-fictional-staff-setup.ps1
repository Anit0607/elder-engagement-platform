#requires -Version 7.0
$ErrorActionPreference='Stop'
$source=Join-Path $PSScriptRoot '..\scripts\Invoke-FictionalStaffSetup.ps1'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Resolve-Path $source),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Setup script does not parse.' }
foreach ($name in @('Assert-SetupPlan','Assert-SetupJob','Read-SetupBackupTime','Assert-SetupCompletion')) {
    $definition=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true))
    if ($definition.Count -ne 1) {throw 'Missing pure setup helper.'}
    . ([scriptblock]::Create($definition[0].Extent.Text))
}
$script:cases=0
function Must-Reject {param([scriptblock]$Test) $failed=$false; try {& $Test} catch {$failed=$true}; if (-not $failed) {throw 'Unsafe fixture was accepted.'}; $script:cases++}
function Clone {param($Value) return ($Value | ConvertTo-Json -Depth 100 | ConvertFrom-Json -Depth 100)}
$project='example-development-project'; $region='asia-south1'; $revision='a'*40; $image='synthetic-image@sha256:'+('b'*64)
$envs=@(@{name='SOURCE_REVISION';value=$revision},@{name='STAFF_SETUP_MODE';value='fictional-development'},
    @{name='AMIKO_FICTIONAL_STAFF_SETUP_INPUT';valueSource=@{secretKeyRef=@{secret='synthetic-private-input';version='1'}}})
$wantedEnv=@(@{name='SOURCE_REVISION';value=$revision;value_source=@()},
    @{name='STAFF_SETUP_MODE';value='fictional-development';value_source=@()},
    @{name='AMIKO_FICTIONAL_STAFF_SETUP_INPUT';value=$null;value_source=@(@{secret_key_ref=@(@{secret='synthetic-private-input';version='1'})})})
$container=@{image=$image;command=@('python');args=@('-m','app.development_staff_setup');env=$envs;resources=@{limits=@{cpu='1';memory='512Mi'}}}
$task=@{maxRetries=0;timeout='300s';executionEnvironment='EXECUTION_ENVIRONMENT_GEN2';serviceAccount="ee-development-runtime@$project.iam.gserviceaccount.com";containers=@($container);
    vpcAccess=@{egress='PRIVATE_RANGES_ONLY';networkInterfaces=@(@{network="projects/$project/global/networks/ee-development-network";subnetwork="projects/$project/regions/$region/subnetworks/ee-development-serverless"})}}
$live=Clone @{name="projects/$project/locations/$region/jobs/ee-development-fictional-staff-setup";template=@{taskCount=1;parallelism=1;template=$task}}
$job=@{template=@(@{template=@(@{containers=@(@{image=$image;env=$wantedEnv})})})}
Assert-SetupJob $live $job $project $region $image $revision
$script:cases++
$short=Clone $live
$short.template.template.vpcAccess.networkInterfaces[0].network='ee-development-network'
$short.template.template.vpcAccess.networkInterfaces[0].subnetwork='ee-development-serverless'
Assert-SetupJob $short $job $project $region $image $revision
$script:cases++
$bad=Clone $live; $bad.template.template.vpcAccess.networkInterfaces[0].network="projects/other-project/global/networks/ee-development-network"
Must-Reject {Assert-SetupJob $bad $job $project $region $image $revision}
$bad=Clone $live; $bad.template.template.vpcAccess.networkInterfaces[0].subnetwork="projects/$project/regions/other-region/subnetworks/ee-development-serverless"
Must-Reject {Assert-SetupJob $bad $job $project $region $image $revision}
foreach ($field in @('maxRetries','timeout','executionEnvironment','serviceAccount')) {
    $bad=Clone $live; $bad.template.template.$field='unexpected'
    Must-Reject {Assert-SetupJob $bad $job $project $region $image $revision}
}
foreach ($field in @('parallelism','taskCount')) {
    $bad=Clone $live; $bad.template.$field=2
    Must-Reject {Assert-SetupJob $bad $job $project $region $image $revision}
}
foreach ($field in @('image','command','args')) {
    $bad=Clone $live; $bad.template.template.containers[0].$field=@('unexpected')
    Must-Reject {Assert-SetupJob $bad $job $project $region $image $revision}
}
foreach ($field in @('cpu','memory')) {
    $bad=Clone $live; $bad.template.template.containers[0].resources.limits.$field='unexpected'
    Must-Reject {Assert-SetupJob $bad $job $project $region $image $revision}
}
$bad=Clone $live; $bad.template.template.vpcAccess.egress='ALL_TRAFFIC'
Must-Reject {Assert-SetupJob $bad $job $project $region $image $revision}
foreach ($field in @('network','subnetwork')) {
    $bad=Clone $live; $bad.template.template.vpcAccess.networkInterfaces[0].$field='unexpected'
    Must-Reject {Assert-SetupJob $bad $job $project $region $image $revision}
}
$bad=Clone $live; $bad.template.template.containers[0].env[0].value='c'*40
Must-Reject {Assert-SetupJob $bad $job $project $region $image $revision}
$bad=Clone $live; $bad.template.template.containers[0].env[2].valueSource.secretKeyRef.version='latest'
Must-Reject {Assert-SetupJob $bad $job $project $region $image $revision}
$bad=Clone $live; $bad.template.template.containers[0].env+= $bad.template.template.containers[0].env[0]
Must-Reject {Assert-SetupJob $bad $job $project $region $image $revision}
$plan=Clone @{resource_changes=@(@{address='google_cloud_run_v2_job.fictional_staff_setup[0]';change=@{actions=@('create');after=$job}});output_changes=@{}}
$null=Assert-SetupPlan $plan $image $revision; $script:cases++
foreach ($action in @('update','delete')) {
    $bad=Clone $plan; $bad.resource_changes[0].change.actions=@($action)
    Must-Reject {Assert-SetupPlan $bad $image $revision}
}
$bad=Clone $plan; $bad.resource_changes[0].address='google_cloud_run_v2_service.api[0]'
Must-Reject {Assert-SetupPlan $bad $image $revision}
$bad=Clone $plan; $bad.resource_changes+=$bad.resource_changes[0]
Must-Reject {Assert-SetupPlan $bad $image $revision}
$utc=[DateTime]::SpecifyKind([DateTime]::Parse('2026-09-15T03:00:00'),[DateTimeKind]::Utc)
foreach ($value in @($utc,[DateTimeOffset]::Parse('2026-09-15T08:30:00+05:30'),'2026-09-15T03:00:00Z')) {
    if ((Read-SetupBackupTime $value) -ne [DateTimeOffset]::Parse('2026-09-15T03:00:00Z')) {throw 'Backup UTC was lost.'}; $script:cases++
}
Must-Reject {Read-SetupBackupTime '2026-09-15T03:00:00'}
Must-Reject {Read-SetupBackupTime ([DateTime]::SpecifyKind($utc,[DateTimeKind]::Unspecified))}
$execution='ee-development-fictional-staff-setup-unit'
$record=@{status='ok';fictional_only=$true;client_authenticator_acceptance=$false;public_route_enabled=$false;
    checks=@('fictional_administrator_enrolled_and_two_factor_login_verified','administrator_created_contributor_password_login_verified','contributor_cannot_create_staff','setup_test_sessions_signed_out')}
$entry=Clone @{labels=@{'run.googleapis.com/execution_name'=$execution};jsonPayload=$record}
Assert-SetupCompletion @($entry) $execution; $script:cases++
foreach ($field in @('status','fictional_only','client_authenticator_acceptance','public_route_enabled','checks')) {
    $bad=Clone $entry; $bad.jsonPayload.$field='unexpected'
    Must-Reject {Assert-SetupCompletion @($bad) $execution}
}
Must-Reject {Assert-SetupCompletion @($entry,$entry) $execution}
Must-Reject {Assert-SetupCompletion @($entry) 'another-execution'}
$text=Get-Content -LiteralPath $source -Raw
foreach ($pattern in @("'CreateNew'",'Flush\(\$true\)','backupRuns/\$BackupId','@\(\$history.executions','Never restart|never restart','Assert-SetupJob \$executedJob')) {
    if ($text -notmatch $pattern) {throw 'Execution safeguard missing.'}; $script:cases++
}
Write-Host "Fictional staff setup safeguards passed: $script:cases cases; no cloud access or mutation."
