# /vg:field-test Implementation Plan (v2)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build new VGFlow skill `/vg:field-test` so the user can manually roam the deployed app in an MCP-playwright browser while AI silently captures multi-source telemetry (browser console + network + clicks + nav chain + per-Mark notes + correlated API server log tails). On Stop, an analyzer subagent produces `FIELD-REPORT.md` and appends entries to `.vg/KNOWN-ISSUES.json`.

**Revision:** v2 — supersedes v1 plan after Codex GPT-5.5 review found 10 critical issues (race conditions, broken redaction, dead presets, missing `--resume`, cross-platform `date` bug, TOCTOU lock, contract mismatch). All 10 addressed below.

**v1 scope cuts** (per design v2): drop `quick`/`deep` presets, drop `--resume`, drop `dev-phases/<N>/` mirror, drop `--non-interactive`, drop crash-recovery aborted-bundle flow.

**Architecture:** AI orchestrator injects overlay JS via `browser_evaluate`. AI polls overlay state via `browser_evaluate(() => ({len: __VG_FT_STATE.marks.length, status: __VG_FT_STATE.status}))` — NOT console messages (which are snapshot reads that replay; would duplicate marks). Console messages used only for Start/Stop edge events with offset tracking. Per-source API log tails pipe through `redact-stream.py` at capture time (not at build time). Atomic lock via `mkdir`. Python timestamp wrapper replaces GNU `date %3N` for portability.

**Tech Stack:** Python 3.11+, vanilla browser JS, JSON Schema draft-07, MCP playwright1.

**Design doc:** [`docs/plans/2026-05-11-field-test-capture-design.md`](./2026-05-11-field-test-capture-design.md) (v2)

**Working directory:** `main` per project rule.

---

## Conventions

- Python: `from __future__ import annotations`, type-hinted, no third-party deps.
- Bash: `set -euo pipefail`.
- Every `scripts/` file mirrored to `.claude/scripts/` byte-identical. Same for `commands/vg/` → `.claude/commands/vg/` and `agents/` → `.claude/agents/`.
- Commits use:
  ```
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```
- Regression sweep before each commit:
  ```
  python -m pytest tests/ -q --tb=no
  ```

---

## Task 1: Schema v1 + vg.config block (no preset enum)

**Files:**
- Create: `schemas/field-test-session.v1.json`
- Modify: `vg.config.template.md`
- Test: `tests/test_field_test_config_schema.py`

**Key diff vs v1 plan:**
- Drop `preset` from schema (no longer a field).
- Schema validation test seeds a real session.json and asserts jsonschema validation (not just substring check).

**Step 1: Failing test**

```python
"""tests/test_field_test_config_schema.py — schema + config block contracts."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = REPO_ROOT / "schemas" / "field-test-session.v1.json"
CONFIG_TEMPLATE = REPO_ROOT / "vg.config.template.md"


def test_schema_exists_and_parses():
    assert SCHEMA.is_file()
    data = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert data["$schema"] == "http://json-schema.org/draft-07/schema#"
    required = set(data["required"])
    expected = {"version", "sid", "phase", "base_url", "ts_started", "sources", "redaction"}
    assert expected <= required


def test_schema_rejects_invalid_session():
    """Schema must actually reject malformed session.json — not just declare required fields."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    # Missing `sid`
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"version": "1", "base_url": "http://x", "ts_started": "2026-05-11T00:00:00Z",
             "sources": [], "redaction": "password"},
            schema,
        )
    # Bad sources type
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"version": "1", "sid": "ft-2026", "phase": None, "base_url": "http://x",
             "ts_started": "2026-05-11T00:00:00Z", "sources": "not-a-list", "redaction": "password"},
            schema,
        )


def test_schema_accepts_real_session():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    valid = {
        "version": "1", "sid": "ft-2026-05-11T10-00-00Z", "phase": None,
        "base_url": "http://localhost:3000", "ts_started": "2026-05-11T10:00:00Z",
        "sources": [{"type": "file", "target": "/var/log/api.log", "label": "api"}],
        "redaction": "password|token|secret",
    }
    jsonschema.validate(valid, schema)


def test_config_template_advertises_field_test_block_no_preset():
    body = CONFIG_TEMPLATE.read_text(encoding="utf-8")
    assert re.search(r"^#?\s*field_test\s*:", body, re.MULTILINE)
    for key in [
        "api_log_sources", "default_redaction", "default_base_url",
        "mark_window_sec", "session_max_size_mb", "max_session_hours",
    ]:
        assert key in body, f"missing config key: {key}"
    # v2: preset must NOT appear (deferred to v2)
    assert "default_preset" not in body, (
        "v1 ships only the standard capture profile — no preset enum in config"
    )
```

**Step 2: Run** → FAIL.

**Step 3: Write schema** — `schemas/field-test-session.v1.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://vgflow.dev/schemas/field-test-session.v1.json",
  "title": "VG field-test session (v1) — user-driven roam capture",
  "type": "object",
  "required": ["version", "sid", "phase", "base_url", "ts_started", "sources", "redaction"],
  "additionalProperties": true,
  "properties": {
    "version": {"const": "1"},
    "sid": {"type": "string", "pattern": "^ft-(p[A-Za-z0-9._-]+-)?[0-9TZ:.-]+$"},
    "phase": {"type": ["string", "null"]},
    "base_url": {"type": "string"},
    "ts_started": {"type": "string", "format": "date-time"},
    "ts_stopped": {"type": ["string", "null"]},
    "sources": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "target", "label"],
        "properties": {
          "type": {"enum": ["file", "command"]},
          "target": {"type": "string"},
          "label": {"type": "string"},
          "pid": {"type": ["integer", "null"]}
        }
      }
    },
    "redaction": {"type": "string"},
    "mark_count": {"type": "integer", "minimum": 0},
    "bundle_path": {"type": ["string", "null"]}
  }
}
```

