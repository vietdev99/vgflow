"""
Parse runtime_contract block from skill-MD frontmatter.
Substitute ${PHASE_DIR} and ${PHASE_NUMBER} template variables.

Tier B addition (2026-04-26):
  parse_for_phase(phase, command) — pin-aware contract loader. If
  .vg/phases/{phase}/.contract-pins.json exists with an entry for
  `command`, override must_touch_markers + must_emit_telemetry with
  pinned values. This freezes the marker/telemetry contract per-phase
  so harness upgrades don't retroactively invalidate already-shipped
  phases. Other fields (must_write, forbidden_without_override) still
  load from the current skill.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from _repo_root import find_repo_root

REPO_ROOT = find_repo_root(__file__)
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands" / "vg"
PHASES_DIR = REPO_ROOT / ".vg" / "phases"
PIN_FILENAME = ".contract-pins.json"


def parse(command: str) -> dict | None:
    """
    Read .claude/commands/vg/{cmd}.md, extract runtime_contract.
    Returns parsed dict or None if absent. Validates against JSON Schema
    when PyYAML + jsonschema available — typos caught at load-time, not
    runtime. Prints schema errors to stderr but returns parsed dict for
    best-effort operation (never hard-fail a misconfigured skill-MD).
    """
    cmd_name = command.replace("vg:", "").replace("/", "")
    cmd_file = COMMANDS_DIR / f"{cmd_name}.md"
    if not cmd_file.exists():
        return None

    text = cmd_file.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return None

    end = re.search(r"\n---\s*\n", text[4:])
    if not end:
        return None
    fm_text = text[4:4 + end.start()]

    try:
        import yaml  # type: ignore
        fm = yaml.safe_load(fm_text) or {}
        contract = fm.get("runtime_contract")
    except ImportError:
        contract = _fallback_parse(fm_text)

    # Schema validation — best-effort. Prints warnings to stderr, doesn't
    # block parse (preserves current behavior where skills work even if
    # PyYAML/jsonschema missing in hook env).
    if contract:
        _validate_against_schema(contract, command)

    return contract


def _validate_against_schema(contract: dict, command: str) -> None:
    """Load .claude/schemas/runtime-contract.json, validate contract, warn on errors."""
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return  # jsonschema not installed — skip silently

    schema_path = (COMMANDS_DIR.parent.parent / "schemas" /
                   "runtime-contract.json")
    if not schema_path.exists():
        return

    try:
        import sys
        schema = __import__("json").loads(
            schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(contract))
        if errors:
            print(
                f"⚠ runtime_contract schema issues in {command}:",
                file=sys.stderr,
            )
            for err in errors[:5]:  # cap output
                path = ".".join(str(p) for p in err.absolute_path) or "<root>"
                print(f"  [{path}] {err.message}", file=sys.stderr)
    except Exception:
        # Never block on validation infrastructure failure
        pass


def _fallback_parse(fm_text: str) -> dict | None:
    """PyYAML-free parser — subset of runtime_contract shape.
    Used when PyYAML not installed in hook environment.

    Handles block-form list objects with ANY starter field name
    (e.g. `- name: crossai_review`, `- event_type: scope.completed`)
    plus simple string list items. Extended (OHOK-9 d) to parse the
    marker severity/waiver fields — name: / severity: / namespace: /
    required_unless_flag: — via the generic nested field pattern.
    """
    # OHOK Batch 2 fix: allow blank lines inside the block so multi-line
    # marker entries like `- name: X\n  severity: warn` stay grouped with
    # their neighbours. Previous regex stopped at first empty line, cutting
    # off ~80% of extended contracts. Strategy: split fm_text, find block
    # start manually, consume while lines are indented OR blank.
    lines = fm_text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^runtime_contract:\s*$", line):
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    end_idx = start_idx
    while end_idx < len(lines):
        ln = lines[end_idx]
        if ln == "" or ln.startswith((" ", "\t")):
            end_idx += 1
            continue
        break
    block_lines = lines[start_idx:end_idx]
    # Re-use original algorithm on block_lines directly
    m = type('M', (), {'group': lambda self, n: '\n'.join(block_lines) + '\n'})()
    if not m:
        return None
    block = m.group(1)
    contract: dict = {}
    current_key: str | None = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Top-level list key
        key_m = re.match(r"^  ([a-z_]+):\s*$", line)
        if key_m:
            current_key = key_m.group(1)
            contract[current_key] = []
            continue
        # List item: starter-field object  `- name: value` or `- event_type: value`
        obj_start = re.match(
            r"^    -\s+([a-z_]+):\s*\"?([^\"#]+?)\"?\s*$", line,
        )
        if obj_start and current_key:
            contract[current_key].append({
                obj_start.group(1): obj_start.group(2).strip(),
            })
            continue
        # Simple list item (string) — must come AFTER obj_start to avoid
        # eating `- key: value` as plain string.
        item_m = re.match(r"^    -\s+\"?([^\"#:]+)\"?\s*$", line)
        if item_m and current_key:
            contract[current_key].append(item_m.group(1).strip())
            continue
        # Nested field on last object item (indent 6)
        nested_m = re.match(r"^      ([a-z_]+):\s*\"?([^\"#]+?)\"?\s*$", line)
        if nested_m and current_key and contract[current_key]:
            last = contract[current_key][-1]
            if isinstance(last, dict):
                last[nested_m.group(1)] = nested_m.group(2).strip()
    return contract


def _read_phase_pin(phase: str, command: str) -> dict | None:
    """Read pinned contract for (phase, command) from
    .vg/phases/{phase}/.contract-pins.json. Returns None when no pin
    file exists, the file is malformed, or no entry matches `command`.
    """
    phase_dir = resolve_phase_dir(phase)
    if not phase_dir:
        return None
    pin_file = phase_dir / PIN_FILENAME
    if not pin_file.exists():
        return None
    try:
        data = json.loads(pin_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return (data.get("commands") or {}).get(command)


def parse_for_phase(phase: str, command: str) -> dict | None:
    """Pin-aware contract loader.

    Resolution order:
      1. Parse current skill via parse(command) — provides full contract
         (must_write, forbidden_without_override, etc.).
      2. If .contract-pins.json has an entry for this (phase, command),
         OVERRIDE must_touch_markers + must_emit_telemetry with the
         pinned values. Other fields keep current-skill values.

    Why partial override:
      must_touch_markers + must_emit_telemetry change with skill version
      and break legacy phases. Other contract fields (must_write paths,
      forbidden flags) are stable enough to safely track current skill.
    """
    contract = parse(command)
    pinned = _read_phase_pin(phase, command)
    if not pinned:
        return contract
    # Pin exists — copy current contract and override the volatile fields.
    merged = dict(contract or {})
    if "must_touch_markers" in pinned:
        # Pinned schema can be either a flat list of marker names (Tier B
        # canonical form) or the original skill structure (mix of strings
        # and {name, severity} dicts). normalize_markers downstream handles
        # both shapes.
        merged["must_touch_markers"] = pinned["must_touch_markers"]
    if "must_emit_telemetry" in pinned:
        # Pinned form is a flat list of event_type strings; expand to the
        # `event_type:` dict shape that the downstream verifier expects.
        merged["must_emit_telemetry"] = [
            {"event_type": e} if isinstance(e, str) else e
            for e in pinned["must_emit_telemetry"]
        ]
    return merged


def resolve_phase_dir(phase: str) -> Path | None:
    """Find phase dir accepting multiple naming conventions.

    Mirrors bash phase-resolver.sh logic (OHOK v2 Day 5). Handles:
    - canonical: `07.13` → `07.13-dsp-*`
    - zero-pad: `7.13` → `07.13-*` (split on dot, pad major part only)
    - three-level decimal: `07.0.1` → `07.0.1-*`
    - bare dir (legacy GSD migration): `07` → `07/` (no dash suffix)
    - exact-beats-prefix: `07.12` MUST match `07.12-*` not `07.12.1-*`

    Previously broke because `phase.zfill(2)` on `7.13` stayed `7.13`
    (zfill pads the whole string, not the major part of decimal).
    User screenshot 2026-04-22 showed `7.13` → "Phase dir not found" even
    though `07.13-dsp-full-rebuild` existed. OHOK v2 follow-up fix.
    """
    if not phase or not PHASES_DIR.exists():
        return None

    # Step 1: exact match with dash suffix (prevents 07.12 matching 07.12.1-*)
    candidates = list(PHASES_DIR.glob(f"{phase}-*"))
    if candidates:
        return candidates[0]

    # Step 1b: exact bare-dir match (legacy GSD dirs like `00/`, `07/`)
    bare = PHASES_DIR / phase
    if bare.is_dir():
        return bare

    # Step 2: zero-pad the MAJOR part (before first dot)
    # `7.13` → major=`7`, rest=`13` → normalized=`07.13`
    # `7`    → major=`7`, rest=``   → normalized=`07`
    # `07.1` → major=`07`, already 2-wide → unchanged
    if "." in phase:
        major, _, rest = phase.partition(".")
    else:
        major, rest = phase, ""

    if major.isdigit() and len(major) < 2:
        normalized_major = major.zfill(2)
        normalized = f"{normalized_major}.{rest}" if rest else normalized_major
        if normalized != phase:
            candidates = list(PHASES_DIR.glob(f"{normalized}-*"))
            if candidates:
                return candidates[0]
            bare_norm = PHASES_DIR / normalized
            if bare_norm.is_dir():
                return bare_norm

    return None


def substitute(template: str, phase: str, phase_dir: Path | None) -> str:
    """Replace ${PHASE_DIR}, ${PHASE_NUMBER} in path templates.

    When phase_dir is None (phase not yet created on disk), substitute with
    a readable glob placeholder so violation messages point users at the
    right location instead of leaking the literal ${PHASE_DIR} token.
    """
    out = template.replace("${PHASE_NUMBER}", phase)
    if phase_dir is not None:
        out = out.replace("${PHASE_DIR}", str(phase_dir))
    else:
        out = out.replace("${PHASE_DIR}", f".vg/phases/{phase}-<missing>")
    return out


# ─── Phase profile detection (v2.2 OHOK-9) ────────────────────────────
# Drives profile-aware artifact gating in _verify_contract. Matches the
# helper in .claude/commands/vg/_shared/lib/phase-profile.sh.

_PROFILE_KEYWORDS = {
    "migration": [r"\bmigration\b", r"\brollback\b", r"\bschema\s+change\b"],
    "hotfix":    [r"\bhotfix\b", r"\bhot[-\s]fix\b"],
    "bugfix":    [r"\bbugfix\b", r"\bbug[-\s]fix\b", r"^\s*issue[_-]?id\s*:"],
    "infra":     [r"\binfra(structure)?\b", r"\bansible\b", r"\bterraform\b",
                  r"\bVPS\b", r"\bdocker\s+compose\b"],
    "docs":      [r"\bdocumentation\b", r"^\s*#\s+Documentation\b"],
}

# Artifacts REQUIRED per profile. Anything missing from the profile's list
# converts to a WARN (not a BLOCK) when _verify_contract sees must_write.
_PROFILE_REQUIRED_ARTIFACTS = {
    "feature":   {"SPECS.md", "CONTEXT.md", "PLAN.md", "API-CONTRACTS.md",
                  "TEST-GOALS.md", "SUMMARY.md", "DISCUSSION-LOG.md",
                  "api-contract-precheck.txt"},
    "infra":     {"SPECS.md", "PLAN.md", "SUMMARY.md"},
    "hotfix":    {"SPECS.md", "PLAN.md", "SUMMARY.md"},
    "bugfix":    {"SPECS.md", "PLAN.md", "SUMMARY.md"},
    "migration": {"SPECS.md", "PLAN.md", "SUMMARY.md", "ROLLBACK.md"},
    "docs":      {"SPECS.md"},
}


def detect_phase_profile(phase: str) -> str:
    """Detect phase profile from SPECS.md frontmatter + body keywords.
    Falls back to 'feature' when SPECS missing or ambiguous.
    Mirrors the bash helper at _shared/lib/phase-profile.sh."""
    import re as _re
    phase_dir = resolve_phase_dir(phase)
    if phase_dir is None:
        return "feature"
    specs = phase_dir / "SPECS.md"
    if not specs.exists():
        return "feature"
    try:
        text = specs.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "feature"

    # Frontmatter wins if explicit
    fm_match = _re.match(r"^---\s*\n(.+?)\n---\s*\n", text, _re.DOTALL)
    if fm_match:
        fm = fm_match.group(1)
        m = _re.search(r"^\s*profile\s*:\s*[\"']?(\w+)",
                       fm, _re.MULTILINE)
        if m and m.group(1).lower() in _PROFILE_REQUIRED_ARTIFACTS:
            return m.group(1).lower()

    # Heuristic — first matching profile wins (most specific first)
    for prof in ("migration", "hotfix", "bugfix", "infra", "docs"):
        for pat in _PROFILE_KEYWORDS.get(prof, []):
            if _re.search(pat, text, _re.IGNORECASE | _re.MULTILINE):
                return prof
    return "feature"


def artifact_applicable(profile: str, path: str) -> bool:
    """True if the artifact filename is required for this phase profile.
    Used to convert 'missing' violations into WARN for non-applicable
    artifacts on non-feature profiles (e.g. CONTEXT.md on infra phase).
    """
    from pathlib import Path as _Path
    name = _Path(path).name
    required = _PROFILE_REQUIRED_ARTIFACTS.get(
        profile, _PROFILE_REQUIRED_ARTIFACTS["feature"]
    )
    # Normalize: strip phase-number prefix so `14-UAT.md` → `UAT.md`
    stripped = re.sub(r"^[0-9.]+-", "", name)
    return stripped in required or name in required


def normalize_must_write(items: list) -> list[dict]:
    """Normalize mixed string/dict items to unified dict shape.

    v2.5 extensions (anti-forge patch):
    - glob_min_count: int — path is treated as a glob pattern; ≥N matches required
    - required_unless_flag: str — check waived when flag appears in run_args

    v2.5.2 Phase K extensions (artifact-run binding):
    - must_be_created_in_run: bool — require evidence manifest entry
      with creator_run_id == current run (default: False to preserve
      legacy behavior; new contracts opt in explicitly)
    - check_provenance: bool — also verify source_inputs in manifest
      still hash the same on disk (default: False)
    """
    result = []
    for item in items or []:
        if isinstance(item, str):
            result.append({"path": item, "content_min_bytes": 1,
                           "content_required_sections": [],
                           "glob_min_count": None,
                           "required_unless_flag": None,
                           "must_be_created_in_run": False,
                           "check_provenance": False})
        elif isinstance(item, dict) and "path" in item:
            result.append({
                "path": item["path"],
                "content_min_bytes": int(item.get("content_min_bytes", 1)),
                "content_required_sections": item.get(
                    "content_required_sections", []
                ),
                "glob_min_count": item.get("glob_min_count"),
                "required_unless_flag": item.get("required_unless_flag"),
                "must_be_created_in_run": bool(
                    item.get("must_be_created_in_run", False)
                ),
                "check_provenance": bool(item.get("check_provenance", False)),
            })
    return result


def normalize_markers(items: list) -> list[dict]:
    """Normalize markers to {name, namespace, severity, required_unless_flag}.

    Extended schema (OHOK-9 d):
    - severity: "block" (default) | "warn" — warn emits telemetry event
      `contract.marker_warn` instead of violation.
    - required_unless_flag: str — if flag present in run_args, marker
      check is skipped entirely (e.g. `--skip-crossai` waives crossai
      marker requirement, matching the step's skip semantics).
    String-form items keep default severity=block and no flag waiver
    (backward compat — existing contracts don't change meaning).
    """
    result = []
    for item in items or []:
        if isinstance(item, str):
            result.append({
                "name": item, "namespace": "shared",
                "severity": "block", "required_unless_flag": None,
            })
        elif isinstance(item, dict) and "name" in item:
            result.append({
                "name": item["name"],
                "namespace": item.get("namespace", "shared"),
                "severity": item.get("severity", "block"),
                "required_unless_flag": item.get("required_unless_flag"),
            })
    return result


def normalize_telemetry(items: list) -> list[dict]:
    """Normalize telemetry requirements to unified dict shape.

    v2.5 extension (anti-forge patch):
    - required_unless_flag: str — check waived when flag appears in run_args.
      Closes gap where AI touched marker but skipped actual CrossAI invoke.
    """
    result = []
    for item in items or []:
        if isinstance(item, str):
            result.append({"event_type": item, "min_count": 1,
                           "required_unless_flag": None})
        elif isinstance(item, dict) and "event_type" in item:
            result.append({
                "event_type": item["event_type"],
                "phase": item.get("phase"),
                "min_count": int(item.get("min_count", 1)),
                "must_pair_with": item.get("must_pair_with"),
                "required_unless_flag": item.get("required_unless_flag"),
            })
    return result
