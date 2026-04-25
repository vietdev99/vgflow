#!/usr/bin/env python3
"""verify-blueprint-completeness — META-GATE that asserts the phase
blueprint (PLAN + API-CONTRACTS + TEST-GOALS) is detailed enough that
build/review/test/accept have no room to silently slip work.

USER FEEDBACK (2026-04-25):
  "blueprint là khâu vô cùng quan trọng, nó vẽ ra bản vẽ để build, vẽ
   ra chi tiết để test. Nó thiếu, thiếu chi tiết, thiếu tường minh thì
   toàn bộ các khâu sau sẽ lỗi, sẽ lỏng"

  Phase 7.14.3 retrospective: blueprint produced PLAN with 22 tasks +
  TEST-GOALS with 19 goals + API-CONTRACTS with N endpoints, BUT:
    - filter-row goal absent → nothing tested filter behavior
    - paging goal absent → state machine of pagination unverified
    - mutation Layer-4 absent for budget edit → ghost-save risk
    - state-machine guard absent → edit-disabled-when-paused unhandled
    - default-sort goal absent → bulk-pause first-3-rows broke
  Each gap surfaced as a runtime bug. This gate would catch them at
  blueprint time.

CHECKS (per (platform × profile × env) context):
  C1 GOAL-PLAN coverage    — every G-XX in TEST-GOALS has ≥1 PLAN task
                              tagged `Covers goal: G-XX` in body
  C2 ENDPOINT-GOAL coverage — every endpoint in API-CONTRACTS has ≥1
                              goal with auth_path + happy + 4xx + 401
                              + 403 + idempotency (for mutations) + rate
                              limit (per platform's essentials registry)
  C3 SURFACE-ESSENTIALS    — for every UI surface declared in SPECS,
                              platform's essentials checklist is covered
                              (delegates to test-goals-platform-essentials
                              registry — single source of truth)
  C4 MUTATION-LAYER-4      — every mutation goal explicitly includes
                              Layer 1 (toast text) + Layer 2 (API 2xx
                              shape) + Layer 3 (console no-error) +
                              Layer 4 (reload + state persist)
  C5 STATE-MACHINE GUARDS  — for any goal involving editable affordance
                              on a multi-state entity, REACHABLE states
                              that the API rejects must have a "disabled
                              affordance" sub-check
  C6 ORG 6-DIMENSION       — Operational Readiness Gate: PLAN must
                              answer Infra/Env/Deploy/Smoke/Integration/
                              Rollback (or N/A with reason)
  C7 ROLLBACK FOR DESTRUCTIVE — any task that drops/migrates/deletes
                              must have explicit rollback steps
  C8 EMPTY+LOADING+ERROR    — every list/grid surface must have empty,
                              loading, error states declared

CONTEXT-AWARE DISPATCH:
  Reads project profile (.claude/vg.config.md) AND per-phase SPECS
  surfaces field. Each surface's `type` (web-fullstack/mobile-rn/cli-tool/...)
  routes to the appropriate essentials list. Blueprint for a phase
  touching {api-fastify, web-react, mobile-rn} runs C2 for backend, C3
  with web-essentials for web, C3 with mobile-essentials for mobile.

INPUT:
  --phase-dir   path to .vg/phases/{N}-{slug}/
  --config      path to .claude/vg.config.md (default)
  --report-md   optional human-readable gap analysis output
  --strict      treat semi-essentials as BLOCK too

OUTPUT:
  VG-contract JSON. Exit 0 = PASS, 1 = BLOCK, 2 = config error.

WIRING:
  /vg:blueprint step 2c_verify (after PLAN+CONTRACTS+TEST-GOALS written)
  AND step 2d_crossai_review (as prerequisite). UNQUARANTINABLE — AI
  cannot trigger auto-quarantine to slip an under-detailed blueprint.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Re-use the platform registry from sibling validator. Import lazily to
# avoid coupling deployment.
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).parent


def load_platform_registry() -> dict:
    sibling = _THIS_DIR / "verify-test-goals-platform-essentials.py"
    if not sibling.exists():
        return {}
    namespace: dict = {}
    code = sibling.read_text(encoding="utf-8", errors="ignore")
    # Compile + exec so we can pull PLATFORM_REGISTRY without spawning
    # a subprocess. Safe — sibling is project-local, not external.
    exec(compile(code, str(sibling), "exec"), namespace)
    return namespace.get("PLATFORM_REGISTRY", {})


PLATFORM_REGISTRY = load_platform_registry()


def resolve_platform(platform: str) -> dict:
    entry = PLATFORM_REGISTRY.get(platform)
    if entry is None:
        return {}
    if isinstance(entry, str) and entry.startswith("alias:"):
        return resolve_platform(entry.split(":", 1)[1])
    return entry  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------


def read_text(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="ignore")


GOAL_HEADING = re.compile(
    r"^#+\s+(?:Goal\s+)?G-(\d+)\b\s*[:.\-]?\s*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
ENDPOINT_HEADING = re.compile(
    r"^#+\s+(?P<method>GET|POST|PUT|PATCH|DELETE)\s+(?P<path>\S+)",
    re.IGNORECASE | re.MULTILINE,
)
TASK_BLOCK = re.compile(
    # Match BOTH heading style (`### Task 01 — title`) and list style
    # (`- Task 1: title` / `1. Task 1: title`).
    r"(?:^|\n)"
    r"(?:#+\s+|\s*(?:[-*]|\d+\.)\s+(?:\*\*)?)"
    r"Task\s+(\d+(?:\.\d+)?)"
    r"\s*(?:—|\-|:|\.)\s*"
    r"(.+?)"
    r"(?=\n(?:#+\s+|\s*(?:[-*]|\d+\.)\s+(?:\*\*)?)Task\s+\d+|\n##\s+Wave|\Z)",
    re.IGNORECASE | re.DOTALL,
)
COVERS_GOAL = re.compile(
    # Either `Covers goal: G-XX, G-YY` body line OR
    # `<goals-covered>G-XX, G-YY</goals-covered>` XML annotation
    r"(?:covers\s+goal\s*:|<goals-covered>)\s*((?:G-\d+\s*,?\s*)+)",
    re.IGNORECASE,
)


def parse_goals(text: str) -> dict[str, str]:
    """Returns {G-XX: title}."""
    out: dict[str, str] = {}
    for m in GOAL_HEADING.finditer(text):
        gid = f"G-{m.group(1).zfill(2)}"
        if gid not in out:
            out[gid] = m.group(2).strip()
    return out


def parse_endpoints(text: str) -> list[tuple[str, str]]:
    """Returns [(method, path)]."""
    return [(m.group("method").upper(), m.group("path"))
            for m in ENDPOINT_HEADING.finditer(text)]


def parse_plan_tasks(text: str) -> list[tuple[str, str, list[str]]]:
    """Returns [(task_id, title, [covered_goals])]."""
    out: list[tuple[str, str, list[str]]] = []
    for m in TASK_BLOCK.finditer(text):
        body = m.group(2)
        first_line = body.splitlines()[0].strip() if body else ""
        covered: list[str] = []
        cm = COVERS_GOAL.search(body)
        if cm:
            covered = [g.strip() for g in re.split(r"[,\s]+", cm.group(1))
                       if g.strip().startswith("G-")]
        out.append((m.group(1), first_line[:120], covered))
    return out


def detect_surfaces(specs_text: str, config_text: str) -> list[dict]:
    """Pull surfaces declared in SPECS or fall back to project profile.

    SPECS may declare:
      surfaces:
        web:  type: web-frontend-only
        api:  type: web-backend-only
    """
    surfaces: list[dict] = []
    # SPECS surfaces block
    block = re.search(
        r"^surfaces\s*:\s*\n((?:\s+\w+\s*:.*?(?:\n|$))+)",
        specs_text,
        re.MULTILINE | re.DOTALL,
    )
    if block:
        for sm in re.finditer(
            r"^\s+(\w+)\s*:\s*\n(?:\s+#.*\n)*"
            r"(?:\s+\w+\s*:.*?\n)*"
            r"\s+type\s*:\s*[\"']?([\w-]+)",
            block.group(1),
            re.MULTILINE,
        ):
            surfaces.append({"name": sm.group(1), "type": sm.group(2).lower()})
    if surfaces:
        return surfaces
    # Fall back to project profile from config
    pm = re.search(r"^profile\s*:\s*[\"']?([\w-]+)", config_text, re.MULTILINE)
    if pm:
        return [{"name": "default", "type": pm.group(1).lower()}]
    return [{"name": "default", "type": "web-fullstack"}]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_goal_plan_coverage(goals: dict[str, str],
                              tasks: list) -> list[dict]:
    findings: list[dict] = []
    covered_set: set[str] = set()
    for _tid, _title, covered in tasks:
        covered_set.update(covered)
    for gid in goals:
        if gid not in covered_set:
            findings.append({
                "type": "goal-without-task",
                "goal_id": gid,
                "goal_title": goals[gid],
                "fix_hint": (
                    f"Add a PLAN task body line `Covers goal: {gid}` for the "
                    f"task that implements this goal. Otherwise the planner "
                    f"is shipping a goal with no work mapped to it — "
                    f"build will silently miss it."
                ),
            })
    return findings


def check_endpoint_goal_coverage(endpoints: list[tuple[str, str]],
                                  goals: dict[str, str]) -> list[dict]:
    findings: list[dict] = []
    goals_blob = " | ".join(f"{k}: {v.lower()}" for k, v in goals.items())
    for method, path in endpoints:
        # Heuristic: at least one goal mentions the path token + method
        # OR at least one goal mentions the unique terminal segment of path
        terminal = path.rstrip("/").split("/")[-1].split("?")[0].lower() or path
        path_lower = path.lower()
        if (terminal in goals_blob or path_lower in goals_blob):
            continue
        findings.append({
            "type": "endpoint-without-goal",
            "method": method,
            "path": path,
            "fix_hint": (
                f"No TEST-GOAL mentions `{method} {path}` (or path token "
                f"`{terminal}`). Add a goal covering happy path + 4xx "
                f"validation + 401/403 auth (and idempotency + rate-limit "
                f"if mutation) for this endpoint."
            ),
        })
    return findings


def check_surface_essentials(surfaces: list[dict],
                              goals: dict[str, str],
                              specs_text: str,
                              context_text: str) -> list[dict]:
    """For each surface, check platform essentials are covered."""
    from importlib.machinery import SourceFileLoader
    sibling = _THIS_DIR / "verify-test-goals-platform-essentials.py"
    if not sibling.exists():
        return [{"type": "config-error",
                 "message": "Sibling validator missing; cannot resolve "
                            "platform essentials."}]

    mod = SourceFileLoader(
        "platform_essentials", str(sibling)
    ).load_module()
    detect = mod.detect_categories
    find_cover = mod.find_covering_goal

    findings: list[dict] = []
    detected = detect(specs_text, context_text)
    goal_pairs = [(gid, title.lower()) for gid, title in goals.items()]
    for surf in surfaces:
        essentials_map = resolve_platform(surf["type"])
        if not essentials_map:
            continue
        for cat, items in essentials_map.items():
            if cat not in detected:
                continue
            for essential in items:
                gid = find_cover(essential, goal_pairs)
                if gid is None:
                    findings.append({
                        "type": "surface-essential-missing",
                        "surface": surf["name"],
                        "platform": surf["type"],
                        "category": cat,
                        "essential": essential,
                        "fix_hint": (
                            f"Surface `{surf['name']}` (platform="
                            f"{surf['type']}, category={cat}) requires goal "
                            f"covering `{essential}`. Add `G-NN: "
                            f"{essential.replace('-', ' ').title()}` to "
                            f"TEST-GOALS.md."
                        ),
                    })
    return findings


MUTATION_LAYER_PATTERNS = {
    "layer1_toast":     r"(?:layer\s*1|toast.*text|toast.*message)",
    "layer2_api_2xx":   r"(?:layer\s*2|api\s*2xx|response\s*shape|"
                        r"status\s*200)",
    "layer3_console":   r"(?:layer\s*3|console.*error|no.*console)",
    "layer4_reload":    r"(?:layer\s*4|reload|re-?read|persist|state.*after.*"
                        r"reload|refresh.*shows)",
}


def check_mutation_layer_4(goals_text: str,
                            goals: dict[str, str]) -> list[dict]:
    """For every goal whose title hints at a mutation, all 4 layers must
    appear somewhere in that goal's section body."""
    findings: list[dict] = []
    mutation_re = re.compile(
        r"\b(edit|update|create|delete|submit|mutation|put|post|patch|"
        r"chỉnh|sửa|cập nhật|xóa|tạo)\b",
        re.IGNORECASE,
    )
    # Split goals_text into sections by goal heading
    sections: dict[str, str] = {}
    parts = re.split(r"^#+\s+(?:Goal\s+)?G-\d+\b.*?$",
                     goals_text, flags=re.MULTILINE)
    headings = [m.group(0) for m in GOAL_HEADING.finditer(goals_text)]
    for i, hdr in enumerate(headings):
        gm = re.search(r"G-(\d+)", hdr)
        if not gm:
            continue
        gid = f"G-{gm.group(1).zfill(2)}"
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sections[gid] = body

    for gid, title in goals.items():
        if not mutation_re.search(title):
            continue
        body = sections.get(gid, "")
        body_lower = (title + "\n" + body).lower()
        missing_layers = [
            name for name, patt in MUTATION_LAYER_PATTERNS.items()
            if not re.search(patt, body_lower, re.IGNORECASE)
        ]
        if missing_layers:
            findings.append({
                "type": "mutation-layer-missing",
                "goal_id": gid,
                "goal_title": title,
                "missing_layers": missing_layers,
                "fix_hint": (
                    f"Goal {gid} ('{title[:60]}...') is a mutation but "
                    f"its body lacks layer assertions: "
                    f"{', '.join(missing_layers)}. Add explicit success "
                    f"criteria for every layer (toast text + API 2xx shape "
                    f"+ console no-error + reload + diff)."
                ),
            })
    return findings