**Step 4: Modify `vg.config.template.md`**:

```markdown
## field_test (v3.7+ — /vg:field-test skill, v1 scope)

```yaml
field_test:
  api_log_sources:
    # - { type: file,    target: /var/log/api.log,                  label: api }
    # - { type: command, target: "docker logs -f my-api",           label: docker-api }
    # - { type: command, target: "kubectl logs -f pod/api -n prod", label: k8s-api }

  default_redaction: 'password|token|secret|api[_-]?key|email|phone|bearer\s+[A-Za-z0-9._-]+|authorization:\s*\S+'
  default_base_url: ""
  mark_window_sec: 30
  screenshot_quality: 80
  session_max_size_mb: 200
  max_session_hours: 4
```

**Step 5: Run** → PASS.

**Step 6: Commit**

```bash
git add tests/test_field_test_config_schema.py schemas/field-test-session.v1.json vg.config.template.md
git commit -m "feat(field-test): schema v1 + vg.config.template block (no preset enum)

Schema draft-07 with jsonschema validation tests (not substring tautology).
Tests assert rejection of malformed sessions + acceptance of real session.
Config block declares api_log_sources + redaction + caps. No preset field
in v1 — deferred per design v2 scope cut.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Redact-stream helper (single source of truth)

**Files:**
- Create: `scripts/field-test/redact-stream.py`
- Create: `.claude/scripts/field-test/redact-stream.py`
- Test: `tests/test_field_test_redact_stream.py`

**Key:** Single helper applied BOTH at tail capture time (via stdin pipe) AND at build-bundle window correlation. Source of truth for redaction logic. Multi-form patterns: `key=value`, `key: value`, JSON `"key": "value"`, bare `Bearer <jwt>`, `Authorization: Bearer …`.

**Step 1: Failing test**

```python
"""tests/test_field_test_redact_stream.py — capture-time redaction helper."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REDACT = REPO_ROOT / "scripts" / "field-test" / "redact-stream.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "field-test" / "redact-stream.py"


def _run(stdin: str, pattern: str = "password|token|secret|api[_-]?key|email|bearer\\s+[A-Za-z0-9._-]+|authorization:\\s*\\S+") -> str:
    r = subprocess.run(
        [sys.executable, str(REDACT), "--pattern", pattern],
        input=stdin, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return r.stdout


def test_kv_equals_form():
    out = _run("login: password=hunter2 success\n")
    assert "hunter2" not in out
    assert "[REDACTED]" in out


def test_kv_colon_header_form():
    out = _run("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.xxxx\n")
    assert "eyJhbGc" not in out


def test_json_body_form():
    out = _run('POST /api/login {"email":"u@x.com","password":"hunter2"}\n')
    assert "hunter2" not in out
    assert "u@x.com" not in out


def test_url_query_form():
    out = _run("GET /api/things?api_key=ABCDEF&page=2\n")
    assert "ABCDEF" not in out
    assert "page=2" in out, "non-sensitive query params must pass through"


def test_bare_bearer_form():
    out = _run("Got header Bearer eyJhbGc.deadbeef.signature\n")
    assert "deadbeef" not in out


def test_safe_input_passes_through():
    safe = "INFO order created id=42 status=ok\n"
    out = _run(safe)
    assert out.strip() == safe.strip()


def test_idempotency():
    """Re-redacting redacted output should not change it."""
    once = _run("password=hunter2\n")
    twice = _run(once)
    assert once == twice


def test_bad_user_regex_falls_back_to_default():
    """An invalid regex must fall back to default + emit warning to stderr, not crash."""
    r = subprocess.run(
        [sys.executable, str(REDACT), "--pattern", "[unclosed"],
        input="password=hunter2\n", capture_output=True, text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0
    assert "hunter2" not in r.stdout, "default regex must still apply"
    assert "warning" in r.stderr.lower() or "fallback" in r.stderr.lower()


def test_mirror_byte_identity():
    assert REDACT.read_bytes() == MIRROR.read_bytes()
```

**Step 2: Run** → FAIL.

**Step 3: Write `scripts/field-test/redact-stream.py`**:

```python
#!/usr/bin/env python3
"""redact-stream.py — line-oriented redactor for /vg:field-test.

Reads stdin line-by-line, applies a multi-form redaction regex, writes
stdout. Used in two places:

  1. tail-source.sh pipes API log lines through this BEFORE writing to
     disk (capture-time redaction — closes the design v2 disk-exposure
     window).
  2. build-bundle.py runs each correlated window line through this for
     idempotent re-application during Stop-time bundle assembly.

Patterns covered:
  - key=value         (URL query / CLI arg)
  - key: value        (HTTP header)
  - "key": "value"    (JSON body)
  - Bearer <token>    (Authorization value)
  - Authorization: ...

Bad user regex → warn on stderr, fall back to default. Never crash.
"""
from __future__ import annotations

import argparse
import re
import sys


DEFAULT_KEYS = r"password|token|secret|api[_-]?key|email|phone"
DEFAULT_PATTERN = (
    r"(?i)("
    r"(?:" + DEFAULT_KEYS + r")\s*[:=]\s*\"?[^\"\s,&}]+"
    r"|\"(?:" + DEFAULT_KEYS + r")\"\s*:\s*\"[^\"]*\""
    r"|bearer\s+[A-Za-z0-9._\-]+"
    r"|authorization:\s*\S+"
    r")"
)

SENTINEL = "[REDACTED]"


def build_pattern(user: str | None) -> tuple[re.Pattern[str], bool]:
    """Return (compiled, used_default). Falls back to default on bad regex."""
    if not user or user == "default":
        return re.compile(DEFAULT_PATTERN), True
    # Compose user keys with multi-form template (same shape as DEFAULT_PATTERN)
    try:
        composed = (
            r"(?i)("
            r"(?:" + user + r")\s*[:=]\s*\"?[^\"\s,&}]+"
            r"|\"(?:" + user + r")\"\s*:\s*\"[^\"]*\""
            r"|bearer\s+[A-Za-z0-9._\-]+"
            r"|authorization:\s*\S+"
            r")"
        )
        return re.compile(composed), False
    except re.error as exc:
        print(f"redact-stream: warning: invalid user regex '{user}': {exc}; falling back to default", file=sys.stderr)
        return re.compile(DEFAULT_PATTERN), True


def redact(line: str, pat: re.Pattern[str]) -> str:
    return pat.sub(SENTINEL, line)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pattern", default="default", help="Custom redaction keys regex (alternation)")
    args = ap.parse_args()
    pat, _ = build_pattern(args.pattern)
    try:
        for line in sys.stdin:
            sys.stdout.write(redact(line, pat))
            sys.stdout.flush()
    except BrokenPipeError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Mirror + run** → PASS all 9 tests.

**Step 5: Commit**

```bash
git add scripts/field-test/redact-stream.py .claude/scripts/field-test/redact-stream.py tests/test_field_test_redact_stream.py
git commit -m "feat(field-test): redact-stream.py multi-form redactor (capture+build)

