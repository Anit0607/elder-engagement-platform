import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const schemaPath = path.join(workspace, "database", "engagement_platform_v1_schema.sql");
const sql = await readFile(schemaPath, "utf8");
const concurrencyTest = await readFile(
  path.join(workspace, "database", "tests", "test_staff_role_concurrency.py"),
  "utf8",
);
const errors = [];

const requiredTables = [
  "app_users",
  "staff_credentials",
  "user_profiles",
  "auth_sessions",
  "circles",
  "circle_memberships",
  "content_items",
  "content_assets",
  "content_audiences",
  "moderation_decisions",
  "events",
  "event_audiences",
  "notification_preferences",
  "broadcasts",
  "broadcast_audiences",
  "recordings",
  "notification_deliveries",
  "audit_events",
];

for (const table of requiredTables) {
  if (!new RegExp(`CREATE\\s+TABLE\\s+${table}\\s*\\(`, "i").test(sql))
    errors.push(`Required table is missing: ${table}`);
}

for (const forbidden of [
  "CREATE TABLE bookings",
  "CREATE TABLE payments",
  "CREATE TABLE caregivers",
  "CREATE TABLE wallets",
  "CREATE TABLE subscriptions",
]) {
  if (sql.toLowerCase().includes(forbidden.toLowerCase()))
    errors.push(`Excluded legacy capability found: ${forbidden}`);
}

for (const requiredControl of [
  "REFERENCES app_users",
  "moderation_status",
  "quarantined boolean",
  "viewer_cap integer",
  "trace_id varchar",
  "youtube_video_id",
  "^[+][1-9][0-9]{7,14}$",
  "UNIQUE NULLS NOT DISTINCT",
  "circle_memberships_one_active_idx",
  "staff_credentials_role_guard",
  "app_users_staff_role_guard",
  "FOR UPDATE",
]) {
  if (!sql.toLowerCase().includes(requiredControl.toLowerCase()))
    errors.push(`Required control is missing: ${requiredControl}`);
}

for (const forbiddenControl of [
  "phone_e164 ~ '^\\\\+",
  "PRIMARY KEY (circle_id, user_id)",
  "staff_credentials_role_enforced CHECK",
]) {
  if (sql.toLowerCase().includes(forbiddenControl.toLowerCase()))
    errors.push(`Unsafe inherited control found: ${forbiddenControl}`);
}

for (const requiredConcurrencyCase of [
  "test_insert_waits_for_concurrent_demotion",
  "test_demotion_waits_for_concurrent_insert",
  "wait_event_type = 'Lock'",
]) {
  if (!concurrencyTest.includes(requiredConcurrencyCase))
    errors.push(`Required staff-role concurrency case is missing: ${requiredConcurrencyCase}`);
}

const tableNames = [...sql.matchAll(/CREATE\s+TABLE\s+([a-z_][a-z0-9_]*)\s*\(/gi)].map(
  (match) => match[1].toLowerCase(),
);
for (const table of new Set(tableNames)) {
  if (tableNames.filter((name) => name === table).length > 1)
    errors.push(`Duplicate table declaration: ${table}`);
}

if (errors.length) {
  console.error(`Engagement schema validation failed with ${errors.length} issue(s):`);
  for (const error of errors) console.error(`- ${error}`);
  process.exit(1);
}

console.log(
  `Engagement schema validation passed: ${tableNames.length} current-scope tables; excluded legacy table check passed.`,
);