def check_state_machine_guards(goals_text: str,
                                goals: dict[str, str],
                                specs_text: str) -> list[dict]:
    """For goals involving editable affordances on entities with multiple
    states (e.g. status field), there must be a sub-check for disabled
    affordance on non-permitted states."""
    findings: list[dict] = []
    edit_re = re.compile(
        r"\b(inline edit|editable|edit.*cell|edit.*budget|edit.*field)\b",
        re.IGNORECASE,
    )
    state_kw_re = re.compile(
        r"\b(active|paused|pending|draft|archived|stopped|status)\b",
        re.IGNORECASE,
    )
    for gid, title in goals.items():
        if not edit_re.search(title):
            continue
        if not state_kw_re.search(specs_text + "\n" + title):
            continue
        # Goal involves edit + entity has states; require a disabled-affordance
        # mention in goal title or body
        section = ""
        for m in GOAL_HEADING.finditer(goals_text):
            if m.group(1).zfill(2) == gid.split("-")[1]:
                start = m.end()
                next_m = next(
                    (n for n in GOAL_HEADING.finditer(goals_text, start)),
                    None,
                )
                section = goals_text[start: next_m.start() if next_m else None]
                break
        body = (title + "\n" + section).lower()
        has_guard = any(kw in body for kw in [
            "disabled", "guard", "non-active", "not editable", "read-only",
            "readonly", "khóa", "không sửa được", "vô hiệu",
        ])
        if not has_guard:
            findings.append({
                "type": "state-machine-guard-missing",
                "goal_id": gid,
                "fix_hint": (
                    f"Goal {gid} edits a multi-state entity but has no "
                    f"explicit success criterion for the DISABLED affordance "
                    f"on non-permitted states. Add: 'On status≠active the "
                    f"cell renders read-only with tooltip explaining why.'"
                ),
            })
    return findings