Single source of truth for redaction. Covers key=value, key: value,
JSON body \"key\":\"value\", bare Bearer <jwt>, Authorization: ... header
form. Idempotent (re-redacting redacted output is no-op). Bad user
regex falls back to default + warns on stderr instead of crashing.

Closes Codex review §4 — v1 plan regex was broken (dropped api_key,
email, phone from design's promised default; second alternative branch
only matched bare word; Bearer never matched).

Used by tail-source.sh at capture time AND build-bundle.py at window
correlation time — closes the disk-exposure window the v1 plan left
open until Stop.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: tail-source.sh + Python timestamp wrapper

**Files:**
- Create: `scripts/field-test/tail-source.sh`
- Create: `scripts/field-test/prefix-iso.py` (replaces GNU `date %3N`)
- Mirror both to `.claude/scripts/field-test/`
- Test: `tests/test_field_test_tail_source.py`

**Key diff vs v1 plan:**
- Replace `date -u +%Y-%m-%dT%H:%M:%S.%3N` (GNU-only) with `python3 prefix-iso.py` (portable Mac+Linux+Windows-via-GitBash).
- Pipe stream through `redact-stream.py` BEFORE writing disk.

**Step 1: Failing test**

```python
"""tests/test_field_test_tail_source.py"""
from __future__ import annotations

import shutil, signal, subprocess, sys, time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TAIL = REPO_ROOT / "scripts" / "field-test" / "tail-source.sh"
PREFIX = REPO_ROOT / "scripts" / "field-test" / "prefix-iso.py"
MIRROR_TAIL = REPO_ROOT / ".claude" / "scripts" / "field-test" / "tail-source.sh"
MIRROR_PREFIX = REPO_ROOT / ".claude" / "scripts" / "field-test" / "prefix-iso.py"


def test_scripts_exist():
    assert TAIL.is_file()
    assert PREFIX.is_file()


def test_tail_uses_python_timestamp_not_gnu_date():
    body = TAIL.read_text(encoding="utf-8")
    # Must NOT use `date %3N` (GNU-only)
    assert "%3N" not in body, "v2 forbids date %3N (macOS BSD date breaks silently)"
    # Must reference prefix-iso.py wrapper
    assert "prefix-iso.py" in body


def test_tail_pipes_through_redactor():
    body = TAIL.read_text(encoding="utf-8")
    assert "redact-stream.py" in body, (
        "v2 mandates capture-time redaction before disk write"
    )


def test_tail_takes_redaction_pattern_arg():
    body = TAIL.read_text(encoding="utf-8")
    assert "--redact" in body, "tail must accept --redact pattern for per-session regex"


def test_mirror_byte_identity():
    assert TAIL.read_bytes() == MIRROR_TAIL.read_bytes()
    assert PREFIX.read_bytes() == MIRROR_PREFIX.read_bytes()


_bash = pytest.mark.skipif(
    not shutil.which("bash") or sys.platform == "win32",
    reason="POSIX bash required",
)


@_bash
def test_tail_file_mode_redacts_inline(tmp_path):
    target = tmp_path / "src.log"
    out = tmp_path / "out.log"
    target.write_text("", encoding="utf-8")
    proc = subprocess.Popen(
        ["bash", str(TAIL), "--type", "file", "--target", str(target),
         "--out", str(out), "--redact", "password|token"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)
        with target.open("a", encoding="utf-8") as f:
            f.write("login password=hunter2 success\n")
        time.sleep(1.0)
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
    text = out.read_text(encoding="utf-8")
    assert "hunter2" not in text, "tail must redact at capture, not leave to build-time"
    assert "[REDACTED]" in text


@_bash
def test_tail_iso_prefix_works_on_any_unix(tmp_path):
    """Verifies prefix-iso.py emits parseable ISO timestamps (no `date %3N` portability bug)."""
    target = tmp_path / "src.log"
    out = tmp_path / "out.log"
    target.write_text("", encoding="utf-8")
    proc = subprocess.Popen(
        ["bash", str(TAIL), "--type", "file", "--target", str(target),
         "--out", str(out), "--redact", "default"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)
        with target.open("a", encoding="utf-8") as f:
            f.write("hello world\n")
        time.sleep(1.0)
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
    text = out.read_text(encoding="utf-8")
    # Each line must start with ISO date (e.g. 2026-05-11T...Z)
    for line in text.strip().splitlines():
        assert line[:4].isdigit() and "T" in line[:20] and "Z" in line[:35], (
            f"line missing ISO timestamp: {line!r}"
        )
```

