<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Codex Round 2 Correction C inlined below the original task body. -->

## Task 17: Post-deploy smoke + PRE-TEST-REPORT writer

**Files:**
- Create: `scripts/lib/post_deploy_smoke.py`
- Create: `scripts/validators/write-pre-test-report.py`
- Test: `tests/test_post_deploy_smoke.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_post_deploy_smoke.py`:

```python
"""Post-deploy smoke + PRE-TEST-REPORT writer."""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WRITER = REPO / "scripts" / "validators" / "write-pre-test-report.py"


def test_writer_renders_pretty_report(tmp_path: Path) -> None:
    t12_report = tmp_path / "t12.json"
    t12_report.write_text(json.dumps({
        "phase": "test-1.0",
        "started_at": "2026-05-03T10:00:00Z",
        "tier_1": {
            "typecheck":      {"status": "PASS", "duration_ms": 1200},
            "lint":           {"status": "PASS", "duration_ms": 800},
            "debug_leftover": {"status": "PASS", "evidence": [], "duration_ms": 50},
        },
        "tier_2": {"status": "PASS", "runner": "vitest", "duration_ms": 8400},
        "completed_at": "2026-05-03T10:00:11Z",
    }), encoding="utf-8")

    deploy_report = tmp_path / "deploy.json"
    deploy_report.write_text(json.dumps({
        "decision": "sandbox",
        "deployed": True,
        "deploy_url": "https://sandbox.example.com",
        "deploy_duration_ms": 45000,
        "smoke_health_check": {"status": "PASS", "endpoint": "/health", "code": 200},
        "smoke_test_run": {"status": "PASS", "spec_count": 5, "duration_ms": 6000},
    }), encoding="utf-8")

    out = tmp_path / "PRE-TEST-REPORT.md"
    result = subprocess.run([
        "python3", str(WRITER),
        "--phase", "test-1.0",
        "--t12-report", str(t12_report),
        "--deploy-report", str(deploy_report),
        "--output", str(out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    md = out.read_text(encoding="utf-8")
    assert "# Pre-Test Report — test-1.0" in md
    assert "## Tier 1 — Static checks" in md
    assert "## Tier 2 — Local tests" in md
    assert "## Deploy + post-deploy smoke" in md
    assert "vitest" in md
    assert "https://sandbox.example.com" in md


def test_writer_handles_no_deploy(tmp_path: Path) -> None:
    t12_report = tmp_path / "t12.json"
    t12_report.write_text(json.dumps({
        "phase": "test-1.0",
        "started_at": "2026-05-03T10:00:00Z",
        "tier_1": {"typecheck": {"status": "PASS", "duration_ms": 0},
                   "lint": {"status": "SKIPPED", "reason": "no tool", "duration_ms": 0},
                   "debug_leftover": {"status": "PASS", "evidence": [], "duration_ms": 0}},
        "tier_2": {"status": "SKIPPED", "reason": "no tests"},
        "completed_at": "2026-05-03T10:00:01Z",
    }), encoding="utf-8")

    out = tmp_path / "PRE-TEST-REPORT.md"
    result = subprocess.run([
        "python3", str(WRITER),
        "--phase", "test-1.0",
        "--t12-report", str(t12_report),
        "--no-deploy",
        "--output", str(out),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    md = out.read_text(encoding="utf-8")
    assert "Deploy: SKIPPED" in md
```

- [ ] **Step 2: Write the post-deploy smoke library**

Create `scripts/lib/post_deploy_smoke.py`:

