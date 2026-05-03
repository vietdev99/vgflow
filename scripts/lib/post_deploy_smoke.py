"""post_deploy_smoke — health check + smoke test runner against deployed URL.

Used after Task 16's deploy decision invoked /vg:deploy. Curls the
deployed health endpoint, then runs a subset of /vg:test specs against
the deployed URL.

Codex Round 2 Correction C: health_check uses TOTAL deadline (not
per-request × retry × sleep), supports custom expected_status range and
auth headers. run_smoke_specs supports Playwright storageState for
authenticated runs + role injection via VG_TEST_ROLE env var.
"""
from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any


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
    env = {**os.environ, "BASE_URL": deploy_url}
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
