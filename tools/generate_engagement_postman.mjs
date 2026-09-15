import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputDirectory = path.join(workspace, "api", "postman");
const outputPath = path.join(
  outputDirectory,
  "Elder_Engage_Sprint3_Draft.postman_collection.json",
);

const jsonHeaders = [{ key: "Content-Type", value: "application/json" }];
const bearer = {
  type: "bearer",
  bearer: [{ key: "token", value: "{{accessToken}}", type: "string" }],
};
const body = (value) => ({
  mode: "raw",
  raw: JSON.stringify(value, null, 2),
  options: { raw: { language: "json" } },
});
const request = (name, method, url, options = {}) => {
  const [route, queryText] = url.split("?", 2);
  const query = queryText
    ? queryText.split("&").map((part) => {
        const [key, value = ""] = part.split("=", 2);
        return { key, value };
      })
    : [];
  return {
    name,
    request: {
      method,
      header: options.headers ?? (options.body ? jsonHeaders : []),
      ...(options.public ? { auth: { type: "noauth" } } : { auth: bearer }),
      ...(options.body ? { body: body(options.body) } : {}),
      url: {
        raw: `{{baseUrl}}${url}`,
        host: ["{{baseUrl}}"],
        path: route.split("/").filter(Boolean),
        ...(query.length ? { query } : {}),
      },
      description:
        options.description ??
        "Contract-only request. It is not claimed callable until the matching backend is deployed and verified.",
    },
  };
};

