#!/usr/bin/env node
/**
 * npm postinstall hook — runs after `npm install -g vgflow`.
 *
 * Conservative behavior: do NOT auto-modify ~/.claude/settings.json.
 * Print install location + next-step prompt. Side-effect-free.
 */
"use strict";

const path = require("path");
const fs = require("fs");

const VG_HOME = path.dirname(__dirname);
const versionFile = path.join(VG_HOME, "VERSION");
const version = fs.existsSync(versionFile)
  ? fs.readFileSync(versionFile, "utf8").trim()
  : "unknown";

if (process.env.CI === "true" || process.env.VG_SKIP_POSTINSTALL) {
  console.log(`vgflow ${version} installed at ${VG_HOME} (postinstall skipped: CI/VG_SKIP_POSTINSTALL)`);
  process.exit(0);
}

console.log("");
console.log(`  vgflow ${version}`);
console.log(`  Installed at: ${VG_HOME}`);
console.log("");
console.log("  Next steps:");
console.log("    vg install          # wire global hooks + prune project-local VG files");
console.log("    vg doctor           # verify install");
console.log("    vg help             # full command list");
console.log("");
console.log("  Documentation: https://github.com/vietdev99/vgflow");
console.log("");
