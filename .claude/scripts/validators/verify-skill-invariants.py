#!/usr/bin/env python3
"""
verify-skill-invariants.py — Phase P validator (v2.7).

Single validator covering BOTH:

  (A) Skill structural invariants (BLOCK on violation):
      - Step numbering monotonic (allow intentional sub-steps like 0.5, 8.5,
        but flag big gaps where intermediates are missing).
      - Frontmatter YAML valid + required fields per config
        (`description`, `user-invocable`, `model`).
      - Every <step name="X"> has a marker write OR an explicit
        `<!-- no-marker: <reason> -->` comment.
      - SKILL.md and corresponding `.claude/commands/vg/X.md` agree on
        step count + names (sync gate).

  (B) Manual-card schema invariants (WARN on soft violation, BLOCK on hard):
      - Body length ≤ N chars (config: manual_card_max_body_chars, default 200).
      - --tag must be one of `enforce|remind|advisory`.
      - When `enforce` set, --validator must reference an existing
        `.claude/scripts/validators/<name>.py`.
      - Anti-pattern entries require an --incident reference (commit-hash
        format `[a-f0-9]{7,40}` OR phase ID format `\\d+(\\.\\d+)*`).

Output:
  Standard validator JSON {validator, verdict, evidence, duration_ms}
  matching v2.6.1 canonical schema. Verdict ∈ {PASS, BLOCK, WARN}.

CLI:
  verify-skill-invariants.py [--skill <name>] [--all] [--json]
                             [--check-schema-only] [--check-invariants-only]

Stdlib only — uses regex for YAML frontmatter (frontmatter is flat dict).

Phase P, harness v2.7. Wired at /vg:accept step 1 (artifact precheck) for
all 45 vg-* skills. UNQUARANTINABLE (closes "skill drift can silently break
workflow" gap).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]

VALID_TAGS = {"enforce", "remind", "advisory"}

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "enforce_severity": "block",
    "schema_severity": "warn",
    "manual_card_max_body_chars": 200,
    "required_frontmatter_fields": ["description", "user-invocable", "model"],
    "enforce_tag_requires_validator": True,
}


def _load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Read validators_skill_invariants block from .claude/vg.config.md.

    Stdlib regex parser (frontmatter sub-block is small + flat enough).
    Falls back to DEFAULT_CONFIG when file missing or block absent.
    """
    cfg = dict(DEFAULT_CONFIG)
    cfg_path = config_path if config_path else REPO_ROOT / ".claude" / "vg.config.md"
    if not cfg_path.exists():
        return cfg
    try:
        text = cfg_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return cfg

    # Find validators_skill_invariants: block + sibling-indented child keys
    block_re = re.compile(
        r"^validators_skill_invariants:\s*\n((?:[ \t]+[^\n]*\n)+)",
        re.MULTILINE,
    )
    m = block_re.search(text)
    if not m:
        return cfg
    block = m.group(1)

    # Each indented line: "  key: value"
    for line in block.splitlines():
        kv = re.match(
            r"^[ \t]+([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.+?)\s*(?:#.*)?$",
            line,
        )
        if not kv:
            continue
        key, raw = kv.group(1), kv.group(2).strip()
        # int
        if raw.isdigit():
            cfg[key] = int(raw)
            continue
        # bool
        if raw.lower() in ("true", "false"):
            cfg[key] = raw.lower() == "true"
            continue
        # YAML inline list ["a", "b"]
        list_m = re.match(r'^\[(.+)\]$', raw)
        if list_m:
            inner = list_m.group(1)
            items = [
                x.strip().strip('"').strip("'")
                for x in inner.split(",") if x.strip()
            ]
            cfg[key] = items
            continue
        # quoted string
        cfg[key] = raw.strip('"').strip("'")

    return cfg


# ---------------------------------------------------------------------------
# Frontmatter parser (regex-based, stdlib only)
# ---------------------------------------------------------------------------

