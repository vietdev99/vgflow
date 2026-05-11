// _test-jsdom-runner.js — runs overlay.js in jsdom, simulates Start→Mark→Submit,
// prints assertions for pytest. Usage: node _test-jsdom-runner.js <path-to-overlay.js>
//
// Auto-installs jsdom via `npm i --no-save jsdom` if missing. Exits 0 on
// success with stdout containing the assertion strings expected by
// test_overlay_mark_flow_via_jsdom.
"use strict";

const fs = require("fs");
const path = require("path");
const cp = require("child_process");
const vm = require("vm");

function ensureJsdom() {
  try {
    require.resolve("jsdom");
  } catch (_e) {
    // Install in repo root so subsequent runs find it.
    const repoRoot = path.resolve(__dirname, "..", "..");
    cp.execSync("npm i --no-save jsdom", { stdio: "inherit", cwd: repoRoot });
  }
}

ensureJsdom();
const { JSDOM } = require("jsdom");

const overlayPath = process.argv[2];
if (!overlayPath) {
  console.error("usage: node _test-jsdom-runner.js <overlay.js>");
  process.exit(64);
}
const overlaySrc = fs.readFileSync(overlayPath, "utf8");

const dom = new JSDOM(
  "<!doctype html><html><head><title>jsdom</title></head><body></body></html>",
  { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true }
);
const { window } = dom;

// Stub alert so overlay's "Click Start first" / "Note required" paths don't throw.
window.alert = function () {};

// Inject overlay via vm.runInContext (runScripts:"outside-only" means DOM scripts
// don't auto-execute — we drive execution from Node's vm instead).
const ctx = dom.getInternalVMContext();
vm.runInContext(overlaySrc, ctx);

// Now simulate user interaction.
function click(id) {
  const el = window.document.getElementById(id);
  if (!el) throw new Error("missing element: " + id);
  el.click();
}

// Sanity check: overlay rendered.
if (!window.document.getElementById("__vg-ft-overlay")) {
  console.error("overlay did not render");
  process.exit(1);
}

// Click Start.
click("__vg-ft-start");
if (window.__VG_FT_STATE.status !== "recording") {
  console.error("expected status=recording after Start, got " + window.__VG_FT_STATE.status);
  process.exit(2);
}
console.log("status=recording");

// Click Mark to open modal.
click("__vg-ft-mark");
if (!window.document.getElementById("__vg-ft-modal")) {
  console.error("modal did not open after Mark click");
  process.exit(3);
}

// Fill note and submit.
const noteEl = window.document.getElementById("__vg-ft-note");
noteEl.value = "found bug";
click("__vg-ft-submit");

// Verify state.
const marks = window.__VG_FT_STATE.marks;
if (marks.length !== 1) {
  console.error("expected marks.length=1, got " + marks.length);
  process.exit(4);
}
console.log("marks.length=" + marks.length);
console.log('user_note="' + marks[0].user_note + '"');

process.exit(0);