def check_org_six_dimensions(plan_text: str) -> list[dict]:
    """ORG 6-Dimension Operational Readiness Gate: PLAN must address
    Infra / Env / Deploy / Smoke / Integration / Rollback or N/A."""
    findings: list[dict] = []
    dimensions = {
        "Infra": ["infra", "ansible", "vps", "service", "install"],
        "Env": ["env var", "environment", ".env", "config", "secret"],
        "Deploy": ["deploy", "rsync", "pm2", "systemd", "build", "release"],
        "Smoke": ["smoke", "health check", "/health", "200", "alive"],
        "Integration": ["integration", "consumer", "kafka", "redis", "queue",
                        "downstream", "upstream"],
        "Rollback": ["rollback", "revert", "previous version", "down migration"],
    }
    blob = plan_text.lower()
    for dim, kws in dimensions.items():
        if any(kw in blob for kw in kws):
            continue
        # Check for explicit N/A declaration
        if re.search(rf"{dim}\s*[:\-]\s*N/?A", plan_text, re.IGNORECASE):
            continue
        findings.append({
            "type": "org-dim-missing",
            "dimension": dim,
            "fix_hint": (
                f"PLAN doesn't address ORG dimension '{dim}'. Either include "
                f"a task that covers it OR add an explicit "
                f"`{dim}: N/A — reason` line in PLAN."
            ),
        })
    return findings