const collection = {
  info: {
    _postman_id: "5b4e91aa-1971-4bc1-9092-1ccbd4e217d9",
    name: "Elder Engage Sprint 3 REST Draft",
    description:
      "Safe synthetic companion to elder-engage-v1.openapi.json. The deployment record, not this collection, determines which operations are callable. Never insert a production credential before importing this collection into an approved private workspace.",
    schema: "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
  },
  variable: [
    { key: "baseUrl", value: "http://127.0.0.1:8000", type: "string" },
    { key: "accessToken", value: "", type: "string" },
    { key: "refreshToken", value: "", type: "string" },
    { key: "providerIdToken", value: "synthetic-provider-token-not-a-real-secret", type: "string" },
    { key: "userId", value: "11111111-1111-4111-8111-111111111111", type: "string" },
    { key: "sessionId", value: "44444444-4444-4444-8444-444444444444", type: "string" },
    { key: "uploadId", value: "55555555-5555-4555-8555-555555555555", type: "string" },
    { key: "circleId", value: "66666666-6666-4666-8666-666666666666", type: "string" },
    { key: "contentItemId", value: "77777777-7777-4777-8777-777777777777", type: "string" },
  ],
  item: [
    {
      name: "Operations",
      item: [
        request("Health", "GET", "/health", { public: true }),
        request("Readiness", "GET", "/ready", { public: true }),
      ],
    },
    {
      name: "Authentication",
      item: [
        request("Create Member session", "POST", "/v1/auth/member/session", {
          public: true,
          body: {
            providerIdToken: "{{providerIdToken}}",
            installationId: "22222222-2222-4222-8222-222222222222",
            platform: "ios",
            deviceName: "iOS contract-test device",
          },
        }),
        request("Create Contributor session", "POST", "/v1/auth/staff/session", {
          public: true,
          body: {
            username: "synthetic.contributor",
            password: "not-a-real-password-value",
            installationId: "33333333-3333-4333-8333-333333333333",
            platform: "ios",
            deviceName: "iOS contract-test device",
          },
        }),
        request("Refresh session", "POST", "/v1/auth/refresh", {
          public: true,
          body: { refreshToken: "{{refreshToken}}" },
          description:
            "Serialize this operation. After an uncertain outcome, do not retry the same refresh token; clear local tokens and return to sign-in because no recovery/status operation exists in this draft.",
        }),
        request("Logout", "POST", "/v1/auth/logout", {
          description: "A successful response is HTTP 204 with no body.",
        }),
      ],
    },
    {
      name: "Profile and sessions",
      item: [
        request("Get my profile", "GET", "/v1/me/profile"),
        request("Update my profile", "PATCH", "/v1/me/profile", {
          headers: jsonHeaders,
          body: {
            preferredLanguage: "hi",
            notificationWindow: {
              enabled: true,
              startLocalTime: "20:00",
              endLocalTime: "08:00",
              timeZone: "Asia/Kolkata",
            },
          },
        }),
        request("Start profile-photo upload", "POST", "/v1/me/profile/photo-upload", {
          body: {
            contentType: "image/jpeg",
            sizeBytes: 102400,
            sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          },
        }),
        request(
          "Complete profile-photo upload",
          "POST",
          "/v1/me/profile/photo-upload/{{uploadId}}/complete",
        ),
        request("Get my notification preferences", "GET", "/v1/me/notification-preferences", {
          description: "Returns only the signed-in account's notification choices.",
        }),
        request(
          "Replace my notification preferences",
          "PUT",
          "/v1/me/notification-preferences",
          {
            body: {
              eventReminders: true,
              contentUpdates: false,
              deliveryWindow: {
                enabled: true,
                startLocalTime: "22:00",
                endLocalTime: "06:00",
                timeZone: "Asia/Kolkata",
              },
            },
            description:
              "Replaces the complete set of notification choices for the signed-in account.",
          },
        ),
        request("List my sessions", "GET", "/v1/me/sessions"),
        request("Revoke one session", "DELETE", "/v1/me/sessions/{{sessionId}}", {
          description: "A successful response is HTTP 204 with no body.",
        }),
      ],
    },
    {
      name: "Circles",
      item: [
        request("List my circles and suggestions", "GET", "/v1/me/circles"),
        request("Join a circle", "POST", "/v1/me/circles/{{circleId}}/membership", {
          description: "A successful response is HTTP 204 with no body.",
        }),
        request("Leave a circle", "DELETE", "/v1/me/circles/{{circleId}}/membership", {
          description: "A successful response is HTTP 204 with no body.",
        }),
      ],
    },
    {
      name: "Contributor content",
      item: [
        request("Start private PDF upload", "POST", "/v1/contributor/content-uploads", {
          body: {
            title: "Synthetic activity guide",
            description: "Fictional content used only for contract testing",
            language: "en",
            contentType: "application/pdf",
            sizeBytes: 32768,
            sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            rightsConfirmed: true,
          },
          description:
            "Contributor only. Save the returned short-lived upload URL only until the direct private upload finishes; never log it.",
        }),
        request(
          "Complete private content upload",
          "POST",
          "/v1/contributor/content-uploads/{{uploadId}}/complete",
          {
            description:
              "Validates the private object and records pending moderation. It does not publish the content.",
          },
        ),
      ],
    },
    {
      name: "Member content feed",
      item: [
        request("List my visible content", "GET", "/v1/feed?limit=20", {
          description:
            "Member only. Returns approved and published items allowed for all Members or one of the Member's active circles.",
        }),
        request(
          "Open visible content media",
          "GET",
          "/v1/feed/{{contentItemId}}/media",
          {
            description:
              "Rechecks current circle access and returns a sensitive five-minute private media link. Do not log or retain it.",
          },
        ),
      ],
    },
    {
      name: "Administration",
      item: [
        request("List pending content", "GET", "/v1/admin/content-moderation"),
        request(
          "Preview pending content",
          "GET",
          "/v1/admin/content-moderation/{{contentItemId}}/preview",
        ),
        request(
          "Approve pending content",
          "POST",
          "/v1/admin/content-moderation/{{contentItemId}}/decision",
          {
            body: { outcome: "approved", reasonCode: "approved" },
            description: "Records the Administrator decision but does not publish the content.",
          },
        ),
        request(
          "Publish approved content to one circle",
          "POST",
          "/v1/admin/content/{{contentItemId}}/publication",
          {
            body: { audience: "circles", circleIds: ["{{circleId}}"] },
            description:
              "Moves one approved clean file from quarantine to private approved storage and records the controlled audience.",
          },
        ),
        request("List users", "GET", "/v1/admin/users?limit=25"),
        request("Create Member profile", "POST", "/v1/admin/users", {
          body: {
            role: "member",
            phoneE164: "+919999999901",
            displayName: "Synthetic Member",
            preferredLanguage: "bn",
            interests: ["music"],
            notificationWindow: { enabled: false, timeZone: "Asia/Kolkata" },
          },
        }),
        request("Suspend user", "PATCH", "/v1/admin/users/{{userId}}/status", {
          body: { status: "suspended", reason: "Synthetic contract test" },
        }),
        request("Change user role", "PATCH", "/v1/admin/users/{{userId}}/role", {
          body: { role: "contributor", reason: "Synthetic contract test" },
        }),
        request("List all circles", "GET", "/v1/admin/circles"),
        request("Create circle", "POST", "/v1/admin/circles", {
          body: {
            name: "Synthetic music circle",
            description: "Synthetic contract example",
            suggestionRules: { interests: ["music"], preferredLanguages: ["bn"] },
          },
        }),
        request("Update circle", "PATCH", "/v1/admin/circles/{{circleId}}", {
          body: { active: false },
        }),
        request(
          "Assign Member to circle",
          "POST",
          "/v1/admin/users/{{userId}}/circles/{{circleId}}/membership",
          { description: "A successful response is HTTP 204 with no body." },
        ),
        request(
          "Remove Member from circle",
          "DELETE",
          "/v1/admin/users/{{userId}}/circles/{{circleId}}/membership",
          { description: "A successful response is HTTP 204 with no body." },
        ),
        request("Get circle settings", "GET", "/v1/admin/circle-settings"),
        request("Change circle membership limit", "PUT", "/v1/admin/circle-settings", {
          body: { maxMemberships: 5 },
        }),
      ],
    },
  ],
};

await mkdir(outputDirectory, { recursive: true });
await writeFile(outputPath, `${JSON.stringify(collection, null, 2)}\n`, "utf8");
console.log(`Generated ${outputPath}`);
