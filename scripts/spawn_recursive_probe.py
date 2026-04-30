#!/usr/bin/env python3
"""spawn_recursive_probe.py — Phase 2b-2.5 manager dispatcher (v2.40.0).

Eligibility check (6 rules) → classify clickables → pick lenses per element class
→ spawn workers (auto) OR generate prompts (manual) → enforce 8 termination guards.

Task 18 implements the eligibility gate + dry-run plan emission.
Task 19 adds auto-mode worker dispatch (LENS_MAP + build_plan).
Tasks 20-21 add manual mode + manual-run verification.

Eligibility (6 rules — all must pass unless --skip-recursive-probe is set):
  1. .phase-profile declares phase_profile ∈ {feature, feature-legacy, hotfix}
  2. .phase-profile declares surface ∈ {ui, ui-mobile}            (NOT visual-only)
  3. CRUD-SURFACES.md declares ≥1 resource                        (recursive surface exists)
  4. SUMMARY.md / RIPPLE-ANALYSIS lists ≥1 touched_resources entry
     intersecting CRUD-SURFACES (we keep this lenient until Phase 1.D)
  5. surface != 'visual'                                          (already enforced via rule 2)
  6. ENV-CONTRACT.md present, disposable_seed_data: true, all third_party_stubs stubbed

Skip behavior:
  - Failed eligibility writes ``.recursive-probe-skipped.yaml`` audit trail.
  - ``--skip-recursive-probe='<reason>'`` is a hard override and additionally
    surfaces an OVERRIDE-DEBT critical entry on stderr (caller pipeline ingests).

Outputs:
  - ``--dry-run --json`` prints the full eligibility + plan payload to stdout.
  - On failure (eligibility or override), exit code is still 0 — skip is not an
    error. Argument errors return 2.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

ELIGIBLE_PROFILES: set[str] = {"feature", "feature-legacy", "hotfix"}
ELIGIBLE_SURFACES: set[str] = {"ui", "ui-mobile"}
VISUAL_ONLY_SURFACES: set[str] = {"visual", "visual-only"}

# Element-class → list-of-lens mapping (design doc 2026-04-30-v2.40-recursive-lens-probe.md).
LENS_MAP: dict[str, list[str]] = {
    "mutation_button": ["lens-authz-negative", "lens-duplicate-submit", "lens-bfla"],
    "form_trigger": ["lens-input-injection", "lens-mass-assignment", "lens-csrf"],
    "row_action": ["lens-idor", "lens-tenant-boundary"],
    "bulk_action": ["lens-duplicate-submit", "lens-bfla"],
    "modal_trigger": ["lens-modal-state"],
    "file_upload": ["lens-file-upload", "lens-input-injection", "lens-path-traversal"],
    "redirect_url_param": ["lens-open-redirect"],
    "url_fetch_param": ["lens-ssrf"],
    "auth_endpoint": ["lens-auth-jwt", "lens-csrf"],
    "payment_or_workflow": ["lens-business-logic", "lens-duplicate-submit"],
    "error_response": ["lens-info-disclosure"],
    "tab": [],            # no lens — descent only (Phase 2b-2 sub-walker)
    "sub_view_link": [],  # no lens — descent only
    "path_param": ["lens-path-traversal"],
}

# Worker-cap envelope per --mode (guard #1: hard cap on parallel spawns).
MODE_WORKER_CAPS: dict[str, int] = {"light": 15, "deep": 40, "exhaustive": 100}

# Round-robin pool of MCP playwright slots (matches ~/.gemini/settings.json).
MCP_SLOTS: list[str] = [f"playwright{i}" for i in range(1, 6)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_yaml_block(text: str) -> dict[str, Any]:
    """Extract the first ```yaml ... ``` fenced block. Falls back to whole text."""
    m = re.search(r"```ya?ml\s*\n(.+?)\n```", text, re.S)
    payload = m.group(1) if m else text
    try:
        data = yaml.safe_load(payload)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_json_block(text: str) -> dict[str, Any]:
    """Extract the first ```json ... ``` fenced block."""
    m = re.search(r"```json\s*\n(.+?)\n```", text, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _load_phase_profile(phase_dir: Path) -> dict[str, Any]:
    f = phase_dir / ".phase-profile"
    if not f.is_file():
        return {}
    text = f.read_text(encoding="utf-8", errors="replace")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _load_crud_resources(phase_dir: Path) -> list[dict[str, Any]]:
    f = phase_dir / "CRUD-SURFACES.md"
    if not f.is_file():
        return []
    text = f.read_text(encoding="utf-8", errors="replace")
    data = _read_json_block(text)
    resources = data.get("resources") if data else None
    if isinstance(resources, list):
        return [r for r in resources if isinstance(r, dict)]
    # Fallback: legacy fixture syntax with bare "name:" YAML lines.
    if "name:" in text:
        return [{"name": "<unparsed>"}]
    return []


def _load_touched_resources(phase_dir: Path) -> list[str]:
    """Best-effort touched_resources lookup from SUMMARY.md or RIPPLE-ANALYSIS.md.

    Until Phase 1.D locks the schema, we accept any of these shapes:
      - YAML fenced block with ``touched_resources: [list]``
      - Bare ``touched_resources: [list]`` line
    """
    for name in ("SUMMARY.md", "RIPPLE-ANALYSIS.md"):
        f = phase_dir / name
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        data = _read_yaml_block(text)
        tr = data.get("touched_resources")
        if isinstance(tr, list):
            return [str(x) for x in tr]
        # Bare-line fallback (e.g. "touched_resources: ['topup_requests']").
        m = re.search(r"touched_resources:\s*\[(.+?)\]", text)
        if m:
            return [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]
    return []


def _check_env_contract(phase_dir: Path) -> tuple[bool, list[str]]:
    """Return (ok, reasons). Verifies disposable seed + all stubs are stubbed."""
    reasons: list[str] = []
    f = phase_dir / "ENV-CONTRACT.md"
    if not f.is_file():
        return False, ["ENV-CONTRACT.md missing (rule 6)"]
    text = f.read_text(encoding="utf-8", errors="replace")
    data = _read_yaml_block(text)
    if not data:
        return False, ["ENV-CONTRACT.md has no parseable YAML body"]

    if data.get("disposable_seed_data") is not True:
        reasons.append("ENV-CONTRACT.md disposable_seed_data not true")

    stubs = data.get("third_party_stubs") or {}
    if isinstance(stubs, dict) and stubs:
        unstubbed = [k for k, v in stubs.items()
                     if str(v).strip().lower() not in {"stubbed", "stub", "mock"}]
        if unstubbed:
            reasons.append(
                f"ENV-CONTRACT.md third_party_stubs not stubbed: {sorted(unstubbed)}"
            )
    return len(reasons) == 0, reasons


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------
def check_eligibility(phase_dir: Path,
                      override_reason: str | None) -> dict[str, Any]:
    """Run the 6-rule eligibility gate. Returns a JSON-friendly dict."""
    if override_reason:
        return {
            "passed": False,
            "skipped_via_override": True,
            "reasons": [f"override: {override_reason}"],
        }

    reasons: list[str] = []
    profile_data = _load_phase_profile(phase_dir)
    profile = str(profile_data.get("phase_profile", ""))
    surface = str(profile_data.get("surface", ""))

    # Rule 1: phase_profile
    if profile not in ELIGIBLE_PROFILES:
        reasons.append(
            f"phase_profile '{profile}' not in {sorted(ELIGIBLE_PROFILES)}"
        )

    # Rule 2 + 5: surface eligible AND not visual-only
    if surface in VISUAL_ONLY_SURFACES:
        reasons.append(f"surface '{surface}' is visual-only (rule 5)")
    elif surface not in ELIGIBLE_SURFACES:
        reasons.append(
            f"surface '{surface}' not in {sorted(ELIGIBLE_SURFACES)}"
        )

    # Rule 3: CRUD-SURFACES has resources
    resources = _load_crud_resources(phase_dir)
    if not resources:
        reasons.append("CRUD-SURFACES.md declares 0 resources")

    # Rule 4: touched_resources intersects CRUD-SURFACES
    touched = _load_touched_resources(phase_dir)
    if resources and touched:
        crud_names = {str(r.get("name", "")) for r in resources}
        if not (set(touched) & crud_names) and "<unparsed>" not in crud_names:
            reasons.append(
                f"touched_resources {touched} does not intersect CRUD names {sorted(crud_names)}"
            )
    # If touched_resources missing entirely, we keep gate lenient (Phase 1.D
    # will tighten this once SUMMARY.md schema locks).

    # Rule 6: ENV-CONTRACT.md
    env_ok, env_reasons = _check_env_contract(phase_dir)
    if not env_ok:
        reasons.extend(env_reasons)

    return {
        "passed": not reasons,
        "skipped_via_override": False,
        "reasons": reasons,
    }


def write_skip_evidence(phase_dir: Path, eligibility: dict[str, Any]) -> Path:
    out = phase_dir / ".recursive-probe-skipped.yaml"
    payload = {
        "skipped_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "reasons": eligibility["reasons"],
        "via_override": bool(eligibility.get("skipped_via_override", False)),
    }
    out.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return out


def log_override_debt(reason: str) -> None:
    """Surface OVERRIDE-DEBT critical to stderr — caller pipeline aggregates."""
    sys.stderr.write(
        f"OVERRIDE-DEBT critical: --skip-recursive-probe used; reason={reason!r}\n"
    )


# ---------------------------------------------------------------------------
# Plan composition (Task 19)
# ---------------------------------------------------------------------------
def build_plan(classification: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    """Convert a classification list into a deduped, capped spawn plan.

    Args:
        classification: ``[{element_class, selector, view, resource, ...}, ...]``
            shaped per ``identify_interesting_clickables.py``.
        mode: ``light`` / ``deep`` / ``exhaustive`` (selects MODE_WORKER_CAPS).

    Returns:
        ``[{element, lens, scope_key}, ...]`` truncated to the mode cap with
        guard #7 idempotency dedupe applied (same resource × role × lens once).
    """
    raw: list[dict[str, Any]] = []
    for c in classification:
        ec = c.get("element_class", "")
        for lens in LENS_MAP.get(ec, []):
            raw.append({
                "element": c,
                "lens": lens,
                "scope_key": (
                    c.get("resource", ""),
                    c.get("role", "admin"),
                    lens,
                ),
            })

    seen: set[tuple[Any, Any, Any]] = set()
    deduped: list[dict[str, Any]] = []
    for entry in raw:
        if entry["scope_key"] in seen:
            continue
        seen.add(entry["scope_key"])
        deduped.append(entry)

    cap = MODE_WORKER_CAPS.get(mode, MODE_WORKER_CAPS["light"])
    return deduped[:cap]


def _classify_phase(phase_dir: Path) -> list[dict[str, Any]]:
    """Run identify_interesting_clickables.py → recursive-classification.json."""
    scan_files = sorted(phase_dir.glob("scan-*.json"))
    if not scan_files:
        return []
    out_path = phase_dir / "recursive-classification.json"
    classifier = REPO_ROOT / "scripts" / "identify_interesting_clickables.py"
    cmd: list[str] = [
        sys.executable, str(classifier),
        "--scan-files", *(str(p) for p in scan_files),
        "--output", str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    data = json.loads(out_path.read_text(encoding="utf-8"))
    clickables = data.get("clickables", [])
    return clickables if isinstance(clickables, list) else []


def _output_basename(entry: dict[str, Any]) -> str:
    """Stable filename component: ``recursive-{lens}-{selector_hash}-d{depth}``."""
    elem = entry.get("element", {})
    sh = elem.get("selector_hash") or elem.get("selector", "unknown")
    sh = re.sub(r"[^a-zA-Z0-9_-]", "_", str(sh))[:24]
    lens = str(entry.get("lens", "lens-unknown"))
    return f"recursive-{lens}-{sh}-d1"


def spawn_one_worker(entry: dict[str, Any], phase_dir: Path,
                     mcp_slot: str, *, model: str = "gemini-2.5-flash",
                     timeout: int = 600) -> dict[str, Any]:
    """Spawn a single Gemini Flash worker for one (element × lens) probe.

    Mirrors ``scripts/spawn-crud-roundtrip.py:spawn_worker`` — same shape, same
    redaction discipline. Returns a result dict (exit_code + duration) but does
    NOT raise; caller aggregates failures into an INDEX.json.
    """
    elem = entry.get("element", {})
    lens = entry.get("lens", "lens-unknown")
    runs_dir = phase_dir / "runs" / mcp_slot
    runs_dir.mkdir(parents=True, exist_ok=True)
    output_path = runs_dir / f"{_output_basename(entry)}.json"

    context_block = {
        "element_class": elem.get("element_class"),
        "selector": elem.get("selector"),
        "view": elem.get("view"),
        "resource": elem.get("resource"),
        "lens": lens,
        "metadata": elem.get("metadata", {}),
        "output_path": str(output_path),
    }
    prompt = (
        f"You are running the {lens} recursive-lens probe on a UI clickable.\n"
        "Use the playwright MCP tools to interact with the target element and "
        "record the network log + step trace.\n\n"
        "## CONTEXT\n```json\n"
        + json.dumps(context_block, indent=2)
        + "\n```\nWrite the run artifact JSON to OUTPUT_PATH and return briefly."
    )

    cmd: list[str] = [
        "gemini", "-p", prompt, "-m", model,
        "--approval-mode", "yolo",
        "--allowed-mcp-server-names", mcp_slot,
    ]
    started = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "exit_code": result.returncode,
            "duration_seconds": round(time.time() - started, 1),
            "output_path": str(output_path),
            "mcp_slot": mcp_slot,
            "lens": lens,
            "selector": elem.get("selector"),
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "duration_seconds": timeout,
            "output_path": str(output_path),
            "mcp_slot": mcp_slot,
            "lens": lens,
            "selector": elem.get("selector"),
            "error": "timeout",
        }
    except FileNotFoundError:
        return {
            "exit_code": -2,
            "duration_seconds": round(time.time() - started, 1),
            "output_path": str(output_path),
            "mcp_slot": mcp_slot,
            "lens": lens,
            "selector": elem.get("selector"),
            "error": "gemini binary not on PATH",
        }


def dispatch_auto(plan: list[dict[str, Any]], phase_dir: Path) -> list[dict[str, Any]]:
    """Spawn one worker per plan entry, round-robin across MCP slots."""
    results: list[dict[str, Any]] = []
    for i, entry in enumerate(plan):
        slot = MCP_SLOTS[i % len(MCP_SLOTS)]
        results.append(spawn_one_worker(entry, phase_dir, mcp_slot=slot))
    return results


def dispatch_manual(plan: list[dict[str, Any]], phase_dir: Path,
                    mode: str) -> int:
    """Hand the plan off to ``generate_recursive_prompts.py`` (Task 20)."""
    generator = REPO_ROOT / "scripts" / "generate_recursive_prompts.py"
    if not generator.is_file():
        sys.stderr.write(
            "manual mode requires scripts/generate_recursive_prompts.py (Task 20)\n"
        )
        return 1
    r = subprocess.run([
        sys.executable, str(generator),
        "--phase-dir", str(phase_dir),
        "--mode", mode,
        "--plan-json", json.dumps(plan, default=list),
    ], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="spawn_recursive_probe.py",
        description="Phase 2b-2.5 manager — eligibility + (Task 19) dispatch.",
    )
    ap.add_argument("--phase-dir", required=True,
                    help="Absolute path to the phase directory.")
    ap.add_argument("--mode", choices=["light", "deep", "exhaustive"],
                    default="light",
                    help="Worker-cap envelope (light=15, deep=40, exhaustive=100).")
    ap.add_argument("--probe-mode", choices=["auto", "manual", "hybrid"],
                    default="auto",
                    help="Spawn strategy (Task 19+).")
    ap.add_argument("--skip-recursive-probe", default=None,
                    metavar="REASON",
                    help="Override reason; logs OVERRIDE-DEBT critical.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the plan as JSON and exit; do not spawn.")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON on stdout.")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        sys.stderr.write(f"phase dir not found: {phase_dir}\n")
        return 2

    eligibility = check_eligibility(phase_dir, args.skip_recursive_probe)
    payload: dict[str, Any] = {
        "phase_dir": str(phase_dir),
        "mode": args.mode,
        "probe_mode": args.probe_mode,
        "eligibility": eligibility,
    }

    if not eligibility["passed"]:
        # Always write skip evidence — the audit trail is the same whether the
        # caller is dry-running or doing a real run.
        write_skip_evidence(phase_dir, eligibility)
        if eligibility.get("skipped_via_override") and args.skip_recursive_probe:
            log_override_debt(args.skip_recursive_probe)
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Recursive probe skipped: {', '.join(eligibility['reasons'])}")
        return 0

    # ------------------------------------------------------------------
    # Eligibility passed → classify + build plan (Task 19).
    # ------------------------------------------------------------------
    try:
        classification = _classify_phase(phase_dir)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            f"identify_interesting_clickables.py failed (rc={exc.returncode}):\n"
            f"{exc.stderr or ''}\n"
        )
        return 1

    plan = build_plan(classification, args.mode)
    payload["planned_spawns"] = [
        {
            "element_class": entry["element"].get("element_class"),
            "selector": entry["element"].get("selector"),
            "view": entry["element"].get("view"),
            "resource": entry["element"].get("resource"),
            "lens": entry["lens"],
        }
        for entry in plan
    ]

    if args.dry_run:
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"Eligibility passed. mode={args.mode} probe-mode={args.probe_mode} "
                f"plan={len(plan)} spawns"
            )
        return 0

    # ------------------------------------------------------------------
    # Real run — dispatch per probe-mode.
    # ------------------------------------------------------------------
    if args.probe_mode == "auto":
        results = dispatch_auto(plan, phase_dir)
        index_path = phase_dir / "runs" / "INDEX.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(
            json.dumps({"plan": payload["planned_spawns"], "results": results}, indent=2),
            encoding="utf-8",
        )
        print(f"Auto dispatch complete: {len(results)} workers, index={index_path}")
        return 0

    if args.probe_mode == "manual":
        return dispatch_manual(plan, phase_dir, args.mode)

    # hybrid: split via vg.config hybrid_routing — defer to Task 26 wiring;
    # for now run auto for everything (safe default).
    sys.stderr.write(
        "hybrid probe-mode falls back to auto until Phase 1.D vg.config wiring lands.\n"
    )
    results = dispatch_auto(plan, phase_dir)
    print(f"Hybrid (auto-fallback) dispatch complete: {len(results)} workers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
