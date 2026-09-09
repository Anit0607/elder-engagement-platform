import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseEnv, validateConfig } from "../../../config/engagement/validation.mjs";

const directory = path.dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(fs.readFileSync(path.join(directory, "fixtures", "config-parity.json"), "utf8"));

for (const entry of fixture.cases) {
  test(`shared config parity: ${entry.name}`, () => {
    const errors = validateConfig(parseEnv(entry.env));
    assert.equal(errors.length === 0, entry.valid, errors.join("; "));
  });
}

for (const key of fixture.requiredCoreSecretRefs) {
  test(`shared config parity rejects empty ${key}`, () => {
    const values = parseEnv(fixture.cases[0].env);
    values[key] = "";
    assert.notEqual(validateConfig(values).length, 0);
  });
}
