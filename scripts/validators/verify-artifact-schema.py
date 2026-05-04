#!/usr/bin/env python3
"""
Validator: verify-artifact-schema.py

Phase E (v2.7, 2026-04-26): locks the YAML-frontmatter shape of the 6 core VG
artifacts (SPECS.md, CONTEXT.md, PLAN.md, TEST-GOALS.md, SUMMARY.md, UAT.md)
against versioned JSON Schemas at `.claude/schemas/`.

Strict frontmatter (additionalProperties: false) + lenient body (required H2
sections checked via regex). Single validator, dispatched per producer step
post-write. See `.vg/workflow-hardening-v2.7/SPEC-E.md` for the normative spec.

Usage:
  verify-artifact-schema.py --phase <N> --artifact {specs|context|plan|test-goals|summary|uat}
  verify-artifact-schema.py --phase <N> --all

Severity:
  BLOCK — frontmatter type/enum/required violation; missing required H2 section
  WARN  — soft body checks (decision-ID monotonicity, count drift)
  PASS  — file absent (skip silently); schema clean

Backward-compat:
  Env VG_SCHEMA_GRANDFATHER_BEFORE=<phase-major> skips artifacts whose phase
  major number is below the cutoff (default unset = check all).

Exit codes:
  0 PASS or WARN-only
  1 BLOCK
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
SCHEMA_DIR = REPO_ROOT / ".claude" / "schemas"

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)

# Canonical artifact filenames (case-sensitive). UAT also accepts legacy
# `${phase}-UAT.md` form written by the current accept.md skill body —
# resolution handled in _resolve_artifact_path.
ARTIFACT_FILES = {
    "specs": "SPECS.md",
    "context": "CONTEXT.md",
    "plan": "PLAN.md",
    "test-goals": "TEST-GOALS.md",
    "summary": "SUMMARY.md",
    "uat": "UAT.md",
}

# Per-artifact required H2 anchors (regex, compiled at module load).
# Lenient: each anchor must appear at least once in the body. Authors free to
# reorder, add subsections, or interleave prose.
BODY_H2_REQUIRED = {
    "specs": [
        r"^##\s+Goal\b",
        r"^##\s+Scope\b",
        r"^##\s+Out of [Ss]cope\b",
        r"^##\s+Constraints\b",
        r"^##\s+Success criteria\b",
    ],
    "context": [
        r"^##\s+Goals\b",
        r"^##\s+Decisions\b",
        r"^##\s+Open questions\b",
        r"^##\s+Risks\b",
    ],
    "plan": [
        r"^##\s+Verification\b",
        r"^##\s+Risks\b",
    ],
    "test-goals": [],
    "summary": [
        r"^##\s+Tasks shipped\b",
        r"^##\s+Files touched\b",
        r"^##\s+Goal coverage\b",
        r"^##\s+Deviations\b",
        r"^##\s+Next steps\b",
    ],
    "uat": [
        r"^##\s+Login \+ setup\b",
        r"^##\s+Per-goal verification\b",
        r"^##\s+Deviations from acceptance criteria\b",
        r"^##\s+Sign-off\b",
    ],
}

DECISION_HEADING_RE = re.compile(r"^###\s+D-(\d{2,3}):\s+.+", re.MULTILINE)
GOAL_HEADING_RE = re.compile(r"^##\s+G-(\d+):\s+.+", re.MULTILINE)
WAVE_HEADING_RE = re.compile(r"^##\s+Wave\s+(\d+)\b", re.MULTILINE | re.IGNORECASE)


# ---------------------------------------------------------------------------
# Hand-rolled minimal JSON Schema walker (~150 LOC, no external dep)
# ---------------------------------------------------------------------------


def _type_check(value, expected: str) -> bool:
    import datetime
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        # YAML auto-coerces unquoted ISO dates to datetime.date / datetime.datetime
        # objects. Treat those as strings since they serialize back to ISO strings
        # round-trip — authors shouldn't have to manually quote every date field.
        return isinstance(value, (str, datetime.date, datetime.datetime))
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _validate_against_schema(data, schema, pointer: str, violations: list[dict]) -> None:
    """Walk schema keywords against data; append violations.

    Supported keywords: type, required, enum, pattern, minimum, maximum,
    minLength, maxLength, minItems, maxItems, items, properties,
    additionalProperties. Unsupported keywords are silently ignored.
    """
    if not isinstance(schema, dict):
        return

    expected_type = schema.get("type")
    if expected_type and not _type_check(data, expected_type):
        violations.append({
            "pointer": pointer or "/",
            "rule": "type",
            "message": f"Expected {expected_type}, got {type(data).__name__}",
        })
        return  # type mismatch — downstream checks would all fail

    if "enum" in schema and data not in schema["enum"]:
        violations.append({
            "pointer": pointer or "/",
            "rule": "enum",
            "message": (
                f"Value {data!r} not in enum {schema['enum']!r}"
            ),
        })

    import datetime as _dt
    string_repr = None
    if isinstance(data, str):
        string_repr = data
    elif isinstance(data, (_dt.date, _dt.datetime)):
        string_repr = data.isoformat()

    if string_repr is not None:
        if "pattern" in schema:
            if not re.search(schema["pattern"], string_repr):
                violations.append({
                    "pointer": pointer or "/",
                    "rule": "pattern",
                    "message": (
                        f"Value {string_repr!r} does not match pattern "
                        f"{schema['pattern']!r}"
                    ),
                })
        if "minLength" in schema and len(string_repr) < schema["minLength"]:
            violations.append({
                "pointer": pointer or "/",
                "rule": "minLength",
                "message": (
                    f"String length {len(string_repr)} < minLength {schema['minLength']}"
                ),
            })
        if "maxLength" in schema and len(string_repr) > schema["maxLength"]:
            violations.append({
                "pointer": pointer or "/",
                "rule": "maxLength",
                "message": (
                    f"String length {len(string_repr)} > maxLength {schema['maxLength']}"
                ),
            })

    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            violations.append({
                "pointer": pointer or "/",
                "rule": "minimum",
                "message": f"Value {data} < minimum {schema['minimum']}",
            })
        if "maximum" in schema and data > schema["maximum"]:
            violations.append({
                "pointer": pointer or "/",
                "rule": "maximum",
                "message": f"Value {data} > maximum {schema['maximum']}",
            })

    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            violations.append({
                "pointer": pointer or "/",
                "rule": "minItems",
                "message": (
                    f"Array length {len(data)} < minItems {schema['minItems']}"
                ),
            })
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            violations.append({
                "pointer": pointer or "/",
                "rule": "maxItems",
                "message": (
                    f"Array length {len(data)} > maxItems {schema['maxItems']}"
                ),
            })
        item_schema = schema.get("items")
        if item_schema:
            for idx, item in enumerate(data):
                _validate_against_schema(
                    item, item_schema, f"{pointer}/{idx}", violations,
                )

    if isinstance(data, dict):
        for req_key in schema.get("required", []):
            if req_key not in data:
                violations.append({
                    "pointer": f"{pointer}/{req_key}",
                    "rule": "required",
                    "message": f"Required property '{req_key}' is missing",
                })
        properties = schema.get("properties", {}) or {}
        for key, value in data.items():
            if key in properties:
                _validate_against_schema(
                    value, properties[key], f"{pointer}/{key}", violations,
                )
        addl = schema.get("additionalProperties", True)
        if addl is False:
            for key in data.keys():
                if key not in properties:
                    violations.append({
                        "pointer": f"{pointer}/{key}",
                        "rule": "additionalProperties",
                        "message": (
                            f"Property '{key}' not allowed by schema "
                            f"(additionalProperties: false)"
                        ),
                    })


# ---------------------------------------------------------------------------
# Artifact-specific helpers
# ---------------------------------------------------------------------------


def _resolve_artifact_path(phase_dir: Path, artifact: str) -> Path | None:
    """Return path to artifact in phase_dir, or None if missing.

    Tries canonical name first (e.g. UAT.md). Falls back to legacy prefixed
    forms (e.g. `${phase}-UAT.md`) for older phase directories.
    """
    canonical = phase_dir / ARTIFACT_FILES[artifact]
    if canonical.exists():
        return canonical
    # Legacy fallback: prefixed form like `05-UAT.md`, `7.14.3-UAT.md`.
    suffix = ARTIFACT_FILES[artifact]
    for child in phase_dir.iterdir():
        if child.is_file() and child.name.endswith(f"-{suffix}"):
            return child
    return None


def _parse_frontmatter(text: str) -> tuple[dict | None, str | None]:
    """Returns (frontmatter_dict, error). frontmatter_dict is {} if absent."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, None
    raw = m.group(1)
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return None, f"YAML parse error: {exc}"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, f"Frontmatter must be a YAML mapping, got {type(data).__name__}"
    return data, None