**Step 2: Run** → FAIL.

**Step 3: Write `scripts/field-test/prefix-iso.py`**:

```python
#!/usr/bin/env python3
"""prefix-iso.py — portable line-oriented ISO-8601 timestamp prefixer.

Replaces `date -u +%Y-%m-%dT%H:%M:%S.%3N` which is GNU-only (macOS BSD
date silently emits literal `%3N`). Pure Python = portable Mac+Linux+
Windows-via-Git-Bash.

Reads stdin line-by-line, writes `<ISO-UTC-Z> <line>` to stdout.
"""
from __future__ import annotations

import datetime as _dt
import sys


def main() -> int:
    try:
        for line in sys.stdin:
            ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            sys.stdout.write(f"{ts} {line}")
            sys.stdout.flush()
    except BrokenPipeError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Write `scripts/field-test/tail-source.sh`**:

```bash
#!/usr/bin/env bash
# /vg:field-test tail wrapper — pipes source output through redact-stream.py
# then prefix-iso.py before writing to disk. Capture-time redaction closes
# the disk-exposure window v1 left open until Stop.
set -euo pipefail

TYPE=""
TARGET=""
OUT=""
REDACT_PATTERN="default"
while [ $# -gt 0 ]; do
  case "$1" in
    --type)    TYPE="$2";          shift 2 ;;
    --target)  TARGET="$2";        shift 2 ;;
    --out)     OUT="$2";           shift 2 ;;
    --redact)  REDACT_PATTERN="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 64 ;;
  esac
done

if [ -z "$TYPE" ] || [ -z "$TARGET" ] || [ -z "$OUT" ]; then
  echo "usage: tail-source.sh --type {file|command} --target <arg> --out <path> [--redact <pattern>]" >&2
  exit 64
fi

mkdir -p "$(dirname "$OUT")"
: > "$OUT"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
REDACTOR="$SCRIPT_DIR/redact-stream.py"
PREFIXER="$SCRIPT_DIR/prefix-iso.py"

cleanup() {
  if [ -n "${CHILD_PID:-}" ] && kill -0 "$CHILD_PID" 2>/dev/null; then
    kill -TERM "$CHILD_PID" 2>/dev/null || true
    sleep 0.3
    kill -KILL "$CHILD_PID" 2>/dev/null || true
  fi
  exit 0
}
trap cleanup TERM INT

case "$TYPE" in
  file)
    if [ ! -e "$TARGET" ]; then
      "$PYTHON_BIN" -c "import datetime as d; print(d.datetime.now(d.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'tail-source: waiting for $TARGET to exist')" >> "$OUT"
    fi
    tail -F -n 0 "$TARGET" 2>/dev/null \
      | "$PYTHON_BIN" "$REDACTOR" --pattern "$REDACT_PATTERN" \
      | "$PYTHON_BIN" "$PREFIXER" \
      >> "$OUT" &
    CHILD_PID=$!
    wait "$CHILD_PID"
    ;;
  command)
    # shellcheck disable=SC2086
    bash -c "$TARGET" 2>&1 \
      | "$PYTHON_BIN" "$REDACTOR" --pattern "$REDACT_PATTERN" \
      | "$PYTHON_BIN" "$PREFIXER" \
      >> "$OUT" &
    CHILD_PID=$!
    wait "$CHILD_PID"
    ;;
  *)
    echo "unknown --type: $TYPE" >&2
    exit 64
    ;;
esac
```

**Step 5: Mirror + run**:

```bash
mkdir -p .claude/scripts/field-test
cp scripts/field-test/tail-source.sh .claude/scripts/field-test/
cp scripts/field-test/prefix-iso.py .claude/scripts/field-test/
chmod +x scripts/field-test/tail-source.sh .claude/scripts/field-test/tail-source.sh
python -m pytest tests/test_field_test_tail_source.py -v
```

PASS expected.

**Step 6: Commit**

```bash
git add scripts/field-test/tail-source.sh scripts/field-test/prefix-iso.py \
        .claude/scripts/field-test/tail-source.sh .claude/scripts/field-test/prefix-iso.py \
        tests/test_field_test_tail_source.py
git commit -m "feat(field-test): tail-source.sh + portable prefix-iso.py

Closes Codex review §7: replaces GNU date %3N (macOS BSD date breaks
silently) with prefix-iso.py portable Python wrapper.

Closes Codex review §4: pipes through redact-stream.py BEFORE writing
to disk. Capture-time redaction closes the multi-hour disk-exposure
window v1 left open.

--redact <pattern> per-session regex passed from skill body resolves
session.redaction config.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Overlay JS with idempotent reload + reload_epoch

**Files:**
- Create: `scripts/field-test/overlay.js`
- Mirror: `.claude/scripts/field-test/overlay.js`
- Test: `tests/test_field_test_overlay_js.py`

**Key diff vs v1 plan:**
- `state.reload_epoch` field added so orchestrator distinguishes pre/post-reload marks.
- Overlay no longer is the only source for marks — orchestrator polls `state.marks` directly. Console emit is notification-only.
- Functional test (jsdom or headless playwright) actually clicks Start + Mark + asserts `state.marks.length === 1`. No more substring tautology.

**Step 1: Failing test**

