#!/bin/bash
# bootstrap-inject.sh — render <bootstrap_rules> prompt block for agent spawn paths.
#
# PURPOSE (enforces user's hard rule): rules promoted via /vg:learn in any prior
# phase MUST be loaded + injected into the subagent prompts of later phases when
# their scope DSL matches the current step. Without this, `/vg:bootstrap --view`
# reports "7 rules active" but agents never see them — learnings rot in overlay.
#
# USAGE (called from command bash blocks before Agent spawn):
#
#   source "${REPO_ROOT:-.}/.claude/commands/vg/_shared/lib/bootstrap-inject.sh"
#   BOOTSTRAP_RULES_BLOCK=$(vg_bootstrap_render_block "$BOOTSTRAP_PAYLOAD_FILE" "$STEP_NAME")
#
# Then interpolate ${BOOTSTRAP_RULES_BLOCK} into the Agent prompt ~= after the
# static rules block, before task/contract/goals context. On empty → block is
# the string "(no project-specific rules match this step)" so grep gates can
# verify the block always appears (no silent skip).
#
# HARD RULE (enforced by callers, not this helper): every Agent spawn path in
# build/blueprint/review/scope MUST include <bootstrap_rules>${BOOTSTRAP_RULES_BLOCK}
# </bootstrap_rules>. The integrity checker `vg_bootstrap_verify_injection` below
# verifies this statically.

set +e  # never block caller on helper failure — we fail open to empty block

vg_bootstrap_render_block() {
  local payload_file="${1:-}"
  local step_name="${2:-unknown}"

  if [ -z "$payload_file" ] || [ ! -s "$payload_file" ]; then
    echo "(no bootstrap payload — helper not called or loader failed)"
    return 0
  fi

  # Payload shape (from bootstrap-loader.py --emit all):
  #   { "rules": [{"id","title","prose","target_step","scope",...}],
  #     "overlay": {...}, "overlay_rejected": [...] }
  #
  # Rule selection:
  #   - target_step == $step_name OR target_step == 'global' OR absent (matches all)
  #   - loader already pre-filtered by scope DSL against phase metadata

  ${PYTHON_BIN:-python3} - "$payload_file" "$step_name" <<'PY' 2>/dev/null
import json, sys
from pathlib import Path

payload_path = sys.argv[1]
step = sys.argv[2]

try:
    data = json.loads(Path(payload_path).read_text(encoding='utf-8'))
except Exception as e:
    print(f"(bootstrap payload unreadable: {e})")
    sys.exit(0)

rules = data.get('rules') or []
if not rules:
    print("(no project-specific rules match this step — bootstrap empty or scope no-match)")
    sys.exit(0)

matched = []
for r in rules:
    target = (r.get('target_step') or '').strip()
    if target in ('', 'global', step):
        matched.append(r)

if not matched:
    print(f"(no project-specific rules target step='{step}' — skipped {len(rules)} rules with other targets)")
    sys.exit(0)

# Emit one PROJECT RULE block per matched rule. Prose is the executable prompt;
# title is the human-readable label; id is for telemetry correlation.
out = []
for r in matched:
    rid = r.get('id', 'L-???')
    title = (r.get('title') or '(untitled)').strip()
    prose = (r.get('prose') or '').rstrip()
    out.append(f"### PROJECT RULE {rid}: {title}\n{prose}\n")

print('\n'.join(out))
PY
}

