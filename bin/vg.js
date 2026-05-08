#!/usr/bin/env node
/**
 * vgflow CLI entry point.
 *
 * Resolves the package root, then dispatches to the bash dispatcher
 * `bin/vg-cli-dispatcher.sh` with VG_HOME exported. Works on POSIX (bash)
 * and Windows (Git Bash).
 *
 * The dispatcher routes sub-commands (install, sync, doctor, etc.) to
 * the appropriate skill or shell script under `~/.vgflow/`.
 */
"use strict";

const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

// VG_HOME = directory containing this package (resolves to npm install path).
const VG_HOME = path.dirname(path.dirname(path.resolve(__filename)));
const dispatcher = path.join(VG_HOME, "bin", "vg-cli-dispatcher.sh");

if (!fs.existsSync(dispatcher)) {
  console.error(`vg: dispatcher missing at ${dispatcher}`);
  console.error("Reinstall: npm install -g vgflow");
  process.exit(1);
}

// Find bash. Windows: prefer Git Bash; POSIX: standard bash.
function findBash() {
  if (os.platform() !== "win32") {
    return "bash";
  }
  const candidates = [
    process.env.VG_BASH,
    "C:\\Program Files\\Git\\bin\\bash.exe",
    "C:\\Program Files (x86)\\Git\\bin\\bash.exe",
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "Programs", "Git", "bin", "bash.exe"),
  ].filter(Boolean);
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return "bash"; // PATH lookup; may resolve to WSL on some Windows setups
}

const bash = findBash();
const env = Object.assign({}, process.env, { VG_HOME });

const child = spawn(bash, [dispatcher, ...process.argv.slice(2)], {
  stdio: "inherit",
  env,
});

child.on("error", (err) => {
  console.error("vg: failed to spawn dispatcher:", err.message);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.exit(128 + (os.constants.signals[signal] || 0));
  }
  process.exit(code != null ? code : 1);
});
