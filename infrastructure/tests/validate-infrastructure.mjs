import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const foundation = join(root, 'terraform', 'foundation');
const files = readdirSync(foundation).filter((name) => name.endsWith('.tf'));
const source = files.map((name) => readFileSync(join(foundation, name), 'utf8')).join('\n');
const read = (relative) => readFileSync(join(root, relative), 'utf8');
const candidateWorkflow = readFileSync(
  resolve(root, '..', '.github', 'workflows', 'build-development-candidate.yml'),
  'utf8'
);
const deploymentWorkflow = readFileSync(
  resolve(root, '..', '.github', 'workflows', 'verify-development-deployment.yml'),
  'utf8'
);
const migrationWorkflow = readFileSync(
  resolve(root, '..', '.github', 'workflows', 'build-database-migration-candidate.yml'),
  'utf8'
);
const migrationDockerfile = readFileSync(
  resolve(root, '..', 'database', 'Dockerfile'),
  'utf8'
);
const operationalAlertTester = read('scripts/Test-OperationalAlerts.ps1');
const bootstrapTemplate = readFileSync(
  resolve(root, '..', 'database', 'bootstrap', 'V0001__establish_schema_ownership.sql.template'),
  'utf8'
);

assert.ok(files.length >= 8, 'foundation must be split into reviewable concerns');
const staffSetup = read('terraform/foundation/development_staff_setup.tf');
assert.match(source, /variable "prepare_development_staff_secrets"\s*\{[^}]*default\s*=\s*false/s, 'staff secret preparation must be opt-in');
assert.match(source, /variable "deploy_development_staff_setup_job"\s*\{[^}]*default\s*=\s*false/s, 'fictional setup deployment must be opt-in');
assert.match(staffSetup, /var\.environment == "development"/, 'fictional setup must reject production');
assert.match(staffSetup, /parallelism\s*=\s*1/, 'fictional setup must not run concurrently');
assert.match(staffSetup, /task_count\s*=\s*1/, 'fictional setup must have one task');
assert.match(staffSetup, /max_retries\s*=\s*0/, 'fictional setup must not retry uncertain execution');
assert.match(staffSetup, /PRIVATE_RANGES_ONLY/, 'fictional setup must use the private network');
assert.match(staffSetup, /args\s*=\s*\["-m", "app\.development_staff_setup"\]/, 'fictional setup must use the reviewed module');
assert.match(staffSetup, /STAFF_SETUP_MODE\s*=\s*"fictional-development"/, 'fictional setup must use its guarded mode');
assert.match(staffSetup, /AMIKO_FICTIONAL_STAFF_SETUP_INPUT[\s\S]*secret_key_ref/, 'private setup input must come from Secret Manager');
assert.match(staffSetup, /var\.development_staff_setup_input_version != null/, 'setup input version must be explicitly pinned');
assert.match(staffSetup, /var\.staff_authenticator_secret_version != null/, 'authenticator secret version must be explicitly pinned');
assert.match(staffSetup, /@sha256:\[0-9a-f\]\{64\}/, 'fictional setup must require an immutable image');
assert.doesNotMatch(staffSetup, /secret_data|allUsers|allAuthenticatedUsers|local-exec|gcloud|terraform apply/, 'setup resource definitions must not contain plaintext, public access or automatic execution');
assert.match(source, /backend\s+"gcs"/, 'remote Google Cloud Storage state is required');
assert.match(source, /disable_on_destroy\s*=\s*false/, 'required interfaces must survive ordinary destroy');
assert.match(source, /roles\/iam\.workloadIdentityUser/, 'GitHub must use Workload Identity Federation');
assert.match(source, /assertion\.repository\s*==/, 'federation must be restricted to one repository');
assert.match(source, /assertion\.repository_id\s*==/, 'federation must be restricted to an immutable repository identifier');
assert.match(source, /assertion\.repository_owner_id\s*==/, 'federation must be restricted to an immutable owner identifier');
assert.match(source, /assertion\.ref\s*==/, 'federation must be restricted to an approved Git ref');
assert.doesNotMatch(source, /service_account_key/, 'service-account JSON keys are prohibited');
assert.doesNotMatch(source, /google_secret_manager_secret_iam_member" "migration_database"/, 'keyless migration identity must not read a password connection secret');
assert.doesNotMatch(source, /roles\/run\.developer/, 'the federated GitHub identity must not be able to execute Cloud Run jobs');
assert.match(source, /roles\/run\.viewer/, 'the federated GitHub identity needs read-only Cloud Run discovery access');
assert.match(source, /google_service_account" "upload_signer"/, 'direct uploads require a separate signer identity');
assert.match(source, /roles\/storage\.objectCreator/, 'the upload signer must have create-only bucket access');
assert.doesNotMatch(source, /roles\/storage\.objectAdmin/, 'the application runtime must not receive broad media-bucket access');
assert.match(source, /public_access_prevention\s*=\s*"enforced"/);
assert.match(source, /uniform_bucket_level_access\s*=\s*true/);
assert.doesNotMatch(source, /authorized_networks\s*\{/, 'Cloud SQL must not have IP allowlists');
assert.match(source, /ipv4_enabled\s*=\s*false/, 'Cloud SQL must use private addressing');
assert.match(source, /ssl_mode\s*=\s*"ENCRYPTED_ONLY"/, 'Cloud SQL must require encrypted transport');
assert.match(source, /network_interfaces\s*\{/, 'Cloud Run must use Direct Virtual Private Cloud egress');
assert.doesNotMatch(source, /google_vpc_access_connector/, 'a chargeable serverless connector is not required');
assert.match(source, /deletion_protection\s*=\s*var\.environment\s*==\s*"production"/);
assert.match(source, /point_in_time_recovery_enabled\s*=\s*true/);
assert.match(source, /data_api_access\s*=\s*"DISALLOW_DATA_API"/, 'Cloud SQL Data API must be closed during normal operation');
assert.match(source, /edition\s*=\s*"ENTERPRISE"/, 'shared-core development SQL must explicitly use Enterprise edition');
assert.match(source, /google_billing_budget/, 'a project budget is mandatory');
assert.match(source, /google_monitoring_uptime_check_config" "api_health"/, 'the deployed API requires an uptime check');
assert.match(source, /service_agent_authentication\s*\{[\s\S]*?type\s*=\s*"OIDC_TOKEN"/m, 'the private API uptime check must authenticate');
assert.match(source, /monitored_resource\s*\{[\s\S]*?type\s*=\s*"cloud_run_revision"/m, 'authenticated uptime monitoring must target Cloud Run rather than an arbitrary URL');
const monitoringSource = read('terraform/foundation/monitoring.tf');
const privateHealthSource = monitoringSource.split('resource "google_cloud_run_v2_service_iam_member" "monitoring_uptime"')[0];
assert.match(monitoringSource, /revision_name\s*=\s*""/, 'Cloud Run uptime monitoring must use the API-normalised service-wide revision label');
assert.match(monitoringSource, /configuration_name\s*=\s*""/, 'Cloud Run uptime monitoring must use the API-normalised empty configuration label');
assert.doesNotMatch(monitoringSource, /latest_ready_revision|latest_created_revision/, 'app revisions must not force uptime-check replacement or inconsistent deployment plans');
assert.match(source, /google_monitoring_uptime_check_config" "api_health"\s*\{[\s\S]*?lifecycle\s*\{[\s\S]*?create_before_destroy\s*=\s*true/m, 'a replacement target health check must exist before the alert releases its predecessor');
assert.doesNotMatch(privateHealthSource, /validate_ssl\s*=/, 'Cloud Run managed-resource checks must not use the URL-only validate_ssl setting');
assert.match(source, /gcp-sa-monitoring-notification\.iam\.gserviceaccount\.com/, 'only the Google Monitoring service agent may invoke the private uptime check');
assert.match(source, /google_monitoring_uptime_check_config" "public_api_health"/, 'the activated protected hostname requires an external uptime check');
assert.match(monitoringSource, /type\s*=\s*"uptime_url"/, 'public monitoring must exercise the client-visible protected hostname');
assert.match(monitoringSource, /validate_ssl\s*=\s*true/, 'public monitoring must reject an invalid HTTPS certificate');
assert.match(source, /google_monitoring_alert_policy" "api_unavailable"/, 'API availability must have an alert policy');
assert.match(source, /REDUCE_COUNT_FALSE/, 'availability alerts must require failed checks');
assert.match(source, /google_monitoring_alert_policy" "api_error_log"/, 'Cloud Run error logs must have an alert policy');
assert.match(source, /severity>=ERROR/, 'the error alert must match error-or-higher log severity');
assert.match(source, /alert_notification_email/, 'alerts must support a client-approved recipient');
assert.doesNotMatch(source, /labels\s*=\s*\{[\s\S]*?email_address\s*=\s*"[^\"]+@/m, 'a real alert email must not be committed');
assert.match(operationalAlertTester, /TEST-EE-007-development/, 'the live notification test requires explicit confirmation');
assert.match(operationalAlertTester, /EE007_NOTIFICATION_TEST/, 'the notification test must use a recognisable synthetic event');
assert.match(operationalAlertTester, /notificationChannels/, 'the notification test must reject policies without a recipient');
assert.match(operationalAlertTester, /resource\.type=.*cloud_run_revision/, 'the synthetic event must match the protected Cloud Run error policy');
assert.match(operationalAlertTester, /Ask the approved recipient to confirm/, 'human receipt remains an explicit acceptance gate');
assert.doesNotMatch(operationalAlertTester, /@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/, 'the public notification test must not contain a real email address');
assert.match(source, /identitytoolkit\.googleapis\.com/, 'Google Identity Platform must be enabled through the reviewed cloud configuration');
assert.match(source, /google_identity_platform_config" "member_phone"/, 'Member phone sign-in must be managed as a repeatable cloud resource');
assert.match(source, /phone_number\s*\{[\s\S]*?enabled\s*=\s*true/m, 'the approved Member phone provider must be enabled');
assert.match(read('terraform/foundation/identity_platform.tf'),
  /email\s*\{\s*enabled\s*=\s*false\s*password_required\s*=\s*false\s*\}/m,
  'Member login must preserve explicit disabled-email defaults instead of repeatedly removing the provider block');
assert.match(source, /allowlist_only\s*\{[\s\S]*?allowed_regions\s*=\s*var\.identity_sms_allowed_regions/m, 'real sign-in messages must be restricted to approved regions');
assert.match(source, /identity_test_phone_numbers/, 'fictional phone identities must be supplied only as an environment input');
assert.match(source, /enable_member_session/, 'live Member session wiring must be opt-in');
assert.match(source, /secret_key_ref\s*\{/, 'session keys must be injected from Secret Manager');
assert.match(source, /AMIKO_SESSION_SIGNING_KEY_BASE64/, 'session signing material must use secure injection');
assert.match(source, /EE_DATABASE_IAM_USER/, 'Member login must use the dedicated runtime IAM database user');
assert.doesNotMatch(source, /test_phone_numbers\s*=\s*\{[\s\S]*?"\+[0-9]/m, 'fictional phone identities must not be committed to the public repository');
assert.match(source, /billing_project\s*=\s*var\.project_id/, 'user credential API quota must be charged to the selected project');
assert.match(source, /user_project_override\s*=\s*true/, 'Google provider must override the default user quota project');
assert.match(source, /projects\/\$\{data\.google_project\.current\.number\}/, 'budget must filter by immutable project number');
assert.match(source, /enable_project_level_recipients\s*=\s*true/, 'project owners must receive budget alerts');
assert.match(source, /0\.5,\s*0\.8,\s*1\.0/, 'budget thresholds must cover 50, 80 and 100 percent');
assert.match(source, /var\.deploy_application\s*\?\s*1\s*:\s*0/, 'application deployment must be opt-in');
assert.match(source, /@sha256:/, 'Cloud Run must require an immutable image digest');
assert.match(source, /startswith\(var\.container_image,\s*local\.approved_image_prefix\)/, 'Cloud Run must accept images only from the environment repository');
assert.match(source, /immutable_tags\s*=\s*true/, 'Artifact Registry tags must be immutable');
assert.match(source, /var\.environment\s*==\s*"development"/, 'the current health-service candidate must be development-only');
assert.match(source, /var\.public_api_origin/, 'Cloud Run must use an explicit assigned public origin');
assert.match(source, /bootstrap\.invalid/, 'private development bootstrap must use a non-routable placeholder origin');
const gatewaySource = read('terraform/foundation/public_gateway.tf');
assert.match(gatewaySource, /google_compute_global_address" "public_api"/, 'the protected API gateway requires a stable address for DNS');
assert.match(gatewaySource, /google_compute_region_network_endpoint_group" "public_api"/, 'the protected gateway must use a serverless Cloud Run endpoint');
assert.match(gatewaySource, /network_endpoint_type\s*=\s*"SERVERLESS"/, 'the public gateway endpoint must be serverless');
assert.match(gatewaySource, /google_compute_security_policy" "public_api"/, 'Cloud Armor must protect the public gateway');
assert.match(gatewaySource, /action\s*=\s*"rate_based_ban"/, 'the gateway must temporarily block traffic floods');
assert.match(gatewaySource, /rate_limit_threshold[\s\S]*?count\s*=\s*600[\s\S]*?interval_sec\s*=\s*60/m, 'the whole-API flood limit must remain reviewable and bounded');
assert.match(gatewaySource, /evaluatePreconfiguredWaf\('sqli-v33-stable'\)/, 'database-injection detection must be present');
assert.match(gatewaySource, /evaluatePreconfiguredWaf\('xss-v33-stable'\)/, 'browser-script attack detection must be present');
assert.match(gatewaySource, /preview\s*=\s*true/g, 'attack detection must begin in preview to measure false positives safely');
assert.match(gatewaySource, /google_compute_managed_ssl_certificate" "public_api"/, 'Google must manage HTTPS certificate renewal');
assert.match(gatewaySource, /google_compute_target_https_proxy" "public_api"/, 'the public entry point must use HTTPS');
assert.match(gatewaySource, /port_range\s*=\s*"443"/, 'the public entry point must accept only HTTPS');
assert.doesNotMatch(gatewaySource, /target_http_proxy|port_range\s*=\s*"80"/, 'unencrypted HTTP must not be exposed');
assert.match(source, /var\.activate_public_gateway\s*\?\s*"INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"\s*:\s*"INGRESS_TRAFFIC_ALL"/, 'activation must prevent bypassing Cloud Armor through the Cloud Run address');
assert.match(source, /!var\.allow_unauthenticated\s*\|\|\s*var\.activate_public_gateway/, 'direct unauthenticated Cloud Run access must be prohibited');
assert.match(source, /var\.deploy_application\s*&&\s*var\.activate_public_gateway\s*&&\s*var\.allow_unauthenticated/, 'public invoke permission must exist only after protected-gateway activation');
assert.match(source, /output "public_gateway_ip"/, 'the DNS manager needs the reserved address as a controlled output');
assert.match(source, /google_cloud_run_v2_service_iam_member" "github_verifier"/, 'the keyless verifier requires explicit Cloud Run invoke permission');
assert.match(source, /member\s*=\s*"serviceAccount:\$\{google_service_account\.github_deployer\.email\}"/, 'Cloud Run verification must use the existing federated service account');
assert.match(source, /startup_probe\s*\{[\s\S]*?tcp_socket\s*\{/m, 'Cloud Run must have a startup probe');
assert.match(source, /liveness_probe\s*\{[\s\S]*?http_get\s*\{[\s\S]*?path\s*=\s*"\/health"/m, 'Cloud Run liveness must call the HTTP health endpoint');
assert.match(source, /http_headers\s*\{[\s\S]*?name\s*=\s*"Host"[\s\S]*?value\s*=\s*local\.cloud_run_hostname/m, 'Cloud Run liveness must use the configured trusted host');
assert.doesNotMatch(source, /liveness_probe\s*\{[\s\S]*?tcp_socket\s*\{/m, 'Cloud Run does not support TCP liveness probes');
assert.match(source, /container_port\s*=\s*8080/, 'Cloud Run and the container must agree on port 8080');
assert.doesNotMatch(source, /cloudbuild\.googleapis\.com|google_cloudbuild_/, 'GitHub Actions is the approved builder; Cloud Build must not be enabled');
assert.doesNotMatch(source, /local-exec|\.sql["']/, 'infrastructure planning must not execute an application schema');
assert.match(source, /google_cloud_run_v2_job" "database_migration"/, 'database migrations require a controlled Cloud Run job');
assert.match(source, /var\.deploy_database_migration_job\s*\?\s*1\s*:\s*0/, 'the migration job must be disabled by default');
assert.match(source, /parallelism\s*=\s*1/, 'database migrations must not run parallel tasks');
assert.match(source, /task_count\s*=\s*1/, 'database migrations must use one task');
assert.match(source, /max_retries\s*=\s*0/, 'database migration failures must not retry automatically');
assert.match(source, /EXECUTION_ENVIRONMENT_GEN2/, 'the migration job must use the second-generation execution environment');
assert.match(source, /engagement-migration@sha256:/, 'the migration job must require its dedicated immutable image');
assert.doesNotMatch(source, /start_execution_token/, 'Terraform must never execute the migration job');
assert.doesNotMatch(source, /google_cloud_run_v2_job_iam/, 'no job invoker may be granted before execution approval');

const runner = read('scripts/Invoke-Infrastructure.ps1');
const healthVerifier = read('scripts/Test-CloudRunHealth.ps1');
const bootstrapRunner = read('scripts/Invoke-DatabaseBootstrap.ps1');
const migrationRunner = read('scripts/Invoke-DatabaseMigration.ps1');
assert.match(runner, /\[string\]\$Action\s*=\s*'Plan'/, 'runner must default to plan');
assert.match(runner, /APPLY-\$Environment/, 'apply must require an environment-specific confirmation');
assert.match(runner, /Apply requires a reviewed saved plan/, 'apply must consume a saved reviewed plan');
assert.match(runner, /check-ignore --quiet/, 'environment inputs and saved plans must be ignored by Git');
assert.match(runner, /GetRelativePath/, 'Git safety checks must use repository-relative paths');
assert.match(runner, /auth print-access-token --quiet/, 'the local runner must acquire an ephemeral Google Cloud access token');
assert.match(runner, /Remove-Item Env:GOOGLE_OAUTH_ACCESS_TOKEN/, 'the local runner must clear its injected access token');
assert.match(runner, /secure-runtime\\gcloud-config/, 'the local runner must prefer the ignored workspace Google Cloud configuration');
assert.match(runner, /Remove-Item Env:CLOUDSDK_CONFIG/, 'the local runner must restore its Google Cloud configuration environment');

assert.match(bootstrapRunner, /\[string\]\$Action\s*=\s*'Plan'/, 'database bootstrap must default to a read-only plan');
assert.match(bootstrapRunner, /BOOTSTRAP-EE-003-development/, 'database bootstrap apply must require an exact confirmation');
assert.match(bootstrapRunner, /CLEANUP-EE-003-development/, 'database bootstrap must provide an explicit emergency cleanup action');
assert.match(bootstrapRunner, /#requires -Version 7\.0/, 'database bootstrap must require PowerShell 7');
assert.match(bootstrapRunner, /deployment_project_id/, 'database bootstrap must bind its target to protected Terraform state');
assert.match(bootstrapRunner, /github_repository_slug/, 'database bootstrap must bind its repository to protected Terraform state');
assert.match(bootstrapRunner, /\^\(\?i:/, 'database bootstrap must anchor the approved repository address');
assert.ok(bootstrapRunner.indexOf('remote get-url origin') < bootstrapRunner.indexOf('fetch --quiet origin main'), 'repository identity must be checked before contacting origin');
assert.match(bootstrapRunner, /originRevision\s*-ne\s*\$ExpectedRevision/, 'database bootstrap must use the exact reviewed origin/main revision');
assert.match(bootstrapRunner, /secure-runtime/, 'temporary database material must stay in the protected runtime area');
assert.match(bootstrapRunner, /bootstrap-recovery/, 'database bootstrap must keep a protected recovery marker');
assert.match(bootstrapRunner, /\[IO\.FileShare\]::None/, 'bootstrap and cleanup must hold an exclusive process lock');
assert.ok(bootstrapRunner.indexOf('[IO.FileShare]::None') < bootstrapRunner.indexOf("'sql', 'instances', 'describe'"), 'the exclusive lock must be acquired before cloud preflight');
assert.match(bootstrapRunner, /\[IO\.FileMode\]::CreateNew/, 'the recovery marker must never overwrite an existing marker');
assert.doesNotMatch(bootstrapRunner, /Set-Content[^\n]+\$recoveryMarkerPath/, 'the recovery marker must not use an overwriting write operation');
assert.match(bootstrapRunner, /\$temporaryOperator\s*=\s*\[string\]\$marker\.operator/, 'cleanup must remove the exact operator recorded before interruption');
assert.match(bootstrapRunner, /\$recoveryMarkerCreatedThisRun\s*-and\s*-not\s*\$cloudMutationAttempted/, 'a newly created marker may be removed before any cloud mutation');
assert.match(bootstrapRunner, /\$dataApiClosureAttempted\s*-and\s*\$operatorClosureAttempted\s*-and\s*\$finalCleanupVerified/, 'an existing recovery marker must survive until both closures are attempted and verified');
assert.doesNotMatch(bootstrapRunner, /\$cleanupErrors\.Count\s*-eq\s*0\s*-and\s*\(Test-Path[^\n]+\$recoveryMarkerPath/, 'a Plan refusal must not delete an existing recovery marker merely because no cleanup error was recorded');
assert.match(bootstrapRunner, /status\s*-eq\s*'SUCCESSFUL'/, 'database bootstrap requires a successful backup');
assert.match(bootstrapRunner, /type\s*-eq\s*'ON_DEMAND'/, 'database bootstrap requires an on-demand backup');
assert.match(bootstrapRunner, /--type=CLOUD_IAM_USER/, 'bootstrap must use the named IAM operator without a password');
assert.match(bootstrapRunner, /--database-roles=cloudsqlsuperuser,\$MigrationRole/, 'the one-time operator roles must be explicit');
assert.match(bootstrapRunner, /--data-api-access=ALLOW_DATA_API/, 'bootstrap may open the authenticated Data API temporarily');
assert.match(bootstrapRunner, /--data-api-access=DISALLOW_DATA_API/, 'bootstrap must close the temporary Data API path');
assert.match(bootstrapRunner, /'sql', 'users', 'delete'/, 'bootstrap must remove the one-time database operator');
assert.match(bootstrapRunner, /--sql=@/, 'bootstrap must execute a reviewed SQL file instead of inline SQL');
assert.match(bootstrapRunner, /--partial-result-mode=FAIL_PARTIAL_RESULT/, 'bootstrap must reject incomplete results');
assert.match(bootstrapRunner, /Get-DatabaseStatusCode -Status \$Response\.status\) -ne 0/, 'bootstrap must reject a top-level database error returned inside successful JSON');
assert.match(bootstrapRunner, /Get-DatabaseStatusCode -Status \$result\.status\) -ne 0/, 'bootstrap must reject a per-statement database error');
assert.match(bootstrapRunner, /\[bool\]\$result\.partialResult/, 'bootstrap must reject a truncated per-statement result');
assert.match(bootstrapRunner, /\$rows\.Count -ne 1/, 'bootstrap must require exactly one final verification row');
assert.match(bootstrapRunner, /correct_database.*application_schema_ready.*migration_schema_ready/s, 'bootstrap must require all three named final verification columns');
assert.match(bootstrapRunner, /Assert-ExecuteSqlResponse -Response \$executeResponse\s+\$bootstrapCommitted = \$true/, 'bootstrap must validate the database response before recording success');
assert.match(bootstrapRunner, /finally\s*\{/, 'temporary access cleanup must run after success or failure');

assert.match(migrationRunner, /\[string\]\$Action\s*=\s*'Plan'/, 'database migration must default to a read-only plan');
assert.match(migrationRunner, /MIGRATE-EE-003-development/, 'database migration apply must require an exact confirmation');
assert.match(migrationRunner, /CLEANUP-MIGRATION-EE-003-development/, 'database migration must provide explicit recovery cleanup');
assert.match(migrationRunner, /Get-FileHash.*SHA256.*ExpectedPlanSha256/s, 'database migration must verify the separately approved plan fingerprint');
assert.match(migrationRunner, /\[IO\.FileShare\]::None/, 'migration execution must hold an exclusive local process lock');
assert.match(migrationRunner, /\[IO\.FileMode\]::CreateNew/, 'migration recovery marker must never overwrite an existing marker');
assert.doesNotMatch(migrationRunner, /analyze-iam-policy|--organization=/, 'migration must not require organization-wide permission inspection');
assert.match(migrationRunner, /Get-JobPolicy/, 'migration must inspect explicit permissions on the protected job');
assert.match(migrationRunner, /\$invokerMembers\.Count -ne 0/, 'migration must reject an existing explicit job-level invoker');
assert.match(migrationRunner, /\$membersAfterGrant\.Count -ne 1.*\$membersAfterGrant\[0\] -cne \$allowedPrincipal/s, 'migration must verify the temporary named job-level invoker');
assert.match(migrationRunner, /Assert-LiveJobMatchesPlan/, 'live migration job must match the reviewed saved plan');
assert.match(migrationRunner, /expectedMigrationImageDigest = '[0-9a-f]{64}'/, 'migration execution must pin the exact reviewed image digest');
assert.match(migrationRunner, /expectedMigrationSourceRevision = '[0-9a-f]{40}'/, 'migration execution must pin the source revision represented by the image');
assert.match(migrationRunner, /APP_SCHEMA = \$expectedApplicationSchema.*MIGRATION_SCHEMA = \$expectedMigrationSchema/s, 'migration execution must pin both client-approved schemas');
assert.match(migrationRunner, /expectedContainer\.command.*expectedContainer\.args.*expectedContainer\.working_dir.*expectedContainer\.ports/s, 'migration execution must reject reviewed-plan command overrides');
assert.match(migrationRunner, /liveContainer\.command.*liveContainer\.args.*liveContainer\.workingDir.*liveContainer\.ports/s, 'migration execution must reject live command overrides');
assert.match(migrationRunner, /execution_environment.*EXECUTION_ENVIRONMENT_GEN2.*execution-environment.*gen2/s, 'migration execution must require the approved second-generation runtime');
assert.match(migrationRunner, /liveLimits\.cpu.*'1'.*liveLimits\.memory.*'512Mi'/s, 'migration execution must require exact live resource limits');
assert.match(migrationRunner, /Get-ExecutionCount\) -ne 0/, 'migration must refuse an existing execution history');
assert.match(migrationRunner, /Pre-EE-003 application table migration safety backup/, 'migration must require the approved pre-migration backup');
assert.match(migrationRunner, /\$Action -ne 'Cleanup'.*Resolve-IgnoredInputFile -Path \$ReviewedPlan/s, 'emergency cleanup must not require the reviewed plan file');
assert.match(migrationRunner, /Clear-TemporaryInvokerBinding/, 'normal and emergency cleanup must remove the explicit job-level binding');
assert.match(migrationRunner, /\$bindingCleanupArmed = \$true\s+\$iamMutationAttempted = \$true\s+Invoke-GcloudMutation/s, 'permission cleanup must be armed before the first IAM mutation');
assert.match(migrationRunner, /'run', 'jobs', 'execute'.*'--format=json'.*\$executionName.*Clear-TemporaryInvokerBinding.*'executions', 'describe'/s, 'migration must start once, capture its identity, remove permission and then monitor that exact execution');
assert.doesNotMatch(migrationRunner, /'run', 'jobs', 'execute'.*'--wait'/s, 'migration must not retain temporary permission while waiting for completion');
assert.doesNotMatch(migrationRunner, /--args|--update-env-vars|--tasks|--task-timeout|--container/, 'migration execution must not override the reviewed job');
assert.match(migrationRunner, /remove-iam-policy-binding/, 'temporary job-level execution permission must be removed');
assert.match(migrationRunner, /\$removeMarker = \$markerCreatedThisRun -and -not \$iamMutationAttempted/, 'any attempted IAM mutation must leave a permanent no-retry marker');
assert.match(migrationRunner, /Clear-TemporaryInvokerBinding\s+if \(-not \$bindingCleanupVerified/s, 'temporary permission must be removed immediately after job execution');
assert.match(migrationRunner, /succeededCount -ne 1.*failedCount -ne 0/s, 'migration must require exactly one successful task and no failures');
assert.match(migrationRunner, /Test-ExecutionLogEntry.*run\.googleapis\.com\/execution_name/s, 'migration must isolate the exact Cloud Run execution log label locally');
assert.match(migrationRunner, /\$record\.status -eq 'ok'.*\$record\.applied\[0\] -eq \$expectedAppliedMigration/s, 'migration must require the exact execution-scoped V0001 success record');
assert.doesNotMatch(bootstrapRunner, /--password(?:=|')|password-secret-version/i, 'bootstrap must not create or pass a password');

assert.match(bootstrapTemplate, /^BEGIN;/m, 'bootstrap changes must use one transaction');
assert.match(bootstrapTemplate, /^COMMIT;/m, 'bootstrap changes must commit only after postchecks');
assert.match(bootstrapTemplate, /SET LOCAL search_path = pg_catalog/, 'administrator search path must be locked');
assert.match(bootstrapTemplate, /pg_advisory_xact_lock/, 'bootstrap and migration must serialize on a database lock');
assert.match(bootstrapTemplate, /CREATE SCHEMA __APPLICATION_SCHEMA_IDENTIFIER__/, 'bootstrap must create the approved application schema');
assert.match(bootstrapTemplate, /CREATE SCHEMA __MIGRATION_SCHEMA_IDENTIFIER__/, 'bootstrap must create the approved control schema');
assert.match(bootstrapTemplate, /temporary_membership_count\s*<>\s*1/, 'bootstrap must verify the one-time operator can assign the approved owner');
assert.match(bootstrapTemplate, /REVOKE ALL ON SCHEMA __APPLICATION_SCHEMA_IDENTIFIER__ FROM PUBLIC/, 'public application-schema access must be removed');
assert.match(bootstrapTemplate, /REVOKE ALL ON SCHEMA __MIGRATION_SCHEMA_IDENTIFIER__ FROM PUBLIC/, 'public control-schema access must be removed');

assert.match(candidateWorkflow, /workflow_dispatch:/, 'candidate publication must be manually started');
assert.match(candidateWorkflow, /environment:\s*development/, 'candidate publication must use the protected development environment');
assert.match(candidateWorkflow, /id-token:\s*write/, 'candidate publication requires keyless federation');
for (const variable of ['GCP_PROJECT_ID', 'GCP_REGION', 'GCP_ARTIFACT_REPOSITORY', 'GCP_WORKLOAD_IDENTITY_PROVIDER', 'GCP_SERVICE_ACCOUNT']) {
  assert.match(candidateWorkflow, new RegExp(`vars\\.${variable}\\b`), `candidate workflow must use the established ${variable} environment variable`);
}
assert.match(candidateWorkflow, /google-github-actions\/auth@[0-9a-f]{40}/, 'Google authentication must be commit-pinned');
assert.match(candidateWorkflow, /docker\/build-push-action@[0-9a-f]{40}/, 'container build action must be commit-pinned');
assert.match(candidateWorkflow, /provenance:\s*mode=max/, 'published image must include provenance');
assert.match(candidateWorkflow, /sbom:\s*true/, 'published image must include a software bill of materials');
assert.match(candidateWorkflow, /python\s+-m\s+bandit\b/, 'backend publication must run Bandit before authentication');
assert.match(candidateWorkflow, /python\s+-m\s+pip_audit\b/, 'backend publication must audit locked runtime dependencies before authentication');
assert.match(candidateWorkflow, /\^sha256:\[0-9a-f\]\{64\}\$/, 'published digest must be validated');
assert.match(candidateWorkflow, /\/health/, 'the exact published digest must pass a health smoke test');
assert.match(candidateWorkflow, /did not deploy Cloud Run/, 'candidate workflow must not deploy Cloud Run');
assert.doesNotMatch(candidateWorkflow, /gcloud\s+run\s+deploy|terraform\s+apply/, 'candidate publication must not deploy');

assert.match(healthVerifier, /auth print-identity-token/, 'private Cloud Run verification must use a short-lived identity token');
assert.match(healthVerifier, /run services describe/, 'health verification must resolve the service URL from Google Cloud');
assert.match(healthVerifier, /--audiences=\$origin/, 'the identity token must be scoped to the resolved service origin');
assert.match(healthVerifier, /--impersonate-service-account=\$VerifierServiceAccount/, 'local verification must use an approved service account identity');
assert.match(healthVerifier, /MaximumRedirection\s+0/, 'health verification must reject redirects');
assert.match(healthVerifier, /\/health/, 'post-deployment verification must call the health endpoint');
assert.match(healthVerifier, /Cache-Control/, 'post-deployment verification must check safe response headers');
assert.doesNotMatch(healthVerifier, /Write-Host.*identityToken/i, 'identity tokens must never be printed');

assert.match(deploymentWorkflow, /workflow_dispatch:/, 'deployment verification must be manually started');
assert.match(deploymentWorkflow, /environment:\s*development/, 'deployment verification must use the protected development environment');
assert.match(deploymentWorkflow, /id-token:\s*write/, 'deployment verification requires keyless federation');
assert.match(deploymentWorkflow, /token_format:\s*id_token/, 'deployment verification must mint an identity token');
assert.match(deploymentWorkflow, /id_token_audience:\s*\$\{\{ env\.SERVICE_ORIGIN \}\}/, 'identity token audience must be the exact service origin');
assert.match(deploymentWorkflow, /id_token_include_email:\s*true/, 'Cloud Run identity tokens must include the bound service-account identity');
assert.match(deploymentWorkflow, /--max-redirs 0/, 'deployment verification must reject redirects');
assert.match(deploymentWorkflow, /\$SERVICE_ORIGIN\/health/, 'deployment verification must call the private health endpoint');
assert.doesNotMatch(deploymentWorkflow, /echo[^\n]*ID_TOKEN/i, 'deployment verification must never print the identity token');

assert.match(migrationWorkflow, /workflow_dispatch:/, 'migration candidate publication must be manually started');
assert.match(migrationWorkflow, /environment:\s*development/, 'migration candidate publication must use the protected development environment');
assert.match(migrationWorkflow, /id-token:\s*write/, 'migration candidate publication requires keyless federation');
assert.match(migrationWorkflow, /database\/Dockerfile/, 'migration publication must build the dedicated Dockerfile');
assert.match(migrationWorkflow, /provenance:\s*mode=max/, 'migration image publication must include provenance');
assert.match(migrationWorkflow, /sbom:\s*true/, 'migration image publication must include a software bill of materials');
assert.match(migrationWorkflow, /pip_audit/, 'migration image dependencies must be audited before publication');
assert.match(migrationWorkflow, /did not create or execute a migration job/, 'candidate publication must state that it cannot migrate the database');
assert.doesNotMatch(migrationWorkflow, /gcloud\s+run\s+jobs\s+(execute|deploy)|terraform\s+apply/, 'candidate publication must not create or execute a migration job');
assert.match(migrationDockerfile, /^FROM\s+python:[^\s]+@sha256:[0-9a-f]{64}$/m, 'migration image base must be digest-pinned');
assert.match(migrationDockerfile, /pip install --no-cache-dir --requirement requirements\.lock/, 'migration image must install the reviewed lock file');
assert.match(migrationDockerfile, /^USER\s+engagement$/m, 'migration image must run as a non-root identity');
assert.match(migrationDockerfile, /^ENTRYPOINT \["python", "migration_runner\.py"\]$/m, 'migration image must have a fixed runner entrypoint');

for (const environment of ['development', 'staging', 'production']) {
  const example = read(`environments/${environment}.tfvars.example`);
  assert.match(example, new RegExp(`environment\\s*=\\s*"${environment}"`));
  assert.match(example, /public_api_origin\s*=\s*null/, `${environment} example must not guess a service origin`);
  assert.match(example, /prepare_public_gateway\s*=\s*false/, `${environment} public gateway preparation must be opt-in`);
  assert.match(example, /activate_public_gateway\s*=\s*false/, `${environment} public gateway activation must be opt-in`);
  assert.match(example, /public_api_hostname\s*=\s*null/, `${environment} example must not guess a client-controlled hostname`);
  assert.match(example, /alert_notification_email\s*=\s*null/, `${environment} example must not contain an alert recipient`);
  assert.match(example, /enable_identity_platform\s*=\s*false/, `${environment} must make phone identity an explicit deployment decision`);
  assert.match(example, /identity_test_phone_numbers\s*=\s*\{\}/, `${environment} example must not contain fictional phone credentials`);
  assert.match(example, /identity_sms_allowed_regions\s*=\s*\["IN"\]/, `${environment} must default real sign-in messages to India only`);
  assert.match(example, /deploy_database_migration_job\s*=\s*false/, `${environment} example must keep the migration job disabled`);
  assert.match(example, /database_migration_image\s*=\s*null/, `${environment} example must not guess a migration image`);
  assert.match(example, /database_migration_source_revision\s*=\s*null/, `${environment} example must not guess a source revision`);
  assert.match(example, /database_application_schema\s*=\s*null/, `${environment} example must await the approved application schema`);
  assert.match(example, /database_migration_schema\s*=\s*null/, `${environment} example must await the approved migration schema`);
  assert.doesNotMatch(example, /@[^\s"]+\.[^\s"]+/, `${environment} example must not contain an email`);
  assert.doesNotMatch(example, /[a-f0-9]{32,}/i, `${environment} example must not contain token-like data`);
}

const configExample = readFileSync(resolve(root, '..', 'config', 'engagement', '.env.example'), 'utf8');
const requiredEnvironmentKeys = [...configExample.matchAll(/^(EE_[A-Z0-9_]+)=/gm)].map((match) => match[1]);
for (const key of requiredEnvironmentKeys) {
  assert.match(source, new RegExp(`\\b${key}\\b`), `Cloud Run startup contract is missing ${key}`);
}

const forbidden = [
  /amiko-[0-9]+/i,
  /AIza[0-9A-Za-z_-]{20,}/,
  new RegExp(['-----BEGIN ', '(?:RSA |EC |OPENSSH )?', 'PRIVATE KEY-----'].join('')),
  /"private_key"\s*:/,
  /"client_email"\s*:/
];

for (const pattern of forbidden) {
  assert.doesNotMatch(source + runner + bootstrapRunner + migrationRunner + bootstrapTemplate, pattern, `forbidden tracked value matched ${pattern}`);
}

execFileSync(
  'pwsh',
  ['-NoProfile', '-File', join(root, 'tests', 'test-database-migration-runner.ps1')],
  { stdio: 'inherit' }
);
for (const timezone of ['UTC', 'Asia/Kolkata']) {
  execFileSync(
    'pwsh',
    ['-NoProfile', '-File', join(root, 'tests', 'test-week2-database-update.ps1')],
    { stdio: 'inherit', env: { ...process.env, TZ: timezone } }
  );
  execFileSync(
    'pwsh',
    ['-NoProfile', '-File', join(root, 'tests', 'test-profile-photo-database-update.ps1')],
    { stdio: 'inherit', env: { ...process.env, TZ: timezone } }
  );
}

console.log(`Infrastructure safety validation passed for ${files.length} Terraform files and 3 environment examples.`);
for (const timezone of ['UTC', 'Asia/Kolkata']) {
  execFileSync('pwsh', ['-NoProfile', '-File', join(root, 'tests', 'test-fictional-staff-setup.ps1')],
    { stdio: 'inherit', env: { ...process.env, TZ: timezone } });
}
