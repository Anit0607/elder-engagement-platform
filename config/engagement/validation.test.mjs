import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseEnv, validateConfig } from "./validation.mjs";

const examplePath = fileURLToPath(new URL("./.env.example", import.meta.url));
const baseline = parseEnv(fs.readFileSync(examplePath, "utf8"));

test("safe development example passes", () => {
  assert.deepEqual(validateConfig(baseline), []);
});

test("staff runtime requires connected member runtime and a dedicated pinned secret", () => {
  const project = baseline.EE_GCP_PROJECT_ID;
  const staff = {
    ...baseline,
    EE_MEMBER_SESSION_ENABLED: "true",
    EE_MEMBER_IDENTITY_PROVIDER: "identity_platform",
    EE_FIREBASE_PROJECT_ID: project,
    EE_MEMBER_TOKEN_AUDIENCE: project,
    EE_DATABASE_IAM_USER: "synthetic-runtime@example-development-project.iam",
    EE_STAFF_SESSION_ENABLED: "true",
    EE_STAFF_AUTHENTICATOR_KEY_SECRET_REF: `projects/${project}/secrets/staff-auth/versions/1`,
  };
  assert.deepEqual(validateConfig(staff), []);
  for (const changes of [
    { EE_MEMBER_SESSION_ENABLED: "false" },
    { EE_STAFF_AUTHENTICATOR_KEY_SECRET_REF: "" },
    { EE_STAFF_AUTHENTICATOR_KEY_SECRET_REF: `projects/${project}/secrets/staff-auth/versions/latest` },
    { EE_STAFF_AUTHENTICATOR_KEY_SECRET_REF: baseline.EE_FIELD_ENCRYPTION_KEY_SECRET_REF },
    { EE_STAFF_SESSION_ENABLED: "yes" },
    { EE_STAFF_SESSION_ENABLED: "" },
  ]) assert.notEqual(validateConfig({ ...staff, ...changes }).length, 0);
});

test("unknown raw-secret key is rejected", () => {
  const errors = validateConfig({ ...baseline, EE_DATABASE_PASSWORD: "not-a-real-secret" });
  assert.ok(errors.includes("unknown key: EE_DATABASE_PASSWORD"));
});

test("duplicate keys are rejected", () => {
  assert.throws(() => parseEnv("EE_ENVIRONMENT=development\nEE_ENVIRONMENT=production\n"), /duplicate key/);
});

test("staging fails closed on mock, memory, local and placeholder settings", () => {
  const errors = validateConfig({ ...baseline, EE_ENVIRONMENT: "staging" });
  assert.ok(errors.some((item) => item.includes("mock identity")));
  assert.ok(errors.some((item) => item.includes("memory rate limits")));
  assert.ok(errors.some((item) => item.includes("forbidden marker")));
  assert.ok(errors.some((item) => item.includes("HTTPS origin")));
});

test("secret fields accept references and reject raw values", () => {
  const errors = validateConfig({ ...baseline, EE_DATABASE_URL_SECRET_REF: "postgres://user:password@host/db" });
  assert.ok(errors.some((item) => item.startsWith("EE_DATABASE_URL_SECRET_REF must be")));
});

test("secret references cannot cross the environment project boundary", () => {
  const errors = validateConfig({
    ...baseline,
    EE_DATABASE_URL_SECRET_REF: "projects/another-development-project/secrets/ee-database-url/versions/1",
  });
  assert.ok(errors.includes("EE_DATABASE_URL_SECRET_REF must reference the configured environment project"));
});

test("quarantine and approved media use distinct buckets", () => {
  const errors = validateConfig({ ...baseline, EE_APPROVED_MEDIA_BUCKET: baseline.EE_UPLOADS_BUCKET });
  assert.ok(errors.includes("quarantine and approved-media buckets must be distinct"));
});

test("enabled integrations require only their own configuration", () => {
  const errors = validateConfig({
    ...baseline,
    EE_YOUTUBE_ENABLED: "true",
    EE_BROADCAST_PROVIDER: "agora",
  });
  assert.ok(errors.includes("EE_YOUTUBE_API_KEY_SECRET_REF is required for the selected mode"));
  assert.ok(errors.includes("EE_AGORA_APP_ID is required for the selected mode"));
  assert.ok(errors.includes("EE_AGORA_APP_CERTIFICATE_SECRET_REF is required for the selected mode"));
});

test("CORS origins are required in every environment", () => {
  const { EE_CORS_ORIGINS: _removed, ...withoutCors } = baseline;
  const errors = validateConfig(withoutCors);
  assert.ok(errors.includes("missing required key: EE_CORS_ORIGINS"));
});

test("secure public origin must match a trusted host", () => {
  const project = "valid-staging-project";
  const secure = {
    ...baseline,
    EE_ENVIRONMENT: "staging",
    EE_GCP_PROJECT_ID: project,
    EE_GCP_REGION: "asia-south1",
    EE_PUBLIC_API_ORIGIN: "https://api.staging.invalid",
    EE_TRUSTED_HOSTS: "different.staging.invalid",
    EE_CORS_ORIGINS: "https://console.staging.invalid",
    EE_CLOUD_SQL_INSTANCE: `${project}:asia-south1:engagement-postgres`,
    EE_DATABASE_URL_SECRET_REF: `projects/${project}/secrets/database-url/versions/1`,
    EE_RATE_LIMIT_STORE: "redis",
    EE_REDIS_URL_SECRET_REF: `projects/${project}/secrets/redis-url/versions/1`,
    EE_SESSION_SIGNING_KEY_SECRET_REF: `projects/${project}/secrets/session-key/versions/1`,
    EE_REFRESH_TOKEN_PEPPER_SECRET_REF: `projects/${project}/secrets/refresh-pepper/versions/1`,
    EE_FIELD_ENCRYPTION_KEY_SECRET_REF: `projects/${project}/secrets/field-key/versions/1`,
    EE_MEMBER_IDENTITY_PROVIDER: "firebase",
    EE_FIREBASE_PROJECT_ID: project,
    EE_MEMBER_TOKEN_AUDIENCE: project,
    EE_UPLOADS_BUCKET: `${project}-quarantine`,
    EE_APPROVED_MEDIA_BUCKET: `${project}-approved`,
    EE_UPLOAD_SIGNER_SERVICE_ACCOUNT: `upload-signer@${project}.iam.gserviceaccount.com`,
  };
  const errors = validateConfig(secure);
  assert.ok(errors.includes("public API host must appear in EE_TRUSTED_HOSTS"));
});

test("secure origins reject credentials, query strings and fragments", () => {
  const errors = validateConfig({
    ...baseline,
    EE_ENVIRONMENT: "staging",
    EE_PUBLIC_API_ORIGIN: "https://user:password@api.staging.invalid/?debug=true",
    EE_CORS_ORIGINS: "https://console.staging.invalid/#fragment",
  });
  assert.ok(errors.includes("staging/production API origin must be an HTTPS origin without a path"));
  assert.ok(errors.includes("staging/production CORS origins must be HTTPS origins without paths"));
});