```python
"""post_deploy_smoke — health check + smoke test runner against deployed URL.

Used after Task 16's deploy decision invoked /vg:deploy. Curls the
deployed health endpoint, then runs a subset of /vg:test specs against
the deployed URL.
"""
from __future__ import annotations

import subprocess
import time
import urllib.request
import urllib.error
from typing import Any


def health_check(url: str, path: str = "/health", timeout: int = 30, retries: int = 6) -> dict[str, Any]:
    """Curl health endpoint with retry. Returns {status, code, attempts}."""
    started = time.monotonic()
    full = url.rstrip("/") + path
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(full, timeout=timeout) as resp:
                code = resp.getcode()
                if 200 <= code < 300:
                    return {
                        "status": "PASS",
                        "endpoint": path,
                        "code": code,
                        "attempts": attempt,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                    }
                last_code = code
        except urllib.error.URLError:
            last_code = None
        time.sleep(5)
    return {
        "status": "BLOCK",
        "endpoint": path,
        "code": last_code,
        "attempts": retries,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def run_smoke_specs(deploy_url: str, spec_pattern: str = "**/*.smoke.spec.ts",
                     timeout: int = 120) -> dict[str, Any]:
    """Run subset of E2E specs against deployed URL. Smoke tag only."""
    started = time.monotonic()
    cmd = ["npx", "playwright", "test", spec_pattern, "--reporter=json"]
    env = {"BASE_URL": deploy_url}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env={**__import__('os').environ, **env})
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"status": "BLOCK", "reason": f"runner failed: {e}", "duration_ms": int((time.monotonic() - started) * 1000)}
    return {
        "status": "PASS" if proc.returncode == 0 else "BLOCK",
        "spec_count": proc.stdout.count('"status":"passed"') if proc.stdout else 0,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "stdout_tail": proc.stdout[-500:] if proc.stdout else "",
    }
```

- [ ] **Step 3: Write the report writer**

Create `scripts/validators/write-pre-test-report.py`:

```python
#!/usr/bin/env python3
"""write-pre-test-report.py — render PRE-TEST-REPORT.md from JSON inputs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _row(name: str, result: dict) -> str:
    status = result.get("status", "UNKNOWN")
    glyph = {"PASS": "✓", "BLOCK": "⛔", "SKIPPED": "—", "UNKNOWN": "?"}.get(status, "?")
    duration = result.get("duration_ms", 0)
    detail = result.get("reason") or result.get("runner") or ""
    return f"| {name} | {glyph} {status} | {duration}ms | {detail} |"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--t12-report", required=True)
    parser.add_argument("--deploy-report")
    parser.add_argument("--no-deploy", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    t12 = json.loads(Path(args.t12_report).read_text(encoding="utf-8"))

    out = []
    out.append(f"# Pre-Test Report — {args.phase}")
    out.append("")
    out.append(f"**Started:** {t12.get('started_at', '?')}")
    out.append(f"**Completed:** {t12.get('completed_at', '?')}")
    out.append("")
    out.append("## Tier 1 — Static checks")
    out.append("")
    out.append("| Check | Status | Duration | Detail |")
    out.append("|---|---|---|---|")
    for k, v in t12.get("tier_1", {}).items():
        out.append(_row(k, v))
        if k == "debug_leftover" and v.get("evidence"):
            for ev in v["evidence"][:5]:
                out.append(f"  - `{ev.get('file')}:{ev.get('line')}` — `{ev.get('label')}`: `{ev.get('snippet', '')}`")
    out.append("")
    out.append("## Tier 2 — Local tests")
    out.append("")
    t2 = t12.get("tier_2", {})
    out.append("| Status | Runner | Duration | Detail |")
    out.append("|---|---|---|---|")
    glyph = {"PASS": "✓", "BLOCK": "⛔", "SKIPPED": "—"}.get(t2.get("status"), "?")
    out.append(f"| {glyph} {t2.get('status', '?')} | {t2.get('runner', '–')} | {t2.get('duration_ms', 0)}ms | {t2.get('reason', '')} |")
    out.append("")
    out.append("## Deploy + post-deploy smoke")
    out.append("")
    if args.no_deploy:
        out.append("Deploy: SKIPPED (user opted not to deploy or profile = library/cli-tool).")
    elif args.deploy_report:
        d = json.loads(Path(args.deploy_report).read_text(encoding="utf-8"))
        out.append(f"**Decision:** {d.get('decision', '?')}")
        out.append(f"**Deployed:** {'yes' if d.get('deployed') else 'no'}")
        if d.get("deploy_url"):
            out.append(f"**URL:** {d['deploy_url']}")
        if d.get("smoke_health_check"):
            hc = d["smoke_health_check"]
            out.append(f"**Health check:** {hc.get('status')} ({hc.get('code')} on {hc.get('endpoint')}, {hc.get('attempts', 1)} attempts)")
        if d.get("smoke_test_run"):
            sr = d["smoke_test_run"]
            out.append(f"**Smoke specs:** {sr.get('status')} ({sr.get('spec_count', 0)} specs, {sr.get('duration_ms', 0)}ms)")
    out.append("")
    out.append("---")
    out.append("Generated by `scripts/validators/write-pre-test-report.py`.")

    Path(args.output).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"✓ Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests + commit**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
chmod +x scripts/validators/write-pre-test-report.py
python3 -m pytest tests/test_post_deploy_smoke.py -v
git add scripts/lib/post_deploy_smoke.py scripts/validators/write-pre-test-report.py tests/test_post_deploy_smoke.py
git commit -m "feat(pre-test): add post-deploy smoke + PRE-TEST-REPORT.md writer"
```
Expected: 2 passed.



