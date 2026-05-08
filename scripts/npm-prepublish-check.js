#!/usr/bin/env node
/**
 * Pre-publish gate — runs before `npm publish`.
 *
 * Verifies:
 *   - VERSION file matches package.json version
 *   - No uncommitted changes (warn only)
 *   - Required files exist
 *
 * Exits non-zero on hard failures. Aborts publish.
 */
"use strict";

const path = require("path");
const fs = require("fs");
const { execSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
const versionFile = fs.readFileSync(path.join(ROOT, "VERSION"), "utf8").trim();

if (pkg.version !== versionFile) {
  console.error(`prepublish: package.json version (${pkg.version}) != VERSION file (${versionFile})`);
  console.error("Run: node -e 'const fs=require(\"fs\"); const v=fs.readFileSync(\"VERSION\",\"utf8\").trim(); const p=JSON.parse(fs.readFileSync(\"package.json\",\"utf8\")); p.version=v; fs.writeFileSync(\"package.json\", JSON.stringify(p,null,2)+\"\\n\");'");
  process.exit(1);
}

const requiredFiles = [
  "bin/vg.js",
  "bin/vg-cli-dispatcher.sh",
  "VERSION",
  "VGFLOW-VERSION",
  "LICENSE",
  "README.md",
];
for (const f of requiredFiles) {
  const p = path.join(ROOT, f);
  if (!fs.existsSync(p)) {
    console.error(`prepublish: missing required file ${f}`);
    process.exit(1);
  }
}

try {
  const status = execSync("git status --porcelain", { cwd: ROOT, encoding: "utf8" });
  if (status.trim()) {
    console.warn("prepublish: WARNING — uncommitted changes:");
    console.warn(status);
    console.warn("Continuing anyway. Hit Ctrl+C to abort.");
  }
} catch (e) {
  // not a git repo — skip
}

console.log(`prepublish: vgflow ${pkg.version} ready to publish`);