def _parse_frontmatter(skill_md_text: str) -> tuple[dict[str, Any] | None, str]:
    """Extract YAML frontmatter as flat dict via regex.

    Returns (fields_dict, error_message). fields_dict is None when frontmatter
    is missing or malformed; error_message non-empty in that case.

    Handles:
      key: "value"
      key: value
      key:
        nested: val   (nested dict — flattened with dotted keys when leaf)
    """
    if not skill_md_text.startswith("---"):
        return None, "frontmatter missing — file does not start with '---'"

    end_match = re.search(r"\n---\s*\n", skill_md_text)
    if not end_match:
        return None, "frontmatter never closed — no trailing '---' delimiter"

    fm_text = skill_md_text[3:end_match.start()]
    fields: dict[str, Any] = {}
    current_parent: str | None = None

    for raw in fm_text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        # Top-level key (no leading indentation)
        m_top = re.match(r"^([a-zA-Z_][a-zA-Z0-9_-]*)\s*:\s*(.*)$", line)
        if m_top and not line.startswith((" ", "\t")):
            key, val = m_top.group(1), m_top.group(2).strip()
            if val == "":
                # parent-only — record key as present (boolean true) and
                # capture any nested children below
                current_parent = key
                fields[key] = {}
                continue
            current_parent = None
            # strip surrounding quotes
            if (val.startswith('"') and val.endswith('"')) or \
               (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            fields[key] = val
            continue

        # Nested under current_parent
        if current_parent and line.startswith((" ", "\t")):
            m_n = re.match(
                r"^[ \t]+([a-zA-Z_][a-zA-Z0-9_-]*)\s*:\s*(.*)$",
                line,
            )
            if m_n:
                nk, nv = m_n.group(1), m_n.group(2).strip()
                if (nv.startswith('"') and nv.endswith('"')) or \
                   (nv.startswith("'") and nv.endswith("'")):
                    nv = nv[1:-1]
                if isinstance(fields.get(current_parent), dict):
                    fields[current_parent][nk] = nv

    return fields, ""


def _frontmatter_has_field(fields: dict[str, Any], field: str) -> bool:
    """Required-field presence check — top-level OR nested under metadata.

    Many skills declare `description` at top OR `metadata.short-description`.
    Treat either form as satisfying the `description` requirement. Same for
    `user-invocable` (might be `userInvocable` historically — accept hyphen
    variant only since the config key uses hyphen explicitly).
    """
    if field in fields and fields[field] not in (None, ""):
        return True
    # Check metadata.<field>
    md = fields.get("metadata")
    if isinstance(md, dict) and field in md and md[field] not in (None, ""):
        return True
    # description fallback: metadata.short-description
    if field == "description":
        if isinstance(md, dict) and md.get("short-description"):
            return True
    return False


# ---------------------------------------------------------------------------
# Step extraction
# ---------------------------------------------------------------------------

# Match real step tags only — name must be a valid identifier-ish token,
# not a literal placeholder like "..." or "{STEP_NAME}" used in narration.
STEP_RE = re.compile(
    r'<step\s+name="([a-zA-Z0-9_][a-zA-Z0-9_.-]*)"',
    re.MULTILINE,
)
NO_MARKER_RE = re.compile(
    r"<!--\s*no-marker:\s*([^\n>]+?)\s*-->",
    re.MULTILINE,
)


def _marker_re_for_step(step_name: str) -> re.Pattern:
    """Build a marker-write regex specific to one step name.

    Match either:
      .step-markers/{step_name}.done
      mark_step ... "{step_name}"
    Avoids generic `.step-markers/X.done` matching the wrong step.
    """
    quoted = re.escape(step_name)
    return re.compile(
        rf'(?:\.step-markers[/\\]{quoted}\.done|mark_step\s+[^\n]*"{quoted}")',
    )


def _major_integer(step_name: str) -> int | None:
    """Return the leading major integer of a step name, or None.

    A 'major integer' is the integer at the very start of the step name,
    where the next character is `_`, `.`, or end-of-name (NOT a letter,
    which signals an alphabetic sub-step like `1a` or `1b`).

    Examples:
      '0_init'             → 0    (pure integer base)
      '1_main'             → 1
      '5_finalize'         → 5
      '8_5_bootstrap'      → None (sub-step like 8.5 — not a major integer)
      '1a_recon'           → None (alphabetic sub-step)
      '0.5_sub'            → None (decimal sub-step)
      'create_task_tracker'→ None (not numeric)
    """
    m = re.match(r"^(\d+)(_|$)", step_name)
    if not m:
        return None
    rest = step_name[m.end(1):]
    # If next chunk is _<digits>_ → sub-step (8_5_bootstrap)
    sub_re = re.match(r"^_(\d+)(_|$)", rest)
    if sub_re:
        return None
    return int(m.group(1))


def _check_step_numbering(steps: list[str]) -> list[str]:
    """Verify monotonic step ordering — flag big gaps in pure integer chain.

    Returns list of human-readable issue messages (empty list = OK).
    Allow intentional sub-steps (e.g. 0.5, 1a, 8_5_X). Flag whole-number
    gaps in the major-integer chain (e.g. step 1 → step 4 missing 2,3).
    """
    issues: list[str] = []

    # Collect ordered list of major integers
    majors: list[int] = []
    for s in steps:
        mi = _major_integer(s)
        if mi is not None:
            majors.append(mi)

    if len(majors) < 2:
        return issues

    # Reverse-order check
    for i in range(1, len(majors)):
        if majors[i] < majors[i - 1]:
            issues.append(
                f"step ordering reversed: step {majors[i]} appears after step {majors[i - 1]}"
            )

    # Gap detection over the unique sorted major-integer set
    unique_sorted = sorted(set(majors))
    for i in range(len(unique_sorted) - 1):
        cur = unique_sorted[i]
        nxt = unique_sorted[i + 1]
        if nxt - cur >= 2:
            # Check: is there a sub-step covering the gap (e.g. 8_5 between 8 and 9)?
            # Only flag if no sub-step from the in-between integers exists.
            covered = False
            for s in steps:
                m = re.match(r"^(\d+)[_.]", s)
                if m:
                    base = int(m.group(1))
                    if cur < base < nxt:
                        covered = True
                        break
            if covered:
                continue
            missing = list(range(cur + 1, nxt))
            issues.append(
                f"step numbering gap: step {cur} → step {nxt} "
                f"(missing intermediates: {missing})"
            )

    return issues


def _check_step_markers(skill_text: str, steps: list[str]) -> list[str]:
    """Each <step name="X"> must (a) write a step-marker for THIS specific
    step, OR (b) include an explicit `<!-- no-marker: <reason> -->` comment
    within its body.

    Returns list of step names that violate.
    """
    issues: list[str] = []
    matches = list(re.finditer(
        r'<step\s+name="([a-zA-Z0-9_][a-zA-Z0-9_.-]*)"[^>]*>',
        skill_text,
    ))
    for i, m in enumerate(matches):
        name = m.group(1)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(skill_text)
        body = skill_text[body_start:body_end]

        marker_re = _marker_re_for_step(name)
        if marker_re.search(body):
            continue
        if NO_MARKER_RE.search(body):
            continue
        issues.append(name)
    return issues


# ---------------------------------------------------------------------------
# Sync check: SKILL.md ⇆ commands/vg/X.md
# ---------------------------------------------------------------------------

def _command_mirror_path(skill_name: str) -> Path:
    """Map vg-build → .claude/commands/vg/build.md, vg-review → review.md."""
    if skill_name.startswith("vg-"):
        cmd_name = skill_name[3:]
    else:
        cmd_name = skill_name
    return REPO_ROOT / ".claude" / "commands" / "vg" / f"{cmd_name}.md"


def _check_command_sync(skill_name: str, skill_steps: list[str]) -> list[str]:
    """Compare step set between SKILL.md and commands/vg/X.md mirror.

    If mirror does not exist → no sync requirement (codex-only skill).
    Returns list of diff messages (empty = synced or no-mirror).
    """
    mirror = _command_mirror_path(skill_name)
    if not mirror.exists():
        return []  # No mirror — sync not required

    try:
        mirror_text = mirror.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [f"failed to read mirror {mirror}: {e}"]

    mirror_steps = STEP_RE.findall(mirror_text)
    if not mirror_steps:
        return []  # Mirror has no <step> tags — different format, skip sync

    skill_set = list(skill_steps)
    mirror_set = list(mirror_steps)

    issues: list[str] = []
    if len(skill_set) != len(mirror_set):
        issues.append(
            f"step count mismatch: SKILL.md={len(skill_set)} vs "
            f"commands/vg/{mirror.stem}.md={len(mirror_set)}"
        )

    only_skill = [s for s in skill_set if s not in mirror_set]
    only_mirror = [s for s in mirror_set if s not in skill_set]
    if only_skill:
        issues.append(f"steps only in SKILL.md: {only_skill[:5]}")
    if only_mirror:
        issues.append(f"steps only in commands mirror: {only_mirror[:5]}")
    return issues


# ---------------------------------------------------------------------------
# Manual-card schema parser
# ---------------------------------------------------------------------------

# Match: - **MANUAL-N** [tag] → `validator`
#          body line
# Or:    - **MANUAL-N** [tag]
#          body line
MANUAL_RULE_RE = re.compile(
    r"^-\s+\*\*(MANUAL-\d+|OVERRIDE-\d+)\*\*\s*"
    r"(?:\[(?P<tag>enforce|remind|advisory|[a-z]+)\])?"
    r"(?:\s*→\s*`(?P<validator>[^`]+)`)?"
    r"\s*\n"
    r"(?P<body>(?:[ \t]+[^\n]+\n)+)",
    re.MULTILINE,
)

# Anti-pattern entries:
ANTI_RULE_RE = re.compile(
    r"^-\s+\*\*(?P<id>ANTI-\d+)\*\*\s*"
    r"(?P<body>[^\n]+(?:\n[ \t]+[^\n]+)*)",
    re.MULTILINE,
)

INCIDENT_HASH_RE = re.compile(r"\b[a-f0-9]{7,40}\b")
INCIDENT_PHASE_RE = re.compile(r"\b(?:Phase|phase)\s+\d+(?:\.\d+)*\b")
INCIDENT_INLINE_RE = re.compile(r"\bIncident\s*:", re.IGNORECASE)


def _check_manual_schema(
    skill_name: str,
    manual_text: str,
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate RULES-CARDS-MANUAL.md per Phase P schema rules.

    Returns list of issue dicts: {severity, message, rule_id}.
    Severity: 'block' for hard violations (invalid tag, missing-validator,
    missing-incident); 'warn' for soft violations (body length > cap).
    """
    issues: list[dict[str, Any]] = []
    max_chars = int(cfg.get("manual_card_max_body_chars", 200))
    require_validator = bool(cfg.get("enforce_tag_requires_validator", True))

    for m in MANUAL_RULE_RE.finditer(manual_text):
        rule_id = m.group(1)
        tag = m.group("tag")
        validator = m.group("validator")
        body_block = m.group("body").strip()

        # Tag enum check
        if tag and tag not in VALID_TAGS:
            issues.append({
                "severity": "block",
                "rule_id": rule_id,
                "skill": skill_name,
                "message": (
                    f"invalid --tag '{tag}' on {rule_id}; "
                    f"must be one of {sorted(VALID_TAGS)}"
                ),
            })
            continue  # Other checks meaningless on invalid tag

        # Body length check (warn)
        # Compute length of FIRST non-metadata body line (the rule statement).
        first_body_line = ""
        for line in body_block.splitlines():
            stripped = line.strip()
            if stripped.startswith("*Added") or not stripped:
                continue
            first_body_line = stripped
            break
        if first_body_line and len(first_body_line) > max_chars:
            issues.append({
                "severity": "warn",
                "rule_id": rule_id,
                "skill": skill_name,
                "message": (
                    f"body length {len(first_body_line)} > {max_chars} cap on {rule_id}"
                ),
            })

        # Enforce → validator existence check (block)
        if tag == "enforce" and require_validator:
            if not validator:
                issues.append({
                    "severity": "block",
                    "rule_id": rule_id,
                    "skill": skill_name,
                    "message": (
                        f"{rule_id} tagged [enforce] but no --validator referenced; "
                        f"add `→ \\`verify-X\\`` or downgrade tag"
                    ),
                })
            else:
                vpath = REPO_ROOT / ".claude" / "scripts" / "validators" / f"{validator}.py"
                if not vpath.exists():
                    issues.append({
                        "severity": "block",
                        "rule_id": rule_id,
                        "skill": skill_name,
                        "message": (
                            f"{rule_id} → `{validator}` references non-existent "
                            f"validator file (.claude/scripts/validators/{validator}.py)"
                        ),
                    })

    # Anti-pattern entries — must reference an incident
    for am in ANTI_RULE_RE.finditer(manual_text):
        anti_id = am.group("id")
        anti_body = am.group("body")
        has_incident = (
            INCIDENT_HASH_RE.search(anti_body) is not None
            or INCIDENT_PHASE_RE.search(anti_body) is not None
            or INCIDENT_INLINE_RE.search(anti_body) is not None
        )
        if not has_incident:
            issues.append({
                "severity": "block",
                "rule_id": anti_id,
                "skill": skill_name,
                "message": (
                    f"{anti_id} missing incident reference "
                    f"(commit hash 7+ hex chars OR 'Phase N.M' OR 'Incident: ...')"
                ),
            })

    return issues


# ---------------------------------------------------------------------------
# Per-skill driver
# ---------------------------------------------------------------------------

def _scan_skill(
    skill_name: str,
    cfg: dict[str, Any],
    *,
    check_invariants: bool = True,
    check_schema: bool = True,
    strict: bool = False,
) -> dict[str, Any]:
    """Run all checks for one skill. Return result dict.

    {
      "skill": "vg-build",
      "invariant_violations": [...],
      "schema_violations": [...],
      "verdict": "PASS" | "WARN" | "BLOCK"
    }
    """
    result: dict[str, Any] = {
        "skill": skill_name,
        "invariant_violations": [],
        "schema_violations": [],
        "verdict": "PASS",
    }

    skill_dir = REPO_ROOT / ".codex" / "skills" / skill_name
    skill_md = skill_dir / "SKILL.md"
    manual_md = skill_dir / "RULES-CARDS-MANUAL.md"

    # Severity for invariant violations on REAL skills (R11):
    #   strict=True  → BLOCK (used in test fixtures + dogfood validation)
    #   strict=False → WARN  (initial production rollout — won't break accept)
    invariant_sev = "block" if strict else "warn"

    if not skill_md.exists():
        result["invariant_violations"].append({
            "severity": invariant_sev,
            "skill": skill_name,
            "message": f"SKILL.md missing at {skill_md}",
        })
        # Don't early-return; let verdict logic compute outcome.
        # In strict mode that's BLOCK; in non-strict (R11) it's WARN.
        # Compute verdict and return.
        result["verdict"] = "BLOCK" if strict else "WARN"
        return result

    text = skill_md.read_text(encoding="utf-8", errors="replace")

    if check_invariants:
        # Frontmatter
        fields, fm_err = _parse_frontmatter(text)
        if fm_err:
            result["invariant_violations"].append({
                "severity": invariant_sev,
                "skill": skill_name,
                "message": f"frontmatter parse error: {fm_err}",
            })
        else:
            required = cfg.get("required_frontmatter_fields", [])
            for req in required:
                if not _frontmatter_has_field(fields or {}, req):
                    result["invariant_violations"].append({
                        "severity": "warn",  # R11: WARN initially per task spec
                        "skill": skill_name,
                        "message": (
                            f"frontmatter missing required field '{req}' "
                            f"(per validators_skill_invariants.required_frontmatter_fields)"
                        ),
                    })

        # Steps
        steps = STEP_RE.findall(text)
        if steps:
            for issue in _check_step_numbering(steps):
                result["invariant_violations"].append({
                    "severity": invariant_sev,
                    "skill": skill_name,
                    "message": f"step numbering: {issue}",
                })
            for missing_step in _check_step_markers(text, steps):
                result["invariant_violations"].append({
                    "severity": invariant_sev,
                    "skill": skill_name,
                    "message": (
                        f"step '{missing_step}' has no marker write nor "
                        f"explicit '<!-- no-marker: reason -->' comment"
                    ),
                })
            for diff in _check_command_sync(skill_name, steps):
                result["invariant_violations"].append({
                    "severity": invariant_sev,
                    "skill": skill_name,
                    "message": f"sync drift: {diff}",
                })

    if check_schema and manual_md.exists():
        manual_text = manual_md.read_text(encoding="utf-8", errors="replace")
        schema_issues = _check_manual_schema(skill_name, manual_text, cfg)
        result["schema_violations"].extend(schema_issues)

    # Compute verdict — config-driven severity overrides.
    # In strict mode, ALL severities are honored verbatim (block stays block).
    # In non-strict mode, schema_severity config can downgrade schema BLOCKs
    # to WARN for graceful production rollout.
    enforce_sev = str(cfg.get("enforce_severity", "block")).lower()
    schema_sev = str(cfg.get("schema_severity", "warn")).lower()

    has_block = False
    has_warn = False
    for v in result["invariant_violations"]:
        sev = v.get("severity", "block").lower()
        if sev == "warn":
            has_warn = True
        elif sev == "block":
            # If strict, always BLOCK; if non-strict, honor enforce_sev config
            if strict or enforce_sev == "block":
                has_block = True
            else:
                has_warn = True
    for v in result["schema_violations"]:
        sev = v.get("severity", "warn").lower()
        if sev == "warn":
            has_warn = True
        elif sev == "block":
            if strict or schema_sev == "block":
                has_block = True
            else:
                has_warn = True

    if has_block:
        result["verdict"] = "BLOCK"
    elif has_warn:
        result["verdict"] = "WARN"
    else:
        result["verdict"] = "PASS"

    return result


def _all_skills() -> list[str]:
    """Discover all vg-* skills under .codex/skills/."""
    skills_dir = REPO_ROOT / ".codex" / "skills"
    if not skills_dir.exists():
        return []
    return sorted(
        d.name for d in skills_dir.iterdir()
        if d.is_dir() and d.name.startswith("vg-")
    )


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

def _emit_fired_event(verdict: str, skills_scanned: int, blocks: int, warns: int) -> None:
    """Append telemetry event to .vg/events.jsonl (best-effort, never raises)."""
    try:
        events_dir = REPO_ROOT / ".vg"
        events_dir.mkdir(parents=True, exist_ok=True)
        log_file = events_dir / "events.jsonl"
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "verify-skill-invariants.fired",
            "verdict": verdict,
            "skills_scanned": skills_scanned,
            "block_count": blocks,
            "warn_count": warns,
        }
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skill", help="Scan a single skill (e.g. vg-build)")
    ap.add_argument("--all", action="store_true", help="Scan all vg-* skills")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON (validator-output schema)")
    ap.add_argument("--check-schema-only", action="store_true",
                    help="Skip invariant checks, only manual-card schema")
    ap.add_argument("--check-invariants-only", action="store_true",
                    help="Skip manual-card schema, only structural invariants")
    ap.add_argument("--config", default=None,
                    help="Override config path (default: .claude/vg.config.md)")
    ap.add_argument("--strict", action="store_true",
                    help=("Promote invariant violations to BLOCK severity "
                          "(default: WARN initially per R11). Used by tests + "
                          "post-dogfood promotion."))
    args = ap.parse_args(argv)

    cfg_path = Path(args.config) if args.config else None
    cfg = _load_config(cfg_path)

    if args.skill:
        targets = [args.skill]
    elif args.all:
        targets = _all_skills()
    else:
        # Default: scan all
        targets = _all_skills()

    start = time.time()
    results = []
    for skill in targets:
        results.append(_scan_skill(
            skill, cfg,
            check_invariants=not args.check_schema_only,
            check_schema=not args.check_invariants_only,
            strict=args.strict,
        ))

    # Aggregate verdict — worst across skills
    verdicts = [r["verdict"] for r in results]
    if "BLOCK" in verdicts:
        overall = "BLOCK"
    elif "WARN" in verdicts:
        overall = "WARN"
    else:
        overall = "PASS"

    blocks = sum(1 for v in verdicts if v == "BLOCK")
    warns = sum(1 for v in verdicts if v == "WARN")

    _emit_fired_event(overall, len(targets), blocks, warns)

    duration_ms = int((time.time() - start) * 1000)

    # Build evidence list
    evidence: list[dict[str, Any]] = []
    for r in results:
        for v in r["invariant_violations"]:
            evidence.append({
                "type": "invariant",
                "message": f"[{r['skill']}] {v['message']}",
                "skill": r["skill"],
                "severity": v.get("severity", "block").upper(),
            })
        for v in r["schema_violations"]:
            evidence.append({
                "type": "schema",
                "message": f"[{r['skill']}] {v['message']}",
                "skill": r["skill"],
                "rule_id": v.get("rule_id", ""),
                "severity": v.get("severity", "warn").upper(),
            })

    output = {
        "validator": "verify-skill-invariants",
        "verdict": overall,
        "evidence": evidence,
        "duration_ms": duration_ms,
        "summary": {
            "skills_scanned": len(targets),
            "pass": sum(1 for v in verdicts if v == "PASS"),
            "warn": warns,
            "block": blocks,
        },
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        # Human-readable
        print(f"verify-skill-invariants — verdict: {overall}")
        print(f"  scanned: {len(targets)}  pass: {output['summary']['pass']}  "
              f"warn: {warns}  block: {blocks}")
        if evidence:
            print()
            for e in evidence[:50]:
                sev = e.get("severity", "")
                print(f"  [{sev:5s}] {e['message']}")
            if len(evidence) > 50:
                print(f"  ... ({len(evidence) - 50} more)")

    # Exit code: 0 = PASS/WARN, 1 = BLOCK
    return 1 if overall == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