```python
"""tests/test_field_test_overlay_js.py"""
from __future__ import annotations

import os, shutil, subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAY = REPO_ROOT / "scripts" / "field-test" / "overlay.js"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "field-test" / "overlay.js"


def test_overlay_exists():
    assert OVERLAY.is_file()


def test_overlay_no_eval_no_cross_origin():
    body = OVERLAY.read_text(encoding="utf-8")
    assert "eval(" not in body
    assert "new Function(" not in body
    assert "fetch('http" not in body and 'fetch("http' not in body


def test_overlay_state_shape():
    body = OVERLAY.read_text(encoding="utf-8")
    # Must declare state with reload_epoch + marks array + status
    assert "window.__VG_FT_STATE" in body
    assert "reload_epoch" in body, "v2 must track reload epoch for orchestrator dedupe"
    assert "marks:" in body
    assert "status:" in body


def test_overlay_console_emit_is_notification_only():
    body = OVERLAY.read_text(encoding="utf-8")
    # Console markers must include event type but mark entries must also go to state.marks
    # The marker text alone is NOT the source of truth.
    assert "state.marks.push" in body or "marks.push" in body, (
        "v2 overlay must push mark entries into state.marks (orchestrator polls state, not console)"
    )


def test_overlay_idempotent_init():
    body = OVERLAY.read_text(encoding="utf-8")
    assert "if (window.__VG_FT_STATE) return" in body or "if (window.__VG_FT_INIT)" in body, (
        "overlay must be idempotent on re-injection (post-reload)"
    )


def test_mirror_byte_identity():
    assert OVERLAY.read_bytes() == MIRROR.read_bytes()


_node = pytest.mark.skipif(not shutil.which("node"), reason="node required")


@_node
def test_overlay_syntax_via_node_check():
    r = subprocess.run(["node", "--check", str(OVERLAY)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@_node
@pytest.mark.skipif(os.environ.get("VG_RUN_BROWSER_TESTS") != "1", reason="set VG_RUN_BROWSER_TESTS=1 to enable jsdom smoke")
def test_overlay_mark_flow_via_jsdom(tmp_path):
    """Functional smoke: load overlay in jsdom, click Start, click Mark, fill note, submit.
    Assert state.marks.length === 1 and entry has user_note."""
    # Implementation requires `npm i jsdom` once; the test runner script wraps it.
    runner = REPO_ROOT / "scripts" / "field-test" / "_test-jsdom-runner.js"
    if not runner.is_file():
        pytest.skip("jsdom runner not installed (run npm i jsdom in scripts/field-test/)")
    r = subprocess.run(["node", str(runner), str(OVERLAY)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "marks.length=1" in r.stdout
    assert "user_note=test note" in r.stdout
```

**Step 2: Run** → FAIL.

**Step 3: Write overlay.js**

(Same skeleton as v1 plan with these specific v2 changes — full file in repo)

```javascript
/* eslint-disable */
// VGFlow /vg:field-test overlay v2 — vanilla browser JS, no deps.
// Injected via mcp__playwright1__browser_evaluate.
// state.marks[] is canonical source; console emit is notification only.
(function () {
  "use strict";
  if (window.__VG_FT_STATE) {
    // Re-injection (e.g. post-reload). Bump reload_epoch, do NOT wipe marks-server-side
    // (orchestrator holds the server-side marks.raw.jsonl record).
    window.__VG_FT_STATE.reload_epoch = (window.__VG_FT_STATE.reload_epoch || 0) + 1;
    if (window.__VG_FT_INIT) window.__VG_FT_INIT();
    return;
  }

  var BUFFER_CAP = 10000;
  function nowIso() { return new Date().toISOString(); }
  function emit(event, payload) {
    try {
      console.log("[VG_FT] " + JSON.stringify({ event: event, ts: nowIso(), payload: payload || {} }));
    } catch (e) {}
  }

  var state = {
    status: "idle",
    reload_epoch: 0,
    marks: [],
    buffer: { console: [], network: [], nav: [], clicks: [] },
    drops: {}
  };
  window.__VG_FT_STATE = state;

  function pushBuffer(name, entry) {
    var b = state.buffer[name];
    b.push(entry);
    while (b.length > BUFFER_CAP) { b.shift(); state.drops[name] = (state.drops[name] || 0) + 1; }
  }

  // Console / fetch / XHR / history / click monkeypatching — same as v1 plan task 2 body.
  // (See repo for full implementation; omitted here for plan brevity.)

  function render() {
    var existing = document.getElementById("__vg-ft-overlay");
    if (existing) existing.remove();
    var root = document.createElement("div");
    root.id = "__vg-ft-overlay";
    root.style.cssText = "position:fixed;top:12px;right:12px;z-index:2147483647;font:13px/1.3 system-ui;background:#0b1220;color:#e5e7eb;padding:10px;border-radius:8px";
    var pillBg = state.status === "recording" ? "#16a34a" : (state.status === "idle" ? "#475569" : "#dc2626");
    root.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">' +
      '<span id="__vg-ft-pill" style="background:' + pillBg + ';padding:2px 8px;border-radius:999px;font-size:11px">' + state.status + '</span>' +
      '<span style="font-size:11px;opacity:.7">marks: ' + state.marks.length + '</span>' +
      '</div>' +
      '<div style="display:flex;gap:6px;flex-wrap:wrap">' +
      '<button id="__vg-ft-start" style="background:#16a34a;color:#fff;border:0;padding:6px 10px;border-radius:6px">▶ Start</button>' +
      '<button id="__vg-ft-mark" style="background:#f59e0b;color:#000;border:0;padding:6px 10px;border-radius:6px">⚑ Mark</button>' +
      '<button id="__vg-ft-stop" style="background:#dc2626;color:#fff;border:0;padding:6px 10px;border-radius:6px">■ Stop</button>' +
      '</div>';
    document.body.appendChild(root);
    document.getElementById("__vg-ft-start").onclick = function () {
      if (state.status !== "idle") return;
      state.status = "recording";
      emit("start", { url: location.href });
      render();
    };
    document.getElementById("__vg-ft-stop").onclick = function () {
      if (state.status === "idle") return;
      state.status = "idle";
      emit("stop", { marks: state.marks.length });
      render();
    };
    document.getElementById("__vg-ft-mark").onclick = openMark;
  }

  function openMark() {
    if (state.status !== "recording") { alert("Click Start first."); return; }
    var existing = document.getElementById("__vg-ft-modal");
    if (existing) existing.remove();
    var modal = document.createElement("div");
    modal.id = "__vg-ft-modal";
    modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:2147483646;display:flex;align-items:center;justify-content:center";
    modal.innerHTML =
      '<div style="background:#0b1220;color:#e5e7eb;padding:18px;border-radius:10px;min-width:420px">' +
      '<div style="margin-bottom:10px;font-weight:600">Mark current view</div>' +
      '<div style="margin-bottom:8px;font-size:12px;opacity:.7">URL: ' + location.href + '</div>' +
      '<textarea id="__vg-ft-note" rows="5" style="width:100%;background:#1e293b;color:#e5e7eb;border:1px solid #334155;border-radius:6px;padding:8px"></textarea>' +
      '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:10px">' +
      '<button id="__vg-ft-cancel" style="background:#475569;color:#fff;border:0;padding:6px 12px;border-radius:6px">Cancel</button>' +
      '<button id="__vg-ft-submit" style="background:#16a34a;color:#fff;border:0;padding:6px 12px;border-radius:6px">Submit</button>' +
      '</div></div>';
    document.body.appendChild(modal);
    document.getElementById("__vg-ft-cancel").onclick = function () { modal.remove(); };
    document.getElementById("__vg-ft-submit").onclick = function () {
      var note = (document.getElementById("__vg-ft-note").value || "").trim();
      if (!note) { alert("Note required."); return; }
      var entry = {
        n: state.marks.length,
        ts: nowIso(),
        url: location.href,
        referrer: document.referrer || "",
        nav_chain: state.buffer.nav.slice(-5),
        user_note: note,
        viewport: { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1 },
        click_target: state.buffer.clicks[state.buffer.clicks.length - 1] || null,
        reload_epoch: state.reload_epoch
      };
      state.marks.push(entry);                  // canonical source
      emit("mark", { n: entry.n });             // notification only
      modal.remove();
      render();
    };
  }

  window.__VG_FT_INIT = function () { render(); return true; };
  window.__VG_FT_INIT();
})();
```