def _load_schema(artifact: str) -> dict:
    schema_path = SCHEMA_DIR / f"{artifact}.v1.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _check_body(artifact: str, text: str, frontmatter: dict, out: Output) -> None:
    """Apply body H2 regex requirements + soft per-artifact body checks."""
    # Strip frontmatter from body for cleaner regex ops.
    body = FRONTMATTER_RE.sub("", text, count=1)

    for h2_pattern in BODY_H2_REQUIRED.get(artifact, []):
        if not re.search(h2_pattern, body, re.MULTILINE):
            out.add(Evidence(
                type="missing_required_section",
                message=(
                    f"{artifact.upper()}.md body missing required H2 section "
                    f"matching {h2_pattern!r}"
                ),
                fix_hint=(
                    f"Add a top-level '## ' heading matching {h2_pattern!r} "
                    f"per SPEC-E section 4. Authors free to add subsections "
                    f"and reorder, but the anchor must exist."
                ),
            ))

    # Soft checks per artifact type.
    if artifact == "context":
        decisions = [int(m.group(1)) for m in DECISION_HEADING_RE.finditer(body)]
        if decisions and decisions != sorted(decisions):
            out.warn(Evidence(
                type="decision_ids_not_monotonic",
                message=(
                    f"CONTEXT.md decision IDs are not monotonically increasing: "
                    f"{decisions}. Re-order or renumber for forensic readability."
                ),
            ))

    if artifact == "plan":
        total_waves = frontmatter.get("total_waves")
        wave_matches = WAVE_HEADING_RE.findall(body)
        wave_count = len(wave_matches)
        if isinstance(total_waves, int) and wave_count != total_waves:
            out.add(Evidence(
                type="wave_count_mismatch",
                message=(
                    f"PLAN.md frontmatter declares total_waves={total_waves} "
                    f"but body contains {wave_count} '## Wave N' H2 sections."
                ),
                fix_hint=(
                    "Either add the missing Wave H2 anchors or update "
                    "frontmatter.total_waves to match body."
                ),
            ))

    if artifact == "test-goals":
        goal_count_fm = frontmatter.get("goal_count")
        goal_ids = [int(m.group(1)) for m in GOAL_HEADING_RE.finditer(body)]
        body_goal_count = len(goal_ids)
        if isinstance(goal_count_fm, int) and body_goal_count != goal_count_fm:
            out.add(Evidence(
                type="goal_count_mismatch",
                message=(
                    f"TEST-GOALS.md frontmatter declares goal_count={goal_count_fm} "
                    f"but body contains {body_goal_count} '## G-XX:' goal headings."
                ),
                fix_hint=(
                    "Either add the missing goal H2 anchors or update "
                    "frontmatter.goal_count to match body."
                ),
            ))

    if artifact == "uat":
        verdict = frontmatter.get("verdict")
        passed = frontmatter.get("goals_passed")
        failed = frontmatter.get("goals_failed")
        verified = frontmatter.get("total_goals_verified")
        if (isinstance(passed, int) and isinstance(failed, int)
                and isinstance(verified, int)
                and (passed + failed) > verified):
            out.add(Evidence(
                type="uat_count_drift",
                message=(
                    f"UAT.md goals_passed ({passed}) + goals_failed ({failed}) "
                    f"= {passed + failed} > total_goals_verified ({verified})."
                ),
            ))
        if verdict == "ACCEPTED" and isinstance(failed, int) and failed != 0:
            out.add(Evidence(
                type="uat_verdict_inconsistent",
                message=(
                    f"UAT.md verdict=ACCEPTED but goals_failed={failed} (non-zero). "
                    f"Switch verdict to CONDITIONAL or REJECTED, or resolve failures."
                ),
            ))