---

## Codex Round 2 Correction C (mandatory — apply on top of the original task body above)

### Correction C — Task 17: total deadline timeout, configurable health, storageState

**Problem (Codex #7, #5b):** `timeout=30` per request × 6 retries can run
~210s — not the documented 30s window. Plus health is unauthenticated
only; smoke specs need role/storageState.

**Patch — Replace `health_check` in `scripts/lib/post_deploy_smoke.py`:**

```python
def health_check(
    url: str,
    path: str = "/health",
    expected_status: int | range = 200,
    headers: dict[str, str] | None = None,
    total_deadline_s: int = 30,
    poll_interval_s: int = 5,
) -> dict[str, Any]:
    """Curl health endpoint with TOTAL deadline (not per-request × retry).

    Codex round 2 fix: previously timeout=30s per req × 6 retries × 5s sleep
    actually ran ~210s. Now: stop at total_deadline_s elapsed regardless of
    attempts.

    headers: optional dict for auth (e.g. {"Authorization": "Bearer ..."}).
    expected_status: int (exact) or range(200, 400) (any 2xx-3xx).
    """
    started = time.monotonic()
    deadline = started + total_deadline_s
    full = url.rstrip("/") + path
    attempts = 0
    last_code: int | None = None
    last_error: str | None = None

    while time.monotonic() < deadline:
        attempts += 1
        per_request_timeout = max(1, int(deadline - time.monotonic()))
        try:
            req = urllib.request.Request(full, headers=headers or {})
            with urllib.request.urlopen(req, timeout=per_request_timeout) as resp:
                code = resp.getcode()
                last_code = code
                ok = (code == expected_status if isinstance(expected_status, int)
                      else code in expected_status)
                if ok:
                    return {
                        "status": "PASS",
                        "endpoint": path,
                        "code": code,
                        "attempts": attempts,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                    }
        except urllib.error.URLError as e:
            last_error = str(e)
        # Don't sleep past deadline
        sleep_until = min(time.monotonic() + poll_interval_s, deadline)
        time.sleep(max(0, sleep_until - time.monotonic()))

    return {
        "status": "BLOCK",
        "endpoint": path,
        "code": last_code,
        "error": last_error,
        "attempts": attempts,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def run_smoke_specs(
    deploy_url: str,
    spec_pattern: str = "**/*.smoke.spec.ts",
    timeout: int = 120,
    storage_state_path: str | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """Run subset of E2E specs against deployed URL.

    storage_state_path: Playwright storageState JSON for authenticated runs
                         (cookies + localStorage). When None, runs unauthenticated.
    role: optional role label injected as VG_TEST_ROLE env var so spec helpers
          can pick the right fixture.
    """
    started = time.monotonic()
    cmd = ["npx", "playwright", "test", spec_pattern, "--reporter=json"]
    if storage_state_path:
        cmd.extend(["--config-override", f"storageState={storage_state_path}"])
    import os as _os
    env = {**_os.environ, "BASE_URL": deploy_url}
    if role:
        env["VG_TEST_ROLE"] = role
    if storage_state_path:
        env["VG_STORAGE_STATE"] = storage_state_path
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"status": "BLOCK", "reason": f"runner failed: {e}",
                "duration_ms": int((time.monotonic() - started) * 1000)}
    return {
        "status": "PASS" if proc.returncode == 0 else "BLOCK",
        "spec_count": proc.stdout.count('"status":"passed"') if proc.stdout else 0,
        "role": role,
        "authenticated": bool(storage_state_path),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "stdout_tail": proc.stdout[-500:] if proc.stdout else "",
    }
```