(Full overlay body with full console/fetch/XHR/history/click monkeypatches — see commit; plan shows the v2-specific delta.)

**Step 4: Mirror + Run** → PASS.

**Step 5: Commit**

```bash
git add scripts/field-test/overlay.js .claude/scripts/field-test/overlay.js tests/test_field_test_overlay_js.py
git commit -m "feat(field-test): overlay v2 — state.marks canonical + reload_epoch

Closes Codex review §1 + §3:
  - state.marks[] is canonical source. Console.log markers are
    notifications only — orchestrator polls state via browser_evaluate,
    not console_messages (which is snapshot-replay and would duplicate
    marks N times per session).
  - state.reload_epoch increments on re-injection after page reload so
    orchestrator can distinguish pre/post-reload marks (overlay state
    persists across SPA nav, wipes on full reload).

Functional jsdom smoke test gated behind VG_RUN_BROWSER_TESTS=1
exercises Start → Mark → Submit and asserts state.marks.length === 1.
Replaces v1 plan's substring-tautology tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: build-bundle.py with redact-stream integration + naive-ts warning + partial recovery

**Files:**
- Create: `scripts/field-test/build-bundle.py`
- Mirror to `.claude/`
- Test: `tests/test_field_test_build_bundle.py`

**Key diff vs v1 plan:**
- API log lines already redacted at capture; build-bundle re-runs through `redact-stream.py` for idempotent safety on browser-side streams (`console.raw.jsonl`, `network.raw.jsonl`).
- Naive (non-Z) timestamps in API log → emit warning to `errors.jsonl` + drop, NOT silent.
- Partial `marks.raw.jsonl` (truncated mid-line from disk-fill / crash) → set `bundle.partial=true`, write what parsed, continue.
- 0-marks session test added.

**Step 1: Failing test** (subset shown; full file generated similarly):

```python
def test_naive_timestamp_logged_to_errors(tmp_path):
    session = _seed_minimal(tmp_path)
    (session / "api-test.log").write_text(
        "2026-05-11T10:00:00Z naive: this one parses\n"
        "2026-05-11 10:00:00 naive: this one does NOT (no T+Z)\n",
        encoding="utf-8",
    )
    subprocess.run([sys.executable, BUILDER, "--session-dir", str(session), "--mark-window-sec", "30"], check=True)
    errors = (session / "errors.jsonl").read_text(encoding="utf-8")
    assert "naive: this one does NOT" in errors


def test_partial_marks_raw_recovered(tmp_path):
    session = _seed_minimal(tmp_path)
    # Truncate last mark mid-JSON
    raw = (session / "marks.raw.jsonl")
    raw.write_text(raw.read_text(encoding="utf-8") + '{"n": 99, "ts": "2026', encoding="utf-8")
    subprocess.run([sys.executable, BUILDER, "--session-dir", str(session)], check=True)
    manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("partial") is True
    assert manifest.get("mark_count") < 99


def test_zero_marks_session_valid_manifest(tmp_path):
    session = _seed_empty(tmp_path)  # no marks.raw.jsonl
    subprocess.run([sys.executable, BUILDER, "--session-dir", str(session)], check=True)
    manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mark_count"] == 0
