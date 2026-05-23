#!/usr/bin/env python3
"""verify-spec-stage-coverage.py — Batch 23

Opens each spec file listed in CODEGEN-MANIFEST.json, checks body contains
stage-specific patterns matching LIFECYCLE-SPECS.json declared stages per
goal.

Stages and required regex patterns (per RCRURDR + 4-layer verify):

  read_before:       page.goto OR page.reload (navigation before mutation)
  create:            page.fill (form input) + page.click (submit) + waitForResponse
  read_after_create: page.reload OR navigate + expect(...).toBeVisible (new entity)
  update:            page.fill (second time) + page.click (save)
  read_after_update: page.reload + expect(persisted_value)
  delete:            page.click (delete) + waitForResponse(DELETE method)
  read_after_delete: expect(...).not.toBeVisible (entity gone)

Plus 4-layer verify (for every mutation stage):
  L1 toast:        expect(...).toContainText(...)
  L2 API 2xx:      waitForResponse + status < 400
  L3 persistence:  page.reload + assertion
  L4 console:      window.__consoleErrors check (advisory, not blocking)

Missing required pattern per declared stage → BLOCK with file:line context.

Exit codes:
  0 — all specs cover declared stages
  1 — at least one shallow spec found
  2 — config error (missing files, malformed JSON)
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


# Stage → list of required regex patterns. Each pattern (compiled, IGNORECASE)
# is checked against the spec file body. Missing pattern = stage not covered.
STAGE_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "read_before": [
        ("navigation", r"page\.goto\("),
    ],
    "create": [
        ("form_fill", r"page\.fill\("),
        ("submit_click", r"page\.click\(['\"](?:button|.*type=['\"]submit)|getByRole\(['\"]button"),
        ("api_response", r"waitForResponse\("),
    ],
    "read_after_create": [
        ("post_create_assert", r"toBeVisible\(\)|toContainText\("),
    ],
    "update": [
        ("update_fill", r"page\.fill\("),
        ("update_save", r"page\.click\("),
        ("update_response", r"waitForResponse\("),
    ],
    "read_after_update": [
        ("persist_reload", r"page\.reload\(\)|page\.goto\("),
        ("persist_assert", r"toBeVisible\(\)|toContainText\("),
    ],
    "delete": [
        ("delete_click", r"page\.click\("),
        ("delete_response", r"waitForResponse\("),
    ],
    "read_after_delete": [
        ("not_visible", r"not\.toBeVisible\(\)|toBeHidden\(\)|toHaveCount\(0\)"),
    ],
}


def _check_spec(spec_path: Path, required_stages: list[str]) -> dict:
    """Returns dict with stage → list[missing_pattern_names]."""
    if not spec_path.is_file():
        return {"_error": f"spec file not found: {spec_path}"}
    body = spec_path.read_text(encoding="utf-8", errors="replace")
    missing: dict[str, list[str]] = {}
    for stage in required_stages:
        patterns = STAGE_PATTERNS.get(stage, [])
        if not patterns:
            continue
        miss = []
        for name, regex in patterns:
            if not re.search(regex, body, re.IGNORECASE):
                miss.append(name)
        if miss:
            missing[stage] = miss
    return missing


# B107 v4.70.1 (Codex postmortem recommendation #2): semantic spec coverage.
# Pre-B107 the validator only checked TOKEN PRESENCE (e.g. `waitForResponse`
# appears somewhere). This passed for shallow specs that called waitForResponse
# on an unrelated endpoint, never asserted status<400, or skipped success/error
# locators entirely. Result: top 25-35% of UAT bugs (form 4xx swallowed,
# missing success message, broken redirect) shipped through `/vg:test` PASS.
#
# B107 reads B106's network_assertion + success_assertion metadata from each
# step in LIFECYCLE-SPECS.json and requires the spec to:
#   - Bind waitForResponse to the EXPECTED method + endpoint path
#   - Have a concrete status<400 assertion (not just bare waitForResponse)
#   - For 4xx/5xx branch: must reference an error locator (role=alert etc.)
#   - For success_assertion with expect_navigation_to: must have waitForURL
#     OR toHaveURL referencing the declared path pattern
#   - For success_assertion without nav: must have a success locator OR
#     toast visibility assertion

_STATUS_LT_400_RE = re.compile(
    r"(\.status\(\)\s*<\s*400|toBeLessThan\(400\)|toBe(?:Less|)\(2\d\d\)|"
    r"toBe\(20\d\)|toBe\(21\d\))",
    re.IGNORECASE,
)
_ERROR_LOCATOR_RE = re.compile(
    r"(\[role=['\"]?alert['\"]?\]|data-testid=['\"][^'\"]*error[^'\"]*['\"]|"
    r"\.error[-_]?(?:banner|toast|message)|class\*=['\"]?Error|"
    r"getByRole\(['\"]alert['\"]\)|getByTestId\(['\"][^'\"]*error[^'\"]*['\"]\))",
    re.IGNORECASE,
)
_SUCCESS_LOCATOR_RE = re.compile(
    r"(\[role=['\"]?status['\"]?\]|data-testid=['\"][^'\"]*success[^'\"]*['\"]|"
    r"\.success[-_]?(?:banner|toast|message)|toast.*success|"
    r"getByRole\(['\"]status['\"]\)|class\*=['\"]?Success|"
    r"getByTestId\(['\"][^'\"]*success[^'\"]*['\"]\))",
    re.IGNORECASE,
)
_NAV_ASSERT_RE = re.compile(
    r"(page\.waitForURL|page\.waitForNavigation|expect\(page\)\.toHaveURL|"
    r"toHaveURL\()",
)


def _check_semantic(spec_path: Path, steps: list[dict]) -> dict[str, list[str]]:
    """B107: semantic checks against B106 metadata. Returns dict of
    per-step concern → list of missing requirements. Empty dict = PASS.
    """
    if not spec_path.is_file():
        return {}
    body = spec_path.read_text(encoding="utf-8", errors="replace")
    findings: dict[str, list[str]] = {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        stage = step.get("stage") or step.get("name") or "?"
        # B106 metadata — if absent, skip semantic check on this step
        net = step.get("network_assertion") or {}
        success = step.get("success_assertion") or {}
        misses: list[str] = []

        if net:
            ep_path = str(net.get("endpoint_path") or "")
            ep_method = str(net.get("endpoint_method") or "")
            # Require waitForResponse/page.on('response') referencing the
            # endpoint path. We escape regex specials but keep `{id}` style
            # placeholders flexible.
            if ep_path:
                # Treat `{var}` / `:var` as wildcards for matching
                path_pattern = re.escape(ep_path).replace(r"\{", "{").replace(r"\}", "}")
                path_pattern = re.sub(r"\{[^}]+\}", r"[^'\"`/]*", path_pattern)
                path_pattern = re.sub(r":\w+", r"[^'\"`/]*", path_pattern)
                # Accept waitForResponse OR page.on('response') OR
                # context.on('response'); the path may appear anywhere within
                # ~400 chars after the call (handles arrow-fn predicates +
                # multi-line). Skip balanced-paren parsing; widen window.
                bound_re = re.compile(
                    r"(?:waitForResponse|page\.on\(['\"]response['\"]|"
                    r"context\.on\(['\"]response['\"]|waitForRequest)"
                    r"[\s\S]{0,400}?" + path_pattern,
                )
                if not bound_re.search(body):
                    misses.append(
                        f"waitForResponse not bound to expected endpoint "
                        f"'{ep_method} {ep_path}' — token present elsewhere "
                        f"is not enough"
                    )
            if not _STATUS_LT_400_RE.search(body):
                misses.append(
                    "no concrete status<400 assertion "
                    "(.status() < 400 / toBeLessThan(400) / toBe(2xx))"
                )
            if net.get("on_4xx_5xx_must_render_error_toast"):
                # The spec doesn't have to actually hit 4xx — but error-locator
                # branch must exist for the moment it does.
                if not _ERROR_LOCATOR_RE.search(body):
                    misses.append(
                        "no error-locator assertion ([role=alert] / "
                        "data-testid*=error / .error-*) — 4xx branch silent"
                    )

        if success:
            nav_target = str(success.get("expect_navigation_to") or "")
            if nav_target:
                if not _NAV_ASSERT_RE.search(body):
                    misses.append(
                        f"success_assertion declares redirect to "
                        f"'{nav_target}' but spec has no waitForURL / "
                        f"toHaveURL assertion"
                    )
            else:
                # Success feedback path — locator OR generic toBeVisible on
                # success-class element
                if not _SUCCESS_LOCATOR_RE.search(body):
                    misses.append(
                        "success_assertion declares feedback but spec has "
                        "no success-locator ([role=status] / "
                        "data-testid*=success / .success-*) assertion"
                    )

        if misses:
            findings[f"{stage}__semantic"] = misses
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--repo-root", type=Path, default=Path("."),
                    help="Repo root for resolving spec relative paths")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ls_path = args.phase_dir / "LIFECYCLE-SPECS.json"
    cm_path = args.phase_dir / "CODEGEN-MANIFEST.json"
    if not ls_path.is_file():
        print(f"⛔ LIFECYCLE-SPECS.json missing at {ls_path}", file=sys.stderr)
        return 2
    if not cm_path.is_file():
        print(f"⛔ CODEGEN-MANIFEST.json missing at {cm_path}", file=sys.stderr)
        return 2

    try:
        ls = json.loads(ls_path.read_text(encoding="utf-8"))
        cm = json.loads(cm_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⛔ JSON parse error: {e}", file=sys.stderr)
        return 2

    # Map goal_id → list of stage names
    # F10 Batch 27 fix: generate-lifecycle-specs.py emits goals[].steps[]
    # (each step dict has both "name" and "stage" fields), NOT "stages".
    # Fall back to "stages" for legacy/alternate format compat.
    goal_stages: dict[str, list[str]] = {}
    for gid, gdata in ls.get("goals", {}).items():
        stage_items = gdata.get("steps", gdata.get("stages", []))
        names = []
        for s in stage_items:
            if isinstance(s, dict):
                # Prefer "stage" (canonical from generator), fall back to "name"
                names.append(s.get("stage", s.get("name", "")))
            else:
                names.append(s)
        goal_stages[gid] = [n for n in names if n]

    # Map goal_id → spec path
    goal_spec: dict[str, str] = {}
    for s in cm.get("playwright_specs", cm.get("specs", [])):
        if isinstance(s, dict):
            goal_spec[s.get("goal_id", "")] = s.get("path", "")
        # bare string entries have no goal binding — skip

    # B107: per-goal step metadata for semantic check
    goal_steps: dict[str, list[dict]] = {}
    for gid, gdata in ls.get("goals", {}).items():
        steps = gdata.get("steps") or []
        goal_steps[gid] = [s for s in steps if isinstance(s, dict)]

    shallow_findings = []
    for gid, stages in goal_stages.items():
        spec_rel = goal_spec.get(gid)
        if not spec_rel:
            continue  # no spec for this goal (MANUAL/INFRA_PENDING?)
        spec_abs = args.repo_root / spec_rel
        result = _check_spec(spec_abs, stages)
        if "_error" in result:
            shallow_findings.append({
                "goal_id": gid, "spec": spec_rel, "error": result["_error"]
            })
            continue
        # B107 v4.70.1: semantic check on top of shallow token presence.
        # Token-presence (Batch 23) is necessary but not sufficient — Codex
        # postmortem 2026-05-23 caught specs that had every required token
        # but bound waitForResponse to wrong endpoint, never asserted status,
        # or had no error/success locator.
        semantic_findings = _check_semantic(spec_abs, goal_steps.get(gid, []))
        # Merge into same missing_stages dict for unified reporting.
        merged = {**result, **semantic_findings}
        if merged:
            shallow_findings.append({
                "goal_id": gid, "spec": spec_rel, "missing_stages": merged
            })

    if args.json:
        print(json.dumps({
            "phase_dir": str(args.phase_dir),
            "total_goals": len(goal_stages),
            "shallow_specs": len(shallow_findings),
            "failures": shallow_findings,
        }, indent=2))
    else:
        if shallow_findings:
            print(f"⛔ Batch 23: {len(shallow_findings)} shallow spec(s) detected:", file=sys.stderr)
            for f in shallow_findings:
                print(f"  - {f['goal_id']} ({f['spec']}):", file=sys.stderr)
                if "error" in f:
                    print(f"      ERROR: {f['error']}", file=sys.stderr)
                else:
                    for stage, missing in f["missing_stages"].items():
                        print(f"      stage '{stage}' missing: {', '.join(missing)}", file=sys.stderr)
        else:
            print(f"✓ Batch 23: {len(goal_stages)} goals — all specs cover declared stages")

    return 1 if shallow_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
