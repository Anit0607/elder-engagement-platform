import fs from "node:fs";

const allowedKeys = new Set([
  "EE_ENVIRONMENT", "EE_APP_NAME", "EE_API_PREFIX", "EE_LOG_LEVEL",
  "EE_GCP_PROJECT_ID", "EE_GCP_REGION", "EE_PUBLIC_API_ORIGIN", "EE_TRUSTED_HOSTS",
  "EE_CORS_ORIGINS", "EE_CLOUD_SQL_INSTANCE", "EE_DATABASE_URL_SECRET_REF",
  "EE_RATE_LIMIT_STORE", "EE_REDIS_URL_SECRET_REF", "EE_SESSION_SIGNING_KEY_SECRET_REF",
  "EE_REFRESH_TOKEN_PEPPER_SECRET_REF", "EE_FIELD_ENCRYPTION_KEY_SECRET_REF",
  "EE_MEMBER_IDENTITY_PROVIDER", "EE_FIREBASE_PROJECT_ID", "EE_MEMBER_TOKEN_AUDIENCE",
  "EE_UPLOADS_BUCKET", "EE_APPROVED_MEDIA_BUCKET", "EE_UPLOAD_SIGNER_SERVICE_ACCOUNT",
  "EE_UPLOAD_MAX_BYTES", "EE_UPLOAD_ALLOWED_MIME_TYPES", "EE_UPLOAD_AUTHORIZATION_SECONDS",
  "EE_FCM_ENABLED", "EE_FCM_PROJECT_ID", "EE_YOUTUBE_ENABLED",
  "EE_YOUTUBE_API_KEY_SECRET_REF", "EE_MEET_MODE", "EE_MEET_OAUTH_CLIENT_SECRET_REF",
  "EE_BROADCAST_PROVIDER", "EE_AGORA_APP_ID", "EE_AGORA_APP_CERTIFICATE_SECRET_REF",
  "EE_ACCESS_TOKEN_MINUTES", "EE_REFRESH_TOKEN_DAYS",
]);

const alwaysRequired = [
  "EE_ENVIRONMENT", "EE_APP_NAME", "EE_API_PREFIX", "EE_LOG_LEVEL", "EE_GCP_PROJECT_ID",
  "EE_GCP_REGION", "EE_PUBLIC_API_ORIGIN", "EE_TRUSTED_HOSTS", "EE_CORS_ORIGINS", "EE_CLOUD_SQL_INSTANCE",
  "EE_DATABASE_URL_SECRET_REF", "EE_RATE_LIMIT_STORE", "EE_SESSION_SIGNING_KEY_SECRET_REF",
  "EE_REFRESH_TOKEN_PEPPER_SECRET_REF", "EE_FIELD_ENCRYPTION_KEY_SECRET_REF",
  "EE_MEMBER_IDENTITY_PROVIDER", "EE_UPLOADS_BUCKET", "EE_APPROVED_MEDIA_BUCKET",
  "EE_UPLOAD_SIGNER_SERVICE_ACCOUNT", "EE_UPLOAD_MAX_BYTES", "EE_UPLOAD_ALLOWED_MIME_TYPES",
  "EE_UPLOAD_AUTHORIZATION_SECONDS", "EE_FCM_ENABLED", "EE_YOUTUBE_ENABLED", "EE_MEET_MODE",
  "EE_BROADCAST_PROVIDER", "EE_ACCESS_TOKEN_MINUTES", "EE_REFRESH_TOKEN_DAYS",
];

const secretRefKeys = [...allowedKeys].filter((key) => key.endsWith("_SECRET_REF"));
const secretRefPattern = /^projects\/[a-z][a-z0-9-]{4,28}[a-z0-9]\/secrets\/[A-Za-z0-9_-]{1,255}\/versions\/(?:latest|[1-9][0-9]*)$/;
const serviceAccountPattern = /^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$/;

export function parseEnv(text) {
  const values = {};
  for (const [index, rawLine] of text.split(/\r?\n/).entries()) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator < 1) throw new Error(`line ${index + 1}: expected KEY=VALUE`);
    const key = line.slice(0, separator).trim();
    if (Object.hasOwn(values, key)) throw new Error(`duplicate key: ${key}`);
    values[key] = line.slice(separator + 1).trim();
  }
  return values;
}

function requireWhen(values, errors, condition, keys) {
  if (!condition) return;
  for (const key of keys) {
    if (!values[key]) errors.push(`${key} is required for the selected mode`);
  }
}

function boundedInteger(values, errors, key, minimum, maximum) {
  const value = Number(values[key]);
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    errors.push(`${key} must be an integer from ${minimum} to ${maximum}`);
  }
}