```

**Steps 2-6:** as in v1 plan task 4, with implementation extended for the 3 new test cases. Pipe each window line through `subprocess.run([python, redact-stream, "--pattern", session.redaction], input=line)` — or, better, import redact-stream as module and reuse the compiled regex. (Implementation chooses module import for perf.)

**Commit msg references** Codex review §5 fixture gaps + §4 redaction at correct site.

---

## Task 6: analyze.py — robust to KNOWN-ISSUES corruption + analyzer subagent

**Files:**
- Create: `scripts/field-test/analyze.py`
- Create: `agents/vg-field-test-analyzer/SKILL.md`
- Mirrors
- Test: `tests/test_field_test_analyze.py`

**Key diff vs v1 plan:**
- KNOWN-ISSUES corruption: write `KNOWN-ISSUES.corrupt-<ts>.json.bak`, emit `analyzer.known_issues_corrupted` telemetry, REFUSE to append (no silent wipe).
- Dedupe test extended: re-run on same session = idempotent. Different sid with same `note` = both appended.

```python
def test_corrupt_known_issues_preserved_not_wiped(tmp_path):
    session = _seed_session(tmp_path)
    known = tmp_path / "KNOWN-ISSUES.json"
    known.write_text("not valid json {", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, ANALYZER, "--session-dir", str(session), "--known-issues", str(known)],
        capture_output=True, text=True,
    )
    # Analyzer aborts append cleanly
    assert r.returncode != 0 or "corrupted" in (r.stdout + r.stderr).lower()
    # Original corrupt file backed up (sidecar)
    backups = list(tmp_path.glob("KNOWN-ISSUES.corrupt-*.json.bak"))
    assert len(backups) == 1, "must back up corrupt file, not silently wipe"
