import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const contractPath = path.join(workspace, "api", "openapi", "elder-engage-v1.openapi.json");
const contract = JSON.parse(await readFile(contractPath, "utf8"));
const errors = [];

const operations = new Set(["get", "put", "post", "delete", "options", "head", "patch", "trace"]);
const operationIds = new Set();

const resolvePointer = (pointer) => {
  if (!pointer.startsWith("#/")) return undefined;
  return pointer
    .slice(2)
    .split("/")
    .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"))
    .reduce((value, part) => value?.[part], contract);
};

const visit = (value, location = "#") => {
  if (!value || typeof value !== "object") return;
  if ("$ref" in value && !resolvePointer(value.$ref))
    errors.push(`${location}: unresolved reference ${value.$ref}`);
  for (const [key, child] of Object.entries(value)) visit(child, `${location}/${key}`);
};

if (contract.openapi !== "3.1.1") errors.push("The contract must use OpenAPI 3.1.1.");
if (!String(contract.info?.version ?? "").match(/^0\.1\./))
  errors.push("The Pre-Sprint contract version must remain in the 0.1.x draft line.");
if (contract["x-contract-status"] !== "pre-sprint-draft")
  errors.push("The contract must remain clearly marked as a Pre-Sprint draft.");
for (const server of contract.servers ?? []) {
  try {
    const url = new URL(server.url);
    if (
      url.protocol !== "http:" ||
      !["127.0.0.1", "localhost", "::1"].includes(url.hostname)
    )
      errors.push(
        `Server ${server.url} is not an exact local-only HTTP origin; a client-owned staging origin must not be invented before Day 0.`,
      );
  } catch {
    errors.push(`Server URL is invalid: ${server.url}`);
  }
}

for (const [route, pathItem] of Object.entries(contract.paths ?? {})) {
  for (const [method, operation] of Object.entries(pathItem)) {
    if (!operations.has(method)) continue;
    const label = `${method.toUpperCase()} ${route}`;
    if (!operation.operationId) errors.push(`${label}: operationId is required.`);
    else if (operationIds.has(operation.operationId))
      errors.push(`${label}: duplicate operationId ${operation.operationId}.`);
    else operationIds.add(operation.operationId);
    if (!operation.summary) errors.push(`${label}: summary is required.`);
    if (!operation.responses || !Object.keys(operation.responses).length)
      errors.push(`${label}: at least one response is required.`);
  }
}

visit(contract);

const profile = contract.components?.schemas?.Profile;
const profileExample = contract.components?.examples?.SyntheticProfile?.value;
const requiredProfileFields = [
  "id",
  "role",
  "status",
  "displayName",
  "preferredLanguage",
  "createdAt",
  "updatedAt",
  "interests",
  "notificationWindow",
];
if (profile?.type !== "object" || profile?.allOf)
  errors.push(
    "Profile must be one strict object; closed allOf composition can reject valid extension fields.",
  );
for (const field of requiredProfileFields) {
  if (!profile?.required?.includes(field) || !profile?.properties?.[field])
    errors.push(`Profile is missing required field ${field}.`);
}
for (const field of requiredProfileFields) {
  if (!(field in (profileExample ?? {})))
    errors.push(`Synthetic profile example is missing required field ${field}.`);
}
for (const field of Object.keys(profileExample ?? {})) {
  if (!profile?.properties?.[field])
    errors.push(`Synthetic profile example contains undeclared field ${field}.`);
}

const sessionResponse = contract.components?.schemas?.SessionResponse;
for (const tokenField of ["accessToken", "refreshToken"]) {
  if (sessionResponse?.properties?.[tokenField]?.writeOnly)
    errors.push(
      `SessionResponse.${tokenField} cannot be writeOnly because mobile response clients must receive it.`,
    );
}

for (const requiredPath of [
  "/v1/me/profile/photo-upload",
  "/v1/me/profile/photo-upload/{uploadId}/complete",
]) {
  if (!contract.paths?.[requiredPath])
    errors.push(`Profile photo lifecycle path is missing: ${requiredPath}`);
}
if (!contract.paths?.["/v1/admin/users"]?.post)
  errors.push("Manual Administrator profile creation is missing.");

for (const errorCode of [
  "ACCESS_TOKEN_EXPIRED",
  "INVALID_REFRESH_TOKEN",
  "REFRESH_OUTCOME_UNKNOWN",
  "SESSION_REVOKED",
  "REFRESH_TOKEN_REUSED",
  "ACCOUNT_SUSPENDED",
  "PROFILE_NOT_PROVISIONED",
  "MFA_REQUIRED",
  "RATE_LIMITED",
]) {
  if (!contract.components?.schemas?.ErrorCode?.enum?.includes(errorCode))
    errors.push(`Stable error code is missing: ${errorCode}`);
  if (!contract["x-client-error-actions"]?.[errorCode])
    errors.push(`Mobile recovery action is missing for ${errorCode}.`);
}

if (!String(contract["x-implementation-status"] ?? "").includes("No listed operation"))
  errors.push("The contract must explicitly state that listed operations are not yet claimed callable.");

const adminCreate = contract.components?.schemas?.AdminCreateUserRequest;
if (!adminCreate?.oneOf || adminCreate.oneOf.length !== 2)
  errors.push("Manual onboarding must define separate Member and staff identity rules.");
const memberBranch = adminCreate?.oneOf?.find(
  (branch) => branch.properties?.role?.const === "member",
);
const staffBranch = adminCreate?.oneOf?.find(
  (branch) => branch.properties?.role?.enum?.includes("contributor"),
);
if (
  memberBranch?.properties?.phoneE164?.type !== "string" ||
  memberBranch?.properties?.username?.type !== "null"
)
  errors.push("Member onboarding must require a usable phone number and reject username-only identity.");
if (staffBranch?.properties?.username?.type !== "string")
  errors.push("Contributor/Administrator onboarding must require a usable username.");

const serialized = JSON.stringify(contract).toLowerCase();
for (const forbidden of [
  "staging-api.eldercaresaathi.com",
  "api.eldercaresaathi.com",
  "example-password",
  "bearer eyj",
]) {
  if (serialized.includes(forbidden))
    errors.push(`Contract contains forbidden legacy or secret-like value: ${forbidden}`);
}

if (errors.length) {
  console.error(`OpenAPI validation failed with ${errors.length} issue(s):`);
  for (const error of errors) console.error(`- ${error}`);
  process.exit(1);
}

console.log(
  `OpenAPI validation passed: ${Object.keys(contract.paths).length} paths, ${operationIds.size} operations, ${Object.keys(contract.components.schemas).length} schemas.`,
);
