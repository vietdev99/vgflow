"""Regression tests for bug-reporter shell quoting."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BUG_REPORTER = REPO_ROOT / "commands" / "vg" / "_shared" / "lib" / "bug-reporter.sh"


def _bash_exe() -> str | None:
    candidates: list[str] = []
    for path in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        os.environ.get("BASH", ""),
        shutil.which("bash") or "",
    ):
        if path and path not in candidates:
            candidates.append(path)
    for path in candidates:
        p = Path(path)
        if not p.exists():
            continue
        if str(p).lower().endswith(r"windows\system32\bash.exe"):
            continue
        return str(p)
    return None


def test_bug_reporter_handles_adversarial_context_without_shell_substitution(tmp_path):
    bash = _bash_exe()
    if not bash:
        pytest.skip("bash not available")

    shutil.copy2(BUG_REPORTER, tmp_path / "bug-reporter.sh")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "VGFLOW-VERSION").write_text("2.28.0\n", encoding="utf-8")

    context = "quote ' and triple ''' plus $HOME, `cmd`, and newline\nsecond line"
    event = {
        "signature": "4579aef3",
        "type": "helper_error",
        "severity": "medium",
        "version": "2.28.0",
        "os": "darwin",
        "ts": "2026-04-28T21:48:52Z",
        "data": {"context": context},
    }

    script = r'''
set -euo pipefail
source ./bug-reporter.sh

mkdir -p fakebin
cat > fakebin/gh <<'GH'
#!/usr/bin/env bash
  if [ "${1:-}" = "auth" ] && [ "${2:-}" = "status" ]; then
    exit 0
  fi
  if [ "${1:-}" = "issue" ] && [ "${2:-}" = "list" ]; then
    exit 0
  fi
  if [ "${1:-}" = "issue" ] && [ "${2:-}" = "create" ]; then
    while [ "$#" -gt 0 ]; do
      if [ "${1:-}" = "--body" ]; then
        shift
        printf '%s' "${1:-}" > "$BODY_OUT"
      fi
      shift || true
    done
  fi
  exit 1
GH
chmod +x fakebin/gh
export PATH="$PWD/fakebin:$PATH"

CONFIG_BUG_REPORTING_ENABLED=true \
CONFIG_BUG_REPORTING_SEVERITY_THRESHOLD=critical \
CONFIG_BUG_REPORTING_QUEUE="$QUEUE_OUT" \
report_bug "subst-regression" "helper_error" "$BR_CONTEXT" "medium"

python3 - <<'PY'
import json, os
queue = os.environ["QUEUE_OUT"]
with open(queue, encoding="utf-8") as fh:
    line = fh.readline()
event = json.loads(line)
assert event["data"]["context"] == os.environ["BR_CONTEXT"]
PY

bug_reporter_github_submit_from_event "$BR_EVENT" || true
test -s "$BODY_OUT"
grep -q "triple" "$BODY_OUT"
grep -q "4579aef3" "$BODY_OUT"
'''
    env = os.environ.copy()
    env.update(
        {
            "BR_CONTEXT": context,
            "BR_EVENT": json.dumps(event),
            "QUEUE_OUT": str(tmp_path / "queue.jsonl"),
            "BODY_OUT": str(tmp_path / "body.md"),
        }
    )
    result = subprocess.run(
        [bash, "-lc", script],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    assert result.returncode == 0, (result.stdout or "") + (result.stderr or "")
