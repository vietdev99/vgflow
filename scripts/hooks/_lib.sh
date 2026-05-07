# shellcheck shell=bash
# scripts/hooks/_lib.sh -- shared bash helpers for VG hooks.
#
# Sourced by every hook. Pure functions only -- no side effects on source.
#
# vg_resolve_session_id
#   Resolve a stable session id without ever falling back to the literal
#   string "default". Resolution order:
#     1. CLAUDE_HOOK_SESSION_ID / CLAUDE_SESSION_ID / CLAUDE_CODE_SESSION_ID
#        / CODEX_SESSION_ID env vars
#     2. .vg/.session-context.json `session_id` field
#        - Legacy "default" sentinel auto-migrates to a per-run synthetic id
#          (`session-unknown-<run_id_prefix>`) if `run_id` is present, AND
#          the orphan `.vg/active-runs/default.json` is renamed to match.
#          Cleans up issue #113 poisoning on first read.
#     3. Fallback to "unknown" -- orphan sentinel; downstream Python state
#        treats it as a synthetic session via `_is_unknown_orphan_session`.
#
# vg_session_run_file <session_id>
#   Echo the canonical active-run state file path for a session id.
#
# vg_sweep_orphan_default
#   Best-effort cleanup: if .vg/active-runs/default.json exists AND its
#   embedded session_id points to a real (non-default) sibling state file
#   with the SAME run_id, the default.json copy is provably an orphan
#   left over from the pre-fix bash hooks. Archive it as
#   default.json.orphan-bak-<epoch>. No-op when default.json is absent or
#   when the sibling is missing/divergent (preserve cautious — avoid
#   nuking a real run during a rollback).

vg_resolve_session_id() {
  local sid="${CLAUDE_HOOK_SESSION_ID:-${CLAUDE_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-${CODEX_SESSION_ID:-}}}}"
  if [ -z "$sid" ] && [ -f ".vg/.session-context.json" ]; then
    sid="$(python3 - <<'PY' 2>/dev/null || true
import json, os
from pathlib import Path

ctx_path = Path(".vg/.session-context.json")
try:
    ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)

s = ctx.get("session_id", "") or ""

# Issue #113 migration: the legacy "default" sentinel poisoned cross-session
# routing -- every env-unset hook resolved to .vg/active-runs/default.json and
# clobbered cross-session run state. Auto-rewrite to a per-run synthetic id so
# subsequent reads route to a session-scoped file.
if s == "default":
    rid = ctx.get("run_id", "") or ""
    if rid:
        new_sid = f"session-unknown-{rid[:8]}"
        ctx["session_id"] = new_sid
        tmp = ctx_path.with_suffix(ctx_path.suffix + ".tmp")
        tmp.write_text(json.dumps(ctx, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(ctx_path))

        legacy = Path(".vg/active-runs/default.json")
        if legacy.exists():
            try:
                cur = json.loads(legacy.read_text(encoding="utf-8"))
                if cur.get("run_id") == rid:
                    target = Path(".vg/active-runs") / f"{new_sid}.json"
                    if not target.exists():
                        legacy.replace(target)
                    else:
                        legacy.unlink()
            except Exception:
                pass
        s = new_sid
    else:
        s = ""

if s and s != "unknown":
    print(s)
PY
)"
  fi
  printf '%s\n' "${sid:-unknown}"
}

vg_session_run_file() {
  local sid="${1:-unknown}"
  printf '%s\n' ".vg/active-runs/${sid}.json"
}

vg_sweep_orphan_default() {
  [ -f ".vg/active-runs/default.json" ] || return 0
  python3 - <<'PY' 2>/dev/null || true
import json, time
from pathlib import Path

runs = Path(".vg/active-runs")
default_p = runs / "default.json"
if not default_p.exists():
    raise SystemExit(0)
try:
    d = json.loads(default_p.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)

rid = d.get("run_id") or ""
sid = d.get("session_id") or ""

# Only sweep when default.json names a real sibling that already
# carries the same run_id. Anything else -- divergent run_id, missing
# sibling, default-as-content-sid -- is preserved so a rollback or an
# in-flight write race does not vaporise live state.
if not rid or not sid or sid in ("default", "unknown"):
    raise SystemExit(0)

sibling = runs / f"{sid}.json"
if not sibling.exists():
    raise SystemExit(0)
try:
    s = json.loads(sibling.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
if s.get("run_id") != rid:
    raise SystemExit(0)

bak = runs / f"default.json.orphan-bak-{int(time.time())}"
default_p.replace(bak)
PY
}
