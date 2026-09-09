import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { validateFile } from "../config/engagement/validation.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const example = path.join(root, "config", "engagement", ".env.example");
const errors = validateFile(example);

if (errors.length) {
  console.error("Engagement configuration validation failed:");
  for (const error of errors) console.error(`- ${error}`);
  process.exitCode = 1;
} else {
  console.log("Engagement configuration example is valid and contains references only.");
}