def _check_artifact(
    artifact: str, phase: str, phase_dir: Path, out: Output,
) -> None:
    path = _resolve_artifact_path(phase_dir, artifact)
    if path is None:
        # Skip silently — artifact may not have been produced yet at this point
        # in the pipeline. Producer steps invoke validator post-write so absence
        # at validation time = pre-write state, not a violation.
        return

    text = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, err = _parse_frontmatter(text)
    if err:
        out.add(Evidence(
            type="frontmatter_parse_error",
            message=f"{path.name}: {err}",
            file=str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path),
            fix_hint=(
                "Frontmatter must be valid YAML wrapped in '---' delimiters at "
                "the top of the file."
            ),
        ))
        return

    schema = _load_schema(artifact)
    violations: list[dict] = []
    _validate_against_schema(
        frontmatter or {}, schema, "/frontmatter", violations,
    )

    rel_path = (
        str(path.relative_to(REPO_ROOT))
        if path.is_relative_to(REPO_ROOT) else str(path)
    )
    for v in violations:
        out.add(Evidence(
            type=f"schema_{v['rule']}",
            message=f"{path.name} {v['pointer']}: {v['message']}",
            file=rel_path,
            fix_hint=(
                f"Fix the frontmatter field at pointer {v['pointer']} per "
                f".claude/schemas/{artifact}.v1.json"
            ),
        ))

    # Body checks run regardless of frontmatter outcome — surfaces body drift
    # even when frontmatter is broken (gives author a complete picture).
    _check_body(artifact, text, frontmatter or {}, out)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _grandfathered(phase: str) -> bool:
    cutoff = os.environ.get("VG_SCHEMA_GRANDFATHER_BEFORE", "").strip()
    if not cutoff:
        return False
    try:
        cutoff_int = int(cutoff)
    except ValueError:
        return False
    major_str = phase.split(".")[0].split("-")[0]
    try:
        major = int(major_str)
    except ValueError:
        return False
    return major < cutoff_int


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        allow_abbrev=False,
    )
    ap.add_argument("--phase", required=True)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--artifact",
        choices=sorted(ARTIFACT_FILES.keys()),
        help="Validate a single artifact type",
    )
    group.add_argument(
        "--all", action="store_true",
        help="Validate every present artifact for the phase",
    )
    args = ap.parse_args()

    out = Output(validator="verify-artifact-schema")
    with timer(out):
        if _grandfathered(args.phase):
            emit_and_exit(out)

        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            # Phase dir not found — soft pass (downstream gates catch).
            emit_and_exit(out)

        artifacts = (
            sorted(ARTIFACT_FILES.keys()) if args.all else [args.artifact]
        )
        for artifact in artifacts:
            _check_artifact(artifact, args.phase, Path(phase_dir), out)

    emit_and_exit(out)


if __name__ == "__main__":
    main()