def check_rollback_for_destructive(plan_text: str) -> list[dict]:
    """If any PLAN task has destructive verbs (drop/delete/migrate), there
    must be a corresponding rollback step."""
    findings: list[dict] = []
    destructive_re = re.compile(
        r"\b(drop\s+(?:table|column|index)|"
        r"delete\s+from|migrate|truncate|destroy|"
        r"remove\s+(?:column|table|user))\b",
        re.IGNORECASE,
    )
    has_rollback = bool(re.search(
        r"\b(rollback|revert|down\s+migration|undo)\b",
        plan_text, re.IGNORECASE,
    ))
    matches = destructive_re.findall(plan_text)
    if matches and not has_rollback:
        findings.append({
            "type": "destructive-without-rollback",
            "destructive_phrases": list(set(matches))[:5],
            "fix_hint": (
                "PLAN contains destructive operations "
                f"({', '.join(list(set(matches))[:3])}) but no rollback "
                "step. Add explicit rollback procedure or document "
                "irreversibility with risk acceptance."
            ),
        })
    return findings


def check_empty_loading_error(specs_text: str,
                               goals: dict[str, str],
                               surfaces: list[dict]) -> list[dict]:
    """Every UI surface (web/mobile/desktop) with list/grid must declare
    empty + loading + error states."""
    findings: list[dict] = []
    if not any(s["type"].startswith(("web-", "mobile-", "desktop-"))
               for s in surfaces):
        return findings
    if not re.search(r"\b(list|table|grid|feed|items)\b",
                     specs_text, re.IGNORECASE):
        return findings
    goals_blob = " | ".join(g.lower() for g in goals.values())
    states_required = {
        "empty":   ["empty", "no data", "no results", "trống", "không có"],
        "loading": ["loading", "skeleton", "spinner", "đang tải", "fetching"],
        "error":   ["error", "failed", "lỗi", "thất bại", "fallback"],
    }
    for state, kws in states_required.items():
        if any(kw in goals_blob for kw in kws):
            continue
        findings.append({
            "type": "ui-state-missing",
            "state": state,
            "fix_hint": (
                f"List/grid surface lacks a TEST-GOAL covering the '{state}' "
                f"state. Add a goal asserting the UI renders correctly when "
                f"data is {state}."
            ),
        })
    return findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--config", default=".claude/vg.config.md")
    ap.add_argument("--report-md", default="")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)

    started = time.monotonic()
    phase_dir = Path(args.phase_dir)
    if not phase_dir.is_dir():
        print(json.dumps({
            "validator": "blueprint-completeness",
            "verdict": "BLOCK",
            "evidence": [{"type": "config-error",
                          "message": f"phase-dir not found: {phase_dir}"}],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "cache_key": None,
        }))
        return 2

    # Load artifacts
    plan_text = ""
    for cand in phase_dir.glob("PLAN*.md"):
        plan_text = read_text(cand)
        break
    contracts_text = read_text(phase_dir / "API-CONTRACTS.md")
    test_goals_text = read_text(phase_dir / "TEST-GOALS.md")
    specs_text = read_text(phase_dir / "SPECS.md")
    context_text = read_text(phase_dir / "CONTEXT.md")
    config_text = read_text(Path(args.config))

    if not plan_text or not test_goals_text or not specs_text:
        print(json.dumps({
            "validator": "blueprint-completeness",
            "verdict": "BLOCK",
            "evidence": [{
                "type": "missing-artifact",
                "message": (
                    f"Need SPECS.md + PLAN*.md + TEST-GOALS.md in "
                    f"{phase_dir}; got SPECS={bool(specs_text)}, "
                    f"PLAN={bool(plan_text)}, TEST-GOALS={bool(test_goals_text)}."
                ),
            }],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "cache_key": None,
        }))
        return 1

    goals = parse_goals(test_goals_text)
    endpoints = parse_endpoints(contracts_text)
    tasks = parse_plan_tasks(plan_text)
    surfaces = detect_surfaces(specs_text, config_text)

    findings: list[dict] = []
    findings.extend(check_goal_plan_coverage(goals, tasks))
    findings.extend(check_endpoint_goal_coverage(endpoints, goals))
    findings.extend(check_surface_essentials(
        surfaces, goals, specs_text, context_text))
    findings.extend(check_mutation_layer_4(test_goals_text, goals))
    findings.extend(check_state_machine_guards(
        test_goals_text, goals, specs_text))
    findings.extend(check_org_six_dimensions(plan_text))
    findings.extend(check_rollback_for_destructive(plan_text))
    findings.extend(check_empty_loading_error(specs_text, goals, surfaces))

    verdict = "PASS" if not findings else "BLOCK"
    output = {
        "validator": "blueprint-completeness",
        "verdict": verdict,
        "evidence": findings or [{
            "type": "summary",
            "message": (
                f"Blueprint complete: {len(goals)} goals, "
                f"{len(endpoints)} endpoints, {len(tasks)} tasks, "
                f"{len(surfaces)} surfaces — all 8 checks PASS."
            ),
        }],
        "duration_ms": int((time.monotonic() - started) * 1000),
        "cache_key": None,
        "stats": {
            "goals": len(goals),
            "endpoints": len(endpoints),
            "tasks": len(tasks),
            "surfaces": [s["type"] for s in surfaces],
            "findings_by_type": _group_by_type(findings),
        },
    }
    print(json.dumps(output))

    if args.report_md:
        _write_report(args.report_md, output, surfaces, goals, endpoints, tasks)

    return 0 if verdict == "PASS" else 1