# Issue Codex #9 / design Section 13.4: causal attribution helper.
# Computes sha256 of joined sequence cmds for procedural rules. Used by
# Task 3.2 prober to verify the sequence WE BELIEVE ran matches what
# ACTUALLY ran in deploy/test log. Without this, outcome attribution is
# cargo-cult — rule fires + phase passes -> rule logged PASS even when
# executor bypassed sequence entirely.
#
# Args:
#   $1 = rule file path (markdown with YAML frontmatter)
#   $2 = optional --json (print payload to stdout instead of emitting telemetry)
#
# Output (JSON, when --json):
#   { "slug": "...", "id": "...", "rule_type": "...", "target_step": "...",
#     "authority": "...",
#     "sequence_checksum": "<sha256>" }    # only when type=procedural
#
# Errors are returned as JSON {"error": "..."} on stdout with rc=0 so the
# caller (or test harness) gets structured feedback instead of bash trap noise.
vg_bootstrap_compute_sequence_checksum() {
  local rule_path="$1"
  local mode="${2:-emit}"

  local payload
  payload="$(VG_RULE_PATH="$rule_path" ${PYTHON_BIN:-python3} - <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(json.dumps({"error": "yaml module missing"}))
    sys.exit(0)

p = Path(os.environ["VG_RULE_PATH"])
try:
    text = p.read_text(encoding="utf-8")
except OSError as e:
    print(json.dumps({"error": f"read failed: {e}"}))
    sys.exit(0)

if not text.startswith("---\n"):
    print(json.dumps({"error": "missing frontmatter"}))
    sys.exit(0)

end = text.find("\n---\n", 4)
if end < 0:
    print(json.dumps({"error": "frontmatter not closed"}))
    sys.exit(0)

try:
    front = yaml.safe_load(text[4:end]) or {}
except yaml.YAMLError as e:
    print(json.dumps({"error": f"yaml parse: {e}"}))
    sys.exit(0)

if not isinstance(front, dict):
    print(json.dumps({"error": "frontmatter not a mapping"}))
    sys.exit(0)

# Accept both 'slug' (Stage 1 schema docs) and 'id' (loader payload format)
identifier = front.get("slug") or front.get("id") or ""

payload = {
    "slug": identifier,           # canonical key in this output
    "id": identifier,             # mirror for loader-format compat
    "rule_type": front.get("type", "declarative"),
    "target_step": front.get("target_step", ""),
    "authority": front.get("authority", "advisory"),
}

if payload["rule_type"] == "procedural":
    seq = front.get("sequence") or []
    cmds = [str(s.get("cmd", "")) for s in seq if isinstance(s, dict)]
    joined = "\n".join(cmds).encode("utf-8")
    payload["sequence_checksum"] = hashlib.sha256(joined).hexdigest()

print(json.dumps(payload))
PY
)"

  if [ "$mode" = "--json" ]; then
    printf '%s' "$payload"
    return 0
  fi

  # Emit-mode: print payload to stdout for caller-side handling.
  # (Existing vg_bootstrap_emit_fired iterates rules and decides whether
  # to wrap into telemetry; this helper just provides the checksum data.)
  printf '%s' "$payload"
}

