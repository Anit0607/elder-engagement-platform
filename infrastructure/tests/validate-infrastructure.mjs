import assert from 'node:assert/strict';
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

assert.ok(files.length >= 8, 'foundation must be split into reviewable concerns');
assert.match(source, /backend\s+"gcs"/, 'remote Google Cloud Storage state is required');
assert.match(source, /disable_on_destroy\s*=\s*false/, 'required interfaces must survive ordinary destroy');
assert.match(source, /roles\/iam\.workloadIdentityUser/, 'GitHub must use Workload Identity Federation');
assert.match(source, /assertion\.repository\s*==/, 'federation must be restricted to one repository');
assert.match(source, /assertion\.repository_id\s*==/, 'federation must be restricted to an immutable repository identifier');
assert.match(source, /assertion\.repository_owner_id\s*==/, 'federation must be restricted to an immutable owner identifier');
assert.match(source, /assertion\.ref\s*==/, 'federation must be restricted to an approved Git ref');
assert.doesNotMatch(source, /service_account_key/, 'service-account JSON keys are prohibited');
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
assert.match(source, /edition\s*=\s*"ENTERPRISE"/, 'shared-core development SQL must explicitly use Enterprise edition');
assert.match(source, /google_billing_budget/, 'a project budget is mandatory');
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
assert.match(source, /startup_probe\s*\{[\s\S]*?tcp_socket\s*\{/m, 'Cloud Run must have a startup probe');
assert.match(source, /liveness_probe\s*\{[\s\S]*?http_get\s*\{[\s\S]*?path\s*=\s*"\/health"/m, 'Cloud Run liveness must call the HTTP health endpoint');
assert.match(source, /http_headers\s*\{[\s\S]*?name\s*=\s*"Host"[\s\S]*?value\s*=\s*local\.cloud_run_hostname/m, 'Cloud Run liveness must use the configured trusted host');
assert.doesNotMatch(source, /liveness_probe\s*\{[\s\S]*?tcp_socket\s*\{/m, 'Cloud Run does not support TCP liveness probes');
assert.match(source, /container_port\s*=\s*8080/, 'Cloud Run and the container must agree on port 8080');
assert.doesNotMatch(source, /cloudbuild\.googleapis\.com|google_cloudbuild_/, 'GitHub Actions is the approved builder; Cloud Build must not be enabled');
assert.doesNotMatch(source, /local-exec|\.sql["']/, 'infrastructure planning must not execute an application schema');

const runner = read('scripts/Invoke-Infrastructure.ps1');
const healthVerifier = read('scripts/Test-CloudRunHealth.ps1');
assert.match(runner, /\[string\]\$Action\s*=\s*'Plan'/, 'runner must default to plan');
assert.match(runner, /APPLY-\$Environment/, 'apply must require an environment-specific confirmation');
assert.match(runner, /Apply requires a reviewed saved plan/, 'apply must consume a saved reviewed plan');
assert.match(runner, /check-ignore --quiet/, 'environment inputs and saved plans must be ignored by Git');
assert.match(runner, /GetRelativePath/, 'Git safety checks must use repository-relative paths');
assert.match(runner, /auth print-access-token --quiet/, 'the local runner must acquire an ephemeral Google Cloud access token');
assert.match(runner, /Remove-Item Env:GOOGLE_OAUTH_ACCESS_TOKEN/, 'the local runner must clear its injected access token');
assert.match(runner, /secure-runtime\\gcloud-config/, 'the local runner must prefer the ignored workspace Google Cloud configuration');
assert.match(runner, /Remove-Item Env:CLOUDSDK_CONFIG/, 'the local runner must restore its Google Cloud configuration environment');

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
assert.match(healthVerifier, /MaximumRedirection\s+0/, 'health verification must reject redirects');
assert.match(healthVerifier, /\/health/, 'post-deployment verification must call the health endpoint');
assert.match(healthVerifier, /Cache-Control/, 'post-deployment verification must check safe response headers');
assert.doesNotMatch(healthVerifier, /Write-Host.*identityToken/i, 'identity tokens must never be printed');

for (const environment of ['development', 'staging', 'production']) {
  const example = read(`environments/${environment}.tfvars.example`);
  assert.match(example, new RegExp(`environment\\s*=\\s*"${environment}"`));
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
  assert.doesNotMatch(source + runner, pattern, `forbidden tracked value matched ${pattern}`);
}

console.log(`Infrastructure safety validation passed for ${files.length} Terraform files and 3 environment examples.`);
