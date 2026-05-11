#!/usr/bin/env python3
"""Prepare and validate AI-authored deep test-spec expansions.

This module is intentionally domain-agnostic. VGFlow owns the schema, merge
rules, and validation. The AI owns domain interpretation from phase artifacts:
actors, fixture dependency graph, artifacts, cleanup, and stage details.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_STAGES = (
    "read_before",
    "create",
    "read_after_create",
    "update",
    "read_after_update",
    "delete",
    "read_after_delete",
)

OUTPUT_SCHEMA: dict[str, Any] = {
    "schema_version": "1.0",
    "goals": {
        "G-ID": {
            "actors": [
                {"id": "actor_id", "role": "domain role", "session": "session fixture", "permissions": []}
            ],
            "fixture_dag": [
                {"id": "fixture_id", "kind": "fixture kind", "depends_on": [], "cleanup": "cleanup rule"}
            ],
            "steps": [
                {"stage": stage, "actor": "actor_id", "action": "domain-specific action", "evidence": []}
                for stage in REQUIRED_STAGES
            ],
            "artifact_capture": [
                {"id": "artifact_id", "source": "where captured", "identifier": "stable identifier", "consumer_step": "stage"}
            ],
            "cleanup": [
                {"target": "fixture_id", "action": "cleanup action"}
            ],
            "execution_plan": {
                "profile": "web-fullstack|mobile-rn|cli-tool|backend-only|library|mixed",
                "runner": "playwright|maestro|appium|cli|api-contract|unit|property|custom",
                "entrypoints": ["route, command, screen, endpoint, function, job, or fixture entrypoint"],
                "assertions": ["observable assertion, no runtime proof claims"],
                "artifacts": ["screenshots, logs, traces, DB snapshots, files, stdout/stderr, reports"],
            },
            "notes": ["domain assumptions or unresolved gaps"],
        }
    },
}

PROFILE_RUNNERS: dict[str, dict[str, Any]] = {
    "web-fullstack": {
        "family": "web",
        "runner": "playwright",
        "entrypoint_kind": "browser route, role/label/data-testid, API endpoint",
        "required_artifacts": ["screenshot", "console log", "network log", "trace on failure"],
    },
    "web-frontend-only": {
        "family": "web",
        "runner": "playwright",
        "entrypoint_kind": "browser route, role/label/data-testid",
        "required_artifacts": ["screenshot", "console log", "network log", "trace on failure"],
    },
    "web-backend-only": {
        "family": "backend",
        "runner": "api-contract",
        "entrypoint_kind": "HTTP endpoint, job, event, DB query",
        "required_artifacts": ["request/response", "DB snapshot", "job/event log"],
    },
    "backend-only": {
        "family": "backend",
        "runner": "api-contract",
        "entrypoint_kind": "HTTP/RPC endpoint, job, queue event, DB query",
        "required_artifacts": ["request/response", "DB snapshot", "job/event log"],
    },
    "backend-multi-actor": {
        "family": "backend",
        "runner": "api-contract",
        "entrypoint_kind": "HTTP/RPC endpoint with multiple auth contexts",
        "required_artifacts": ["request/response per actor", "DB snapshot", "authz denial/proof"],
    },
    "mobile-rn": {
        "family": "mobile",
        "runner": "maestro-or-appium",
        "entrypoint_kind": "mobile screen, accessibility id, deep link, device state",
        "required_artifacts": ["screenshot", "device log", "network log", "video/trace on failure"],
    },
    "mobile-flutter": {
        "family": "mobile",
        "runner": "maestro-or-appium",
        "entrypoint_kind": "mobile screen, accessibility label/key, deep link, device state",
        "required_artifacts": ["screenshot", "device log", "network log", "video/trace on failure"],
    },
    "mobile-native-ios": {
        "family": "mobile",
        "runner": "xctest-or-appium",
        "entrypoint_kind": "iOS screen, accessibility id, universal link, device state",
        "required_artifacts": ["screenshot", "device log", "network log", "video/trace on failure"],
    },
    "mobile-native-android": {
        "family": "mobile",
        "runner": "maestro-or-espresso-or-appium",
        "entrypoint_kind": "Android activity/screen, resource id, deep link, device state",
        "required_artifacts": ["screenshot", "logcat", "network log", "video/trace on failure"],
    },
    "mobile-hybrid": {
        "family": "mobile",
        "runner": "maestro-or-appium",
        "entrypoint_kind": "hybrid webview/native screen, accessibility id, deep link",
        "required_artifacts": ["screenshot", "device log", "webview console/network log"],
    },
    "cli-tool": {
        "family": "cli",
        "runner": "cli",
        "entrypoint_kind": "command, args, stdin, env, file system fixture",
        "required_artifacts": ["exit code", "stdout", "stderr", "created/modified files"],
    },
    "library": {
        "family": "library",
        "runner": "unit-or-property",
        "entrypoint_kind": "public function/class/API, fixture object, property invariant",
        "required_artifacts": ["unit output", "coverage", "property counterexample on failure"],
    },
    "mixed": {
        "family": "mixed",
        "runner": "profile-composite",
        "entrypoint_kind": "profile-specific entrypoint from phase artifacts",
        "required_artifacts": ["profile-specific evidence"],
    },
}

PROFILE_RE = re.compile(
    r"^\s*(?:phase_profile|profile|platform|surface)\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)[\"']?\s*$",
    re.MULTILINE,
)


def read(path: Path, limit: int = 20000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    return text[:limit]


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}

def normalize_profile(value: str | None) -> str:
    raw = (value or "").strip().lower().replace("_", "-")
    aliases = {
        "web": "web-fullstack",
        "frontend": "web-frontend-only",
        "backend": "backend-only",
        "mobile": "mobile-hybrid",
        "cli": "cli-tool",
        "command-line": "cli-tool",
        "lib": "library",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in PROFILE_RUNNERS else "mixed"

def detect_phase_profile(phase_dir: Path, root: Path | None = None) -> str:
    for name in (".phase-profile", "SPECS.md", "CONTEXT.md", "PLAN.md", "BLUEPRINT.md"):
        text = read(phase_dir / name, limit=5000)
        match = PROFILE_RE.search(text)
        if match:
            return normalize_profile(match.group(1))

    combined = "\n".join(
        read(phase_dir / name, limit=12000)
        for name in ("SPECS.md", "CONTEXT.md", "TEST-GOALS.md", "API-DOCS.md")
    ).lower()
    if re.search(r"\b(maestro|android|ios|react native|flutter|mobile|apk|ipa|emulator|device)\b", combined):
        return "mobile-hybrid"
    if re.search(r"\b(cli|command|argv|stdin|stdout|stderr|exit code)\b", combined):
        return "cli-tool"
    if re.search(r"\b(library|sdk|package|public api|function|class|unit test)\b", combined):
        return "library"
    sample_paths: list[str] = []
    if root:
        sample_paths = [str(path).lower() for path in list(root.rglob("*"))[:2000] if path.is_file()]
        if any(part.endswith((".tsx", ".jsx", ".vue", ".svelte")) for part in sample_paths):
            return "web-fullstack"
    if re.search(r"\b(api|endpoint|queue|worker|database|db|webhook|rpc|grpc)\b", combined):
        if not re.search(r"\b(page|screen|button|form|modal|route|browser|click)\b", combined):
            return "backend-only"

    if root:
        if any(part.endswith((".swift", ".kt", ".java")) or "/android/" in part or "/ios/" in part for part in sample_paths):
            return "mobile-hybrid"
    return "mixed"

def execution_strategy(profile: str) -> dict[str, Any]:
    normalized = normalize_profile(profile)
    strategy = dict(PROFILE_RUNNERS[normalized])
    strategy["profile"] = normalized
    return strategy

def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []

def _entrypoint_hints(spec: dict[str, Any], surfaces: dict[str, Any], profile: str) -> list[str]:
    hints: list[str] = []
    for endpoint in _safe_list(spec.get("primary_endpoints")):
        if isinstance(endpoint, dict) and endpoint.get("method") and endpoint.get("path"):
            hints.append(f"{endpoint['method']} {endpoint['path']}")
    for route in _safe_list(surfaces.get("routes"))[:10]:
        if isinstance(route, dict) and route.get("route"):
            hints.append(str(route["route"]))
    strategy = execution_strategy(profile)
    if not hints:
        hints.append(f"derive {strategy['entrypoint_kind']} from built implementation and TEST-GOALS")
    seen: set[str] = set()
    unique: list[str] = []
    for hint in hints:
        if hint in seen:
            continue
        seen.add(hint)
        unique.append(hint)
    return unique

def baseline_execution_plan(goal_id: str, spec: dict[str, Any], profile: str, surfaces: dict[str, Any]) -> dict[str, Any]:
    strategy = execution_strategy(profile)
    stages = [
        str(step.get("stage"))
        for step in _safe_list(spec.get("steps"))
        if isinstance(step, dict) and step.get("stage")
    ]
    assertions = [
        "execute every lifecycle stage in order",
        "assert fresh read state after each mutation",
        "assert cleanup removes or terminally closes test-owned resources",
    ]
    if stages:
        assertions.append("covered stages: " + ", ".join(stages))
    if spec.get("source_assertions"):
        assertions.append("bind source_assertions from TEST-GOALS to runner checks")
    return {
        "profile": normalize_profile(profile),
        "family": strategy["family"],
        "runner": strategy["runner"],
        "goal": goal_id,
        "entrypoints": _entrypoint_hints(spec, surfaces, profile),
        "assertions": assertions,
        "artifacts": list(strategy["required_artifacts"]),
        "notes": [
            "Baseline plan is project-agnostic; TEST-SPEC-LOCALIZER prompt asks AI to replace generic hints with domain-specific fixtures and selectors.",
        ],
    }

def ensure_execution_plans(lifecycle: dict[str, Any], profile: str, surfaces: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_profile(profile)
    lifecycle["phase_profile"] = normalized
    lifecycle["execution_strategy"] = execution_strategy(normalized)
    goals = lifecycle.get("goals") if isinstance(lifecycle.get("goals"), dict) else {}
    for goal_id, spec in goals.items():
        if not isinstance(spec, dict):
            continue
        baseline = baseline_execution_plan(goal_id, spec, normalized, surfaces)
        current = spec.get("execution_plan")
        if not isinstance(current, dict):
            spec["execution_plan"] = baseline
            continue
        merged = dict(baseline)
        for key, value in current.items():
            if value not in (None, "", [], {}):
                merged[key] = value
        spec["execution_plan"] = merged
    return lifecycle

def build_execution_plan_artifact(lifecycle: dict[str, Any], surfaces: dict[str, Any]) -> dict[str, Any]:
    profile = normalize_profile(str(lifecycle.get("phase_profile") or "mixed"))
    goals: dict[str, Any] = {}
    for goal_id, spec in (lifecycle.get("goals") or {}).items():
        if not isinstance(spec, dict):
            continue
        plan = spec.get("execution_plan")
        if not isinstance(plan, dict) or not plan:
            plan = baseline_execution_plan(goal_id, spec, profile, surfaces)
        goals[goal_id] = plan
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": lifecycle.get("phase"),
        "phase_profile": profile,
        "execution_strategy": execution_strategy(profile),
        "goals": goals,
        "surface_summary": {
            "routes": len(_safe_list(surfaces.get("routes"))),
            "forms": len(_safe_list(surfaces.get("forms"))),
            "mutations": len(_safe_list(surfaces.get("mutations"))),
            "files_scanned": surfaces.get("files_scanned", 0),
        },
    }


def goal_brief(goal_id: str, spec: dict[str, Any], profile: str) -> dict[str, Any]:
    return {
        "goal_id": goal_id,
        "title": spec.get("title"),
        "goal_type": spec.get("goal_type"),
        "surface": spec.get("surface"),
        "phase_profile": profile,
        "execution_strategy": execution_strategy(profile),
        "primary_endpoints": spec.get("primary_endpoints") or [],
        "source_assertions": spec.get("source_assertions") or {},
        "current_actors": spec.get("actors") or [],
        "current_fixture_dag": spec.get("fixture_dag") or [],
        "required_stages": list(REQUIRED_STAGES),
    }


def build_request(phase_dir: Path, root: Path, max_goals: int = 200) -> dict[str, Any]:
    lifecycle = read_json(phase_dir / "LIFECYCLE-SPECS.json")
    goals = lifecycle.get("goals") if isinstance(lifecycle.get("goals"), dict) else {}
    profile = normalize_profile(
        str((lifecycle.get("phase_profile") if isinstance(lifecycle, dict) else "") or "")
        or detect_phase_profile(phase_dir, root)
    )
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": phase_dir.name,
        "phase_profile": profile,
        "execution_strategy": execution_strategy(profile),
        "root_hint": str(root),
        "task": "Expand lifecycle test specs with domain-specific actors, fixture DAG, artifact capture, cleanup, and RCRURDR actions.",
        "hard_rules": [
            "Do not invent runtime proof.",
            "Use only phase artifacts and implementation hints in this request.",
            "Return JSON only, matching OUTPUT_SCHEMA.",
            "Every emitted goal must keep all required stages.",
            "Every mutation or multi-actor goal needs explicit fixture_dag and cleanup.",
            "Names must be domain-specific to the current goal, not generic actor/resource placeholders.",
            "Use the phase_profile execution strategy; do not assume web/Playwright for mobile, CLI, backend, or library phases.",
        ],
        "required_stages": list(REQUIRED_STAGES),
        "goals": [goal_brief(goal_id, spec, profile) for goal_id, spec in list(goals.items())[:max_goals]],
        "phase_artifacts": {
            "test_goals_index": read(phase_dir / "TEST-GOALS.md"),
            "context": read(phase_dir / "CONTEXT.md"),
            "summary": "\n\n".join(read(path, 5000) for path in sorted(phase_dir.glob("SUMMARY*.md"))[:3]),
            "runtime_map": read(phase_dir / "RUNTIME-MAP.md"),
            "api_docs": read(phase_dir / "API-DOCS.md"),
        },
    }


def render_prompt(request: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# VG Deep Test-Spec AI Expansion",
            "",
            "You are expanding VGFlow lifecycle specs after build and before review.",
            "Return JSON only. No prose outside JSON.",
            "",
            "## Output Schema",
            "",
            "```json",
            json.dumps(OUTPUT_SCHEMA, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Request",
            "",
            "```json",
            json.dumps(request, indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )


def prepare(phase_dir: Path, root: Path, out_dir: Path, max_goals: int = 200) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    request = build_request(phase_dir, root, max_goals=max_goals)
    request_path = out_dir / "REQUEST.json"
    prompt_path = out_dir / "PROMPT.md"
    schema_path = out_dir / "OUTPUT.schema.json"
    template_path = out_dir / "OUTPUT.template.json"
    request_path.write_text(json.dumps(request, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    prompt_path.write_text(render_prompt(request), encoding="utf-8")
    schema_path.write_text(json.dumps(OUTPUT_SCHEMA, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    template_path.write_text(json.dumps({"schema_version": "1.0", "goals": {}}, indent=2) + "\n", encoding="utf-8")
    return {
        "request": str(request_path),
        "prompt": str(prompt_path),
        "schema": str(schema_path),
        "template": str(template_path),
    }


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        return json.loads(text[first:last + 1])
    raise ValueError("No JSON object found in AI response")


def load_expansion_file(path: Path) -> dict[str, Any]:
    return extract_json(read(path, limit=2_000_000))


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", value))


def validate_expansion(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    goals = payload.get("goals")
    if not isinstance(goals, dict):
        return ["top-level goals must be an object"]
    for goal_id, spec in goals.items():
        if not _valid_id(goal_id):
            errors.append(f"{goal_id}: invalid goal id")
            continue
        if not isinstance(spec, dict):
            errors.append(f"{goal_id}: spec must be object")
            continue
        actors = spec.get("actors") or []
        fixtures = spec.get("fixture_dag") or []
        steps = spec.get("steps") or []
        execution_plan = spec.get("execution_plan") or {}
        if not isinstance(actors, list) or not actors:
            errors.append(f"{goal_id}: actors must be non-empty list")
        if not isinstance(fixtures, list) or not fixtures:
            errors.append(f"{goal_id}: fixture_dag must be non-empty list")
        fixture_ids = {item.get("id") for item in fixtures if isinstance(item, dict)}
        if any(not _valid_id(item) for item in fixture_ids):
            errors.append(f"{goal_id}: fixture ids must be stable ASCII ids")
        for fixture in fixtures:
            if not isinstance(fixture, dict):
                errors.append(f"{goal_id}: fixture item must be object")
                continue
            deps = fixture.get("depends_on") or []
            if not isinstance(deps, list):
                errors.append(f"{goal_id}:{fixture.get('id')}: depends_on must be list")
                continue
            missing_deps = [dep for dep in deps if dep not in fixture_ids]
            if missing_deps:
                errors.append(f"{goal_id}:{fixture.get('id')}: missing dependencies {missing_deps}")
        stages = [step.get("stage") for step in steps if isinstance(step, dict)]
        if stages != list(REQUIRED_STAGES):
            errors.append(f"{goal_id}: steps must exactly match required RCRURDR stages")
        if not isinstance(execution_plan, dict) or not execution_plan:
            errors.append(f"{goal_id}: execution_plan must be object")
        else:
            profile = normalize_profile(str(execution_plan.get("profile") or ""))
            if profile == "mixed" and str(execution_plan.get("profile") or "").strip().lower() not in {"mixed", ""}:
                errors.append(f"{goal_id}: execution_plan profile is unsupported")
            for key in ("runner", "entrypoints", "assertions", "artifacts"):
                value = execution_plan.get(key)
                if key == "runner":
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"{goal_id}: execution_plan.runner required")
                elif not isinstance(value, list) or not value:
                    errors.append(f"{goal_id}: execution_plan.{key} must be non-empty list")
    return errors


def apply_expansion(lifecycle: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    errors = validate_expansion(payload)
    if errors:
        raise ValueError("; ".join(errors))
    goals = lifecycle.get("goals")
    if not isinstance(goals, dict):
        goals = {}
        lifecycle["goals"] = goals
    applied: list[str] = []
    skipped: list[str] = []
    for goal_id, patch in payload.get("goals", {}).items():
        if goal_id not in goals or not isinstance(goals[goal_id], dict):
            skipped.append(goal_id)
            continue
        spec = goals[goal_id]
        for key in ("actors", "fixture_dag", "steps", "artifact_capture", "cleanup"):
            value = patch.get(key)
            if isinstance(value, list) and value:
                spec[key] = value
        if isinstance(patch.get("execution_plan"), dict) and patch["execution_plan"]:
            spec["execution_plan"] = patch["execution_plan"]
        if patch.get("notes"):
            spec["ai_expansion_notes"] = patch.get("notes")
        spec["ai_expanded"] = True
        applied.append(goal_id)
    lifecycle["ai_expansion"] = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "applied_goals": applied,
        "skipped_goals": skipped,
        "schema_version": payload.get("schema_version", "1.0"),
    }
    return lifecycle, lifecycle["ai_expansion"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prepare = sub.add_parser("prepare")
    p_prepare.add_argument("--phase-dir", required=True)
    p_prepare.add_argument("--root", required=True)
    p_prepare.add_argument("--out-dir", required=True)
    p_prepare.add_argument("--max-goals", type=int, default=200)

    p_extract = sub.add_parser("extract")
    p_extract.add_argument("--raw", required=True)
    p_extract.add_argument("--out", required=True)

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--response", required=True)

    args = parser.parse_args()
    if args.cmd == "prepare":
        result = prepare(Path(args.phase_dir), Path(args.root), Path(args.out_dir), args.max_goals)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "extract":
        payload = load_expansion_file(Path(args.raw))
        errors = validate_expansion(payload)
        if errors:
            print(json.dumps({"verdict": "BLOCK", "errors": errors}, indent=2), file=sys.stderr)
            return 1
        Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"verdict": "PASS", "out": args.out}, indent=2))
        return 0
    if args.cmd == "validate":
        payload = load_expansion_file(Path(args.response))
        errors = validate_expansion(payload)
        print(json.dumps({"verdict": "BLOCK" if errors else "PASS", "errors": errors}, indent=2))
        return 1 if errors else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