# Emit telemetry event for each rule actually rendered into a prompt. Called AFTER
# vg_bootstrap_render_block succeeds and BEFORE Agent spawn, so downstream tools
# (`/vg:bootstrap --trace L-042`, `/vg:telemetry --gate bootstrap.rule_fired`)
# can correlate rule firings with phase outcomes.
vg_bootstrap_emit_fired() {
  local payload_file="${1:-}"
  local step_name="${2:-unknown}"
  local phase="${3:-unknown}"
  local command="${VG_COMMAND:-unknown}"

  [ -z "$payload_file" ] || [ ! -s "$payload_file" ] && return 0

  local telemetry_file="${PLANNING_DIR:-.vg}/telemetry.jsonl"

  ${PYTHON_BIN:-python3} - "$payload_file" "$step_name" "$phase" "$command" "$telemetry_file" <<'PY' 2>/dev/null
import hashlib, json, sys, os, subprocess
from datetime import datetime, timezone
from pathlib import Path

payload, step, phase, command, telemetry = sys.argv[1:6]

try:
    data = json.loads(Path(payload).read_text(encoding='utf-8'))
except Exception:
    sys.exit(0)


def _compute_sequence_checksum(rule_path):
    """Re-parse the rule file and compute sha256(joined sequence cmds).

    Codex #9 / design Section 13.4 — causal attribution for procedural rules.
    Returns hex digest, or None if anything goes wrong (fail-open: emit_fired
    must never block the parent command).
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    try:
        text = Path(rule_path).read_text(encoding='utf-8')
    except OSError:
        return None
    if not text.startswith('---\n'):
        return None
    end = text.find('\n---\n', 4)
    if end < 0:
        return None
    try:
        front = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(front, dict):
        return None
    seq = front.get('sequence') or []
    cmds = [str(s.get('cmd', '')) for s in seq if isinstance(s, dict)]
    return hashlib.sha256('\n'.join(cmds).encode('utf-8')).hexdigest()


rules = data.get('rules') or []
fired = []  # list of (rule_id, extra_metadata_dict)
for r in rules:
    target = (r.get('target_step') or '').strip()
    if target in ('', 'global', step):
        rid = r.get('id') or 'L-unknown'
        extra = {}
        # Augment per-rule metadata for procedural rules with sequence checksum.
        # Loader appends '_path' to every rule (.claude/scripts/bootstrap-loader.py:321).
        if r.get('type') == 'procedural' and r.get('_path'):
            digest = _compute_sequence_checksum(r['_path'])
            if digest is not None:
                extra['sequence_checksum'] = digest
                extra['rule_type'] = 'procedural'
        fired.append((rid, extra))

if not fired:
    sys.exit(0)

ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

# Sink 1 — telemetry.jsonl (legacy, for /vg:bootstrap --trace fallback path)
Path(telemetry).parent.mkdir(parents=True, exist_ok=True)
with open(telemetry, 'a', encoding='utf-8') as f:
    for rid, extra in fired:
        evt = {
            'event_type': 'bootstrap.rule_fired',
            'timestamp': ts,
            'rule_id': rid,
            'command': command,
            'phase': phase,
            'step': step,
        }
        evt.update(extra)
        f.write(json.dumps(evt) + '\n')

# Sink 2 — events.db (v2.2 canonical — used by /vg:bootstrap --trace primary path,
# bootstrap-hygiene efficacy, and events-chain integrity). Only works if an active
# run exists (orchestrator-managed lifecycle). Silent skip on any error — the
# telemetry.jsonl sink above keeps the signal even when orchestrator run is absent.
orch = Path(__file__).resolve().parent if False else None  # keep import parity
for rid, extra in fired:
    evt_payload = {
        "rule_id": rid,
        "command": command,
        "phase": phase,
        "step": step,
    }
    evt_payload.update(extra)
    subprocess.run(
        ["python3", ".claude/scripts/vg-orchestrator", "emit-event",
         "bootstrap.rule_fired",
         "--step", step,
         "--actor", "orchestrator",
         "--outcome", "INFO",
         "--payload", json.dumps(evt_payload)],
        capture_output=True, text=True, timeout=10,
    )
PY
}

# Static self-check: scan every vg/*.md command file and verify that every
# Agent(subagent_type=...) spawn block contains a <bootstrap_rules> tag. Used
# by CI and by /vg:doctor to enforce the hard injection rule. Missing injection
# in any spawn path is a workflow bug — fix the source file.
#
# Returns 0 if all spawn paths inject; non-zero with per-file violation list
# otherwise. Safe to run on a clean repo — read-only.
vg_bootstrap_verify_injection() {
  local commands_dir="${1:-.claude/commands/vg}"

  ${PYTHON_BIN:-python3} - "$commands_dir" <<'PY'
import re, sys
from pathlib import Path

root = Path(sys.argv[1])

# VG commands mix literal `Agent(...)` calls (blueprint/build) with prose
# descriptions like "Dispatch Task tool (subagent_type=general-purpose, ...)".
# Both patterns count as spawn sites. Check 300 lines following each match
# for <bootstrap_rules> tag — if missing, the spawn is uninjected.
SPAWN_RES = [
    re.compile(r'Agent\(\s*subagent_type=["\']general-purpose["\']', re.MULTILINE),
    re.compile(r'subagent_type=general-purpose', re.MULTILINE),
]
BOOTSTRAP_RE = re.compile(r'<bootstrap_rules>|BOOTSTRAP_RULES_BLOCK', re.MULTILINE)

violations = []
checked = 0

for md in sorted(root.glob('*.md')):
    text = md.read_text(encoding='utf-8', errors='replace')
    lines = text.split('\n')
    seen_starts: set[int] = set()

    for rx in SPAWN_RES:
        for m in rx.finditer(text):
            start_line = text[:m.start()].count('\n') + 1
            if start_line in seen_starts:
                continue
            seen_starts.add(start_line)
            checked += 1
            # Look backwards ~30 lines AND forwards ~300 lines for bootstrap_rules
            window_start = max(0, start_line - 30)
            window_end = min(len(lines), start_line + 300)
            window = '\n'.join(lines[window_start:window_end])
            if not BOOTSTRAP_RE.search(window):
                violations.append(f"{md.name}:{start_line} — spawn site missing <bootstrap_rules> / BOOTSTRAP_RULES_BLOCK in ±window")

if violations:
    print(f"⛔ Bootstrap injection violations ({len(violations)} of {checked} spawn sites):")
    for v in violations:
        print(f"   - {v}")
    sys.exit(1)

print(f"✓ All {checked} spawn sites have bootstrap injection nearby")
sys.exit(0)
PY
}

# If sourced with argument `--verify`, run the static check and exit.
if [ "${1:-}" = "--verify" ]; then
  vg_bootstrap_verify_injection "${2:-.claude/commands/vg}"
  exit $?
fi