export function validateConfig(values) {
  const errors = [];
  for (const key of Object.keys(values)) {
    if (!allowedKeys.has(key)) errors.push(`unknown key: ${key}`);
  }
  for (const key of alwaysRequired) {
    if (!values[key]) errors.push(`missing required key: ${key}`);
  }

  if (!["development", "staging", "production"].includes(values.EE_ENVIRONMENT)) {
    errors.push("EE_ENVIRONMENT must be development, staging or production");
  }
  if (values.EE_API_PREFIX !== "/v1") errors.push("EE_API_PREFIX must be /v1");
  if (!["DEBUG", "INFO", "WARNING", "ERROR"].includes(values.EE_LOG_LEVEL)) {
    errors.push("EE_LOG_LEVEL is invalid");
  }
  if (!["memory", "redis"].includes(values.EE_RATE_LIMIT_STORE)) {
    errors.push("EE_RATE_LIMIT_STORE must be memory or redis");
  }
  if (!["mock", "firebase", "identity_platform"].includes(values.EE_MEMBER_IDENTITY_PROVIDER)) {
    errors.push("EE_MEMBER_IDENTITY_PROVIDER is invalid");
  }
  if (!["disabled", "link", "api"].includes(values.EE_MEET_MODE)) errors.push("EE_MEET_MODE is invalid");
  if (!["disabled", "agora"].includes(values.EE_BROADCAST_PROVIDER)) {
    errors.push("EE_BROADCAST_PROVIDER is invalid");
  }
  for (const key of ["EE_FCM_ENABLED", "EE_YOUTUBE_ENABLED"]) {
    if (!["true", "false"].includes(values[key])) errors.push(`${key} must be true or false`);
  }

  for (const key of secretRefKeys) {
    if (values[key] && !secretRefPattern.test(values[key])) {
      errors.push(`${key} must be a Secret Manager version reference`);
    } else if (values[key] && values[key].split("/")[1] !== values.EE_GCP_PROJECT_ID) {
      errors.push(`${key} must reference the configured environment project`);
    }
  }
  if (values.EE_UPLOAD_SIGNER_SERVICE_ACCOUNT && !serviceAccountPattern.test(values.EE_UPLOAD_SIGNER_SERVICE_ACCOUNT)) {
    errors.push("EE_UPLOAD_SIGNER_SERVICE_ACCOUNT must be a service-account email");
  }
  if (values.EE_UPLOADS_BUCKET && values.EE_UPLOADS_BUCKET === values.EE_APPROVED_MEDIA_BUCKET) {
    errors.push("quarantine and approved-media buckets must be distinct");
  }

  requireWhen(values, errors, values.EE_RATE_LIMIT_STORE === "redis", ["EE_REDIS_URL_SECRET_REF"]);
  requireWhen(values, errors, ["firebase", "identity_platform"].includes(values.EE_MEMBER_IDENTITY_PROVIDER), [
    "EE_FIREBASE_PROJECT_ID", "EE_MEMBER_TOKEN_AUDIENCE",
  ]);
  requireWhen(values, errors, values.EE_FCM_ENABLED === "true", ["EE_FCM_PROJECT_ID"]);
  requireWhen(values, errors, values.EE_YOUTUBE_ENABLED === "true", ["EE_YOUTUBE_API_KEY_SECRET_REF"]);
  requireWhen(values, errors, values.EE_MEET_MODE === "api", ["EE_MEET_OAUTH_CLIENT_SECRET_REF"]);
  requireWhen(values, errors, values.EE_BROADCAST_PROVIDER === "agora", [
    "EE_AGORA_APP_ID", "EE_AGORA_APP_CERTIFICATE_SECRET_REF",
  ]);

  boundedInteger(values, errors, "EE_ACCESS_TOKEN_MINUTES", 5, 30);
  boundedInteger(values, errors, "EE_REFRESH_TOKEN_DAYS", 1, 90);
  boundedInteger(values, errors, "EE_UPLOAD_MAX_BYTES", 32768, 1073741824);
  boundedInteger(values, errors, "EE_UPLOAD_AUTHORIZATION_SECONDS", 60, 900);

  if (values.EE_ENVIRONMENT === "staging" || values.EE_ENVIRONMENT === "production") {
    const serialized = Object.values(values).join("\n").toLowerCase();
    for (const marker of ["example", "replace", "pending", "localhost", "127.0.0.1"]) {
      if (serialized.includes(marker)) errors.push(`${values.EE_ENVIRONMENT} configuration contains forbidden marker: ${marker}`);
    }
    const trustedHosts = values.EE_TRUSTED_HOSTS?.split(",").map((item) => item.trim()).filter(Boolean) ?? [];
    const corsOrigins = values.EE_CORS_ORIGINS?.split(",").map((item) => item.trim()).filter(Boolean) ?? [];
    let publicOrigin;
    try {
      publicOrigin = new URL(values.EE_PUBLIC_API_ORIGIN);
      if (
        publicOrigin.protocol !== "https:" ||
        publicOrigin.pathname !== "/" ||
        publicOrigin.username ||
        publicOrigin.password ||
        publicOrigin.search ||
        publicOrigin.hash
      ) {
        errors.push("staging/production API origin must be an HTTPS origin without a path");
      }
    } catch {
      errors.push("staging/production API origin must be a valid HTTPS origin");
    }
    for (const origin of corsOrigins) {
      try {
        const parsed = new URL(origin);
        if (
          parsed.protocol !== "https:" ||
          parsed.pathname !== "/" ||
          parsed.username ||
          parsed.password ||
          parsed.search ||
          parsed.hash
        ) {
          errors.push("staging/production CORS origins must be HTTPS origins without paths");
        }
      } catch {
        errors.push("staging/production CORS origin is invalid");
      }
    }
    if (trustedHosts.includes("*")) errors.push("wildcard trusted host is forbidden");
    if (corsOrigins.includes("*")) errors.push("wildcard CORS origin is forbidden");
    if (trustedHosts.some((host) => host.includes("://") || host.includes("/") || host.includes(" "))) {
      errors.push("trusted hosts must contain host names only");
    }
    if (publicOrigin && !trustedHosts.includes(publicOrigin.hostname)) {
      errors.push("public API host must appear in EE_TRUSTED_HOSTS");
    }
    if (values.EE_MEMBER_IDENTITY_PROVIDER === "mock") errors.push("mock identity is development-only");
    if (values.EE_RATE_LIMIT_STORE === "memory") errors.push("memory rate limits are development-only");
    if (values.EE_ENVIRONMENT === "production") {
      for (const key of secretRefKeys) {
        if (values[key]?.endsWith("/versions/latest")) errors.push(`${key} must pin a numeric production version`);
      }
    }
  }

  return errors;
}

export function validateFile(path) {
  return validateConfig(parseEnv(fs.readFileSync(path, "utf8")));
}