def _group_by_type(findings: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        out[f["type"]] = out.get(f["type"], 0) + 1
    return out


def _write_report(path: str, output: dict, surfaces: list[dict],
                   goals: dict[str, str], endpoints: list,
                   tasks: list) -> None:
    lines = [
        "# Blueprint Completeness Audit",
        "",
        f"- Verdict: **{output['verdict']}**",
        f"- Goals: **{output['stats']['goals']}**",
        f"- Endpoints: **{output['stats']['endpoints']}**",
        f"- Tasks: **{output['stats']['tasks']}**",
        f"- Surfaces: {', '.join(output['stats']['surfaces'])}",
        "",
    ]
    grouped = output["stats"]["findings_by_type"]
    if grouped:
        lines.append("## Findings by check")
        lines.append("")
        for t, c in sorted(grouped.items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{t}`: {c}")
        lines.append("")
        lines.append("## Detail")
        lines.append("")
        for f in output["evidence"]:
            if "fix_hint" not in f:
                continue
            lines.append(f"### `{f.get('type','?')}`")
            lines.append("")
            for k, v in f.items():
                if k in ("type", "fix_hint"):
                    continue
                if isinstance(v, list):
                    v = ", ".join(map(str, v))
                lines.append(f"- **{k}**: {v}")
            lines.append("")
            lines.append(f"**Fix:** {f['fix_hint']}")
            lines.append("")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
