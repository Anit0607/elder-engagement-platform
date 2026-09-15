import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const here = path.dirname(fileURLToPath(import.meta.url));
const contract = JSON.parse(
  await readFile(path.resolve(here, "..", "openapi", "elder-engage-v1.openapi.json"), "utf8"),
);
const postman = JSON.parse(
  await readFile(
    path.resolve(here, "..", "postman", "Elder_Engage_Sprint3_Draft.postman_collection.json"),
    "utf8",
  ),
);
const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
const failures = [];

const compile = (schemaName) =>
  ajv.compile({
    components: contract.components,
    $ref: `#/components/schemas/${schemaName}`,
  });

for (const schemaName of Object.keys(contract.components.schemas)) {
  try {
    compile(schemaName);
  } catch (error) {
    failures.push(`${schemaName} did not compile: ${error.message}`);
  }
}

const examples = {
  SyntheticMemberSessionRequest: "MemberSessionRequest",
  SyntheticStaffSessionRequest: "StaffSessionRequest",
  SyntheticRefreshRequest: "RefreshRequest",
  SyntheticSessionResponse: "SessionResponse",
  SyntheticNewMemberSessionResponse: "SessionResponse",
  SyntheticProfileUpdate: "ProfileUpdate",
  SyntheticNotificationPreferencesUpdate: "NotificationPreferencesUpdate",
  SyntheticNotificationPreferences: "NotificationPreferences",
  SyntheticAdminCreateMember: "AdminCreateUserRequest",
  SyntheticAdminCreateContributor: "AdminCreateUserRequest",
  SyntheticProfile: "Profile",
};

for (const [exampleName, schemaName] of Object.entries(examples)) {
  const validate = compile(schemaName);
  const value = contract.components.examples[exampleName]?.value;
  if (!value || !validate(value))
    failures.push(
      `${exampleName} failed ${schemaName}: ${JSON.stringify(validate.errors)}`,
    );
}

let negativeRuleCount = 0;
const expectInvalid = (label, schemaName, value) => {
  negativeRuleCount += 1;
  const validate = compile(schemaName);
  if (validate(value)) failures.push(`${label} unexpectedly validated as ${schemaName}.`);
};

for (const schemaName of ["ProfileUpdate", "AdminCreateUserRequest"]) {
  const value = schemaName === "ProfileUpdate"
    ? { preferredLanguage: "en", ageGroup: "55+" }
    : { ...contract.components.examples.SyntheticAdminCreateContributor.value, preferredLanguage: "en" };
  if (!compile(schemaName)(value)) failures.push(`${schemaName} rejected approved English preference.`);
}
expectInvalid("Unapproved profile language", "ProfileUpdate", { preferredLanguage: "fr" });

expectInvalid("Profile unknown field", "Profile", {
  ...contract.components.examples.SyntheticProfile.value,
  unexpected: true,
});
expectInvalid("Member with null phone", "AdminCreateUserRequest", {
  ...contract.components.examples.SyntheticAdminCreateMember.value,
  phoneE164: null,
});
expectInvalid("Member with username instead of phone", "AdminCreateUserRequest", {
  ...contract.components.examples.SyntheticAdminCreateMember.value,
  phoneE164: null,
  username: "member-as-staff",
});
expectInvalid("Contributor with null username", "AdminCreateUserRequest", {
  ...contract.components.examples.SyntheticAdminCreateContributor.value,
  username: null,
});
expectInvalid("Enabled window without times", "NotificationWindow", {
  enabled: true,
  timeZone: "Asia/Kolkata",
});
expectInvalid("Disabled window with active times", "NotificationWindow", {
  enabled: false,
  startLocalTime: "09:00",
  endLocalTime: "17:00",
  timeZone: "Asia/Kolkata",
});
expectInvalid("Unsupported time-zone shape", "NotificationWindow", {
  enabled: false,
  timeZone: "Kolkata",
});
expectInvalid("Incomplete notification preference replacement", "NotificationPreferencesUpdate", {
  eventReminders: true,
  contentUpdates: false,
});
expectInvalid("Unknown notification preference", "NotificationPreferencesUpdate", {
  ...contract.components.examples.SyntheticNotificationPreferencesUpdate.value,
  unknown: true,
});
expectInvalid("Circle with unknown field", "CircleCreate", {
  name: "Synthetic circle",
  unknown: true,
});
expectInvalid("Empty circle update", "CircleUpdate", {});
expectInvalid("Circle membership limit above approved range", "CircleSettingsUpdate", {
  maxMemberships: 21,
});

for (const field of ["accessToken", "refreshToken"]) {
  if (contract.components.schemas.SessionResponse.properties[field]?.writeOnly)
    failures.push(`Response field ${field} is incorrectly writeOnly.`);
}

for (const code of contract.components.schemas.ErrorCode.enum) {
  if (!contract["x-http-status-by-error-code"]?.[code])
    failures.push(`No HTTP status mapping for ${code}.`);
  if (
    [
      "ACCESS_TOKEN_EXPIRED",
      "INVALID_REFRESH_TOKEN",
      "REFRESH_OUTCOME_UNKNOWN",
      "SESSION_REVOKED",
      "REFRESH_TOKEN_REUSED",
      "ACCOUNT_SUSPENDED",
      "MFA_REQUIRED",
      "RATE_LIMITED",
      "CIRCLE_LIMIT_REACHED",
    ].includes(code) &&
    !contract["x-client-error-actions"]?.[code]
  )
    failures.push(`No mobile recovery action for ${code}.`);
}

const operationMethods = new Set(["get", "post", "put", "patch", "delete"]);
const openApiRequests = new Set();
for (const [route, pathItem] of Object.entries(contract.paths)) {
  for (const method of Object.keys(pathItem)) {
    if (operationMethods.has(method)) openApiRequests.add(`${method.toUpperCase()} ${route}`);
  }
}
const flattenPostman = (items) =>
  items.flatMap((item) => (item.item ? flattenPostman(item.item) : [item]));
const postmanRequests = new Set();
for (const item of flattenPostman(postman.item)) {
  const route = item.request.url.raw
    .replace("{{baseUrl}}", "")
    .split("?")[0]
    .replaceAll("{{sessionId}}", "{sessionId}")
    .replaceAll("{{userId}}", "{userId}")
    .replaceAll("{{uploadId}}", "{uploadId}")
    .replaceAll("{{circleId}}", "{circleId}");
  postmanRequests.add(`${item.request.method} ${route}`);
}
for (const operation of openApiRequests) {
  if (!postmanRequests.has(operation)) failures.push(`Postman request missing: ${operation}`);
}
for (const operation of postmanRequests) {
  if (!openApiRequests.has(operation)) failures.push(`Postman request is outside the contract: ${operation}`);
}
const postmanText = JSON.stringify(postman).toLowerCase();
for (const forbidden of ["bearer eyj", "private_key", "client_secret", "staging-api.eldercaresaathi.com"]) {
  if (postmanText.includes(forbidden)) failures.push(`Postman contains forbidden secret-like or legacy value: ${forbidden}`);
}

if (failures.length) {
  console.error(`Contract schema validation failed with ${failures.length} issue(s):`);
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log(
  `Contract schema validation passed: ${Object.keys(contract.components.schemas).length} schemas compiled, ${Object.keys(examples).length} examples validated, ${negativeRuleCount} negative rules rejected, and ${postmanRequests.size} Postman requests matched.`,
);