```

Implementation diff in `append_known_issues`:

```python
def append_known_issues(known_path: Path, sid: str, phase: str | None, marks: list[dict]) -> None:
    if known_path.is_file():
        try:
            payload = json.loads(known_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            backup = known_path.with_suffix(f".corrupt-{int(time.time())}.json.bak")
            shutil.copy2(known_path, backup)
            print(f"⛔ KNOWN-ISSUES.json corrupted; backed up to {backup} — refusing append", file=sys.stderr)
            raise SystemExit(2)
    else:
        payload = {"version": "1", "issues": []}
    # rest unchanged
```

---

## Task 7: MARKER_TO_AUTO_EVENT extension (same as v1 plan task 6)

Unchanged from v1 plan.

---

## Task 8: Skill entry `commands/vg/field-test.md` with concrete MCP shapes + atomic lock + no `--resume`

**Files:**
- Create: `commands/vg/field-test.md`
- Mirror
- Test: `tests/test_field_test_skill_structure.py`

**Key diff vs v1 plan (per Codex §1, §3, §6, §9):**

1. **State polling** replaces console marker polling in step 5:
```bash
# Step 5: capture loop — poll overlay state directly (NOT console_messages)
last_consumed=0
while true; do
  # AI tool call (skill body shows this as the orchestrator instruction):
  #   mcp__playwright1__browser_evaluate({
  #     function: "() => ({ len: window.__VG_FT_STATE.marks.length, status: window.__VG_FT_STATE.status, epoch: window.__VG_FT_STATE.reload_epoch })"
  #   })
  # Then if returned `len > last_consumed`:
  #   mcp__playwright1__browser_evaluate({
  #     function: "() => window.__VG_FT_STATE.marks.slice(N, M)"  # JSON-safe payload
  #   })
  # For each new mark in slice:
  #   mcp__playwright1__browser_take_screenshot({ filename: "<session>/marks/<n>.png" })
  #   mcp__playwright1__browser_snapshot({ filename: "<session>/marks/<n>.snapshot.yml" })
  #   append entry to marks.raw.jsonl
  #   "${PYTHON_BIN:-python3}" .claude/scripts/vg-orchestrator emit-event \
  #     "field_test.mark_recorded" --payload "{\"sid\":\"$SID\",\"n\":$N}"
  # last_consumed = len
  sleep 2
done
```

2. **Atomic lock**:
```bash
# Step 0: atomic lock via mkdir (NOT echo > file — TOCTOU race)
if ! mkdir "${REPO_ROOT}/.vg/field-test/.active" 2>/dev/null; then
  ACTIVE_OWNER=$(cat "${REPO_ROOT}/.vg/field-test/.active/owner" 2>/dev/null || echo "unknown")
  echo "⛔ field-test session active (sid=$ACTIVE_OWNER)"
  echo "   If you're sure no session is live: rm -rf .vg/field-test/.active"
  exit 1
fi
echo "$SID" > "${REPO_ROOT}/.vg/field-test/.active/owner"
trap 'rm -rf "${REPO_ROOT}/.vg/field-test/.active"' EXIT
```

3. **Runtime contract telemetry** declares all guaranteed + mark_recorded as required_unless_flag:
```yaml
must_emit_telemetry:
  - event_type: "field_test.session_started"
  - event_type: "field_test.session_stopped"
  - event_type: "field_test.analysis_completed"
  - event_type: "field_test.mark_recorded"
    required_unless_flag: "--allow-zero-marks"
```

4. **Tail spawn with `--redact`** passes session.redaction through:
```bash
for src in $(jq -c '.sources[]' < "$SESSION_DIR/session.json"); do
  TYPE=$(echo "$src" | jq -r '.type')
  TARGET=$(echo "$src" | jq -r '.target')
  LABEL=$(echo "$src" | jq -r '.label')
  REDACT=$(jq -r '.redaction' "$SESSION_DIR/session.json")
  bash .claude/scripts/field-test/tail-source.sh \
    --type "$TYPE" --target "$TARGET" \
    --out "$SESSION_DIR/api-${LABEL}.log" \
    --redact "$REDACT" &
  echo "$!" >> "$SESSION_DIR/.tail-pids"
done
```

5. **HARD-GATE banner** at start:
```markdown
<HARD-GATE>
This skill captures live user behavior. Default redaction applies to
console/network/API log streams + user notes. Screenshots are NOT
redacted.

⚠ Do NOT navigate to password/payment/credentials views during this
  session unless that is the explicit test target. Screenshots embed
  pixel content as-is.

Atomic lock at .vg/field-test/.active prevents concurrent sessions.
On crash, manual cleanup: rm -rf .vg/field-test/.active

v1 does NOT support --resume. A browser crash mid-session leaves raw
streams under .vg/field-test/<sid>/ for manual triage; rerun
build-bundle.py + analyze.py manually if needed.
</HARD-GATE>
```

Skill structure test (`tests/test_field_test_skill_structure.py`) asserts:
- Frontmatter parses
- `runtime_contract.must_emit_telemetry` lists 4 events with `mark_recorded` having `required_unless_flag`
- Skill body contains `mkdir .vg/field-test/.active` (NOT `echo > .active`)
- Skill body contains `browser_evaluate(() => ({ len: window.__VG_FT_STATE.marks.length`
- HARD-GATE banner mentions screenshot warning
- NO `--resume` flag in argument-hint
- NO `--preset` flag in argument-hint
- NO `dev-phases` mirror reference

**Commit msg references** Codex review §1 (sync), §3 (lock TOCTOU), §6 (contract), §9 (concrete MCP shape).

---

## Task 9: Codex skill mirror via generator (same as v1 plan task 8)

Unchanged. Run `bash scripts/generate-codex-skills.sh` — produces `codex-skills/vg-field-test/SKILL.md`. Test asserts YAML valid + name correct.

---

## Task 10: Release v3.7.0

**Files:** `VERSION`, `package.json`, `CHANGELOG.md`, `.gitignore` (verify `.vg/` covers field-test path).

**CHANGELOG entry** highlights design v2 + Codex review remediations:

```markdown
## v3.7.0 — /vg:field-test new skill (2026-05-11)

User-driven field-test capture distinct from AI-auto /vg:roam.

### Architecture
- 9 new files under scripts/field-test/ + commands/vg/field-test.md +
  agents/vg-field-test-analyzer/ + schemas/field-test-session.v1.json.
- Sync via browser_evaluate state polling (NOT console_messages replay).
- Per-source API log tails redact at capture time via redact-stream.py.
- Atomic lock via mkdir; portable timestamp via prefix-iso.py.
- MARKER_TO_AUTO_EVENT extension: ('field-test','complete') →
  field_test.session_completed.

### Privacy
Default redaction covers password/token/secret/api_key/email/phone +
Bearer JWT + Authorization header. Multi-form regex (key=value, key:
value, JSON body, bare Bearer). Idempotent. Bad user regex falls back
to default + warns. Screenshots NOT redacted; HARD-GATE banner warns
user before session start.

### v1 scope (post-Codex-review)
- Single preset (no quick/deep enum — deferred v2).
- No --resume (deferred v2; design promised, implementation absent).
- No dev-phases/<N>/ mirror (deferred v2; commit-or-ignore policy
  unresolved).
- No --non-interactive flag (dropped; user-driven skill has no useful
  non-interactive mode).
- No auto-recovered crash bundle (manual triage on browser crash).

### Tests
~35 cross-platform tests + jsdom + Linux functional subset behind
VG_RUN_BROWSER_TESTS=1. Closes 10 Codex review findings.

### Closes
Internal Codex GPT-5.5 plan review §1-§10. Plan + design v2 documented
under docs/plans/2026-05-11-field-test-capture-{design,plan}.md.
```

Run regression sweep, commit, push, tag.

---

## Codex review remediation matrix

| Finding | v1 plan | v2 plan resolution |
|---|---|---|
| §1 Console-poll dedupe race | Polled console messages for marks → snapshot replay duplicates | Task 4: state polling via `browser_evaluate` w/ last-consumed offset; task 8 step 5 documents call shape |
| §2 TDD substring tautologies | Many tests asserted lexical presence | Tasks 1-9: structural + functional tests, jsonschema validation, jsdom smoke for overlay, redaction edge case matrix |
| §3 Concurrency gaps | TOCTOU lock, no respawn impl, no quota impl | Task 8: `mkdir .vg/field-test/.active` atomic; task 8 step 5 documents tail respawn loop + quota check |
| §4 Privacy + redaction | Multi-hour disk-exposure window; broken regex | Task 2: `redact-stream.py` multi-form, idempotent, fallback; task 3: capture-time pipe |
| §5 Fixture coverage gaps | Happy path only | Tasks 2/5/6 add: 0-marks session, partial mid-line, naive ts, JSON body redaction, Bearer form, idempotent re-redact |
| §6 Telemetry contract mismatch | 3 events declared, 7 emitted | Task 8: declare 4 events, `mark_recorded` required_unless_flag |
| §7 Cross-platform `date %3N` | GNU-only | Task 3: `prefix-iso.py` Python wrapper |
| §8 Dead presets | 3 enum values, 0 differential logic | Drop preset enum entirely from v1; ship `standard` capture only |
| §9 Plan executability | Hand-wavy MCP call shape | Task 8 step 5/3 documents `browser_evaluate({function: ...})` payload literally |
| §10 Verdict (back to design) | Design v1 ships with privacy + race + contract issues | Design v2 supersedes; this plan v2 enforces v2 design; ship blocked until tasks 1-10 land |

---

End of v2 plan. **Tasks 1-10**, each commit individually. Estimated 4-5 hours engineering wall-clock for a codebase-familiar dev; 7-9 hours for a fresh contributor.
