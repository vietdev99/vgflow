"""
VG Harness v2.6 Phase G — /vg:learn TTY/HMAC gate regression tests.

4 cases per PLAN-REVISED.md Phase G work item #3:

  1. promote with TTY mocked True + valid 50+ char reason → PASS,
     candidate moves CANDIDATES.md → ACCEPTED.md, learn.promoted
     audit event emitted.
  2. promote with TTY=False AND no HMAC token in env → BLOCK rc=2,
     "TTY or HMAC required" stderr, no state mutation.
  3. AI subagent simulation — no TTY, no env token, no .approver-key
     file → BLOCK + learn.promote_attempt_unauthenticated audit
     event emitted (forensic trail).
  4. Bypass attempt — TTY=False but valid HMAC-signed token in env
     → PASS (documented escape hatch), audit event payload includes
     auth_method="hmac".

The orchestrator's `cmd_learn` lives in __main__.py with module-level
_REPO_ROOT captured at import. For deterministic isolation, cases 1, 3,
4 use the **subprocess CLI path** with VG_REPO_ROOT pointing at
tmp_path; case 2 also uses subprocess so non-TTY behaviour is real
(capture_output strips TTY, matching the AI-subagent scenario).

For case 1 (PASS path) we cannot pretend a real TTY exists in a
subprocess captured by pytest. Instead we mint a real signed HMAC
token via vg-auth.py and treat its env-injection as the "human
operator approved" signal — same as documented automation escape hatch.
The failing-attempt forensic event (case 3) IS the AI-subagent
scenario verified; case 1 is "auth succeeded → mutation happens".

Stdlib only (per harness R6).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATOR_MAIN = REPO_ROOT / ".claude" / "scripts" / "vg-orchestrator" / "__main__.py"
VG_AUTH = REPO_ROOT / ".claude" / "scripts" / "vg-auth.py"


VALID_REASON = (
    "Operator-approved learn promotion after 5 phases of evidence — "
    "rule held consistently per CONTEXT.md decisions D-04 and D-07; "
    "no conflicting ACCEPTED rule, dedupe key unique."
)
assert len(VALID_REASON) >= 50  # sanity


CANDIDATE_BLOCK = """\
```yaml
id: L-042
title: "Test candidate — Phase G TTY gate"
type: rule
scope:
  any_of:
    - phase: "*"
action: must_run
target_step: review
confidence: 0.85
impact: critical
tier: A
created_at: "2026-04-26T00:00:00Z"
evidence:
  - source: "test fixture"
    note: "synthesized for test_learn_tty_gate.py"
```
"""


# ─────────────────────────────── fixtures ─────────────────────────────────


@pytest.fixture
def repo(tmp_path: Path):
    """Build a minimal repo skeleton at tmp_path with one candidate.

    Pre-creates the events.db schema + a `runs` row matching the run_id
    cmd_learn uses (`learn-promote` / `learn-reject`). The events FK
    constraint references `runs(run_id)`; without a parent row the
    db.append_event call inside cmd_learn fails silently (wrapped in
    try/except for production resilience) and the test can't observe
    the audit emission.
    """
    bootstrap = tmp_path / ".vg" / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)
    (bootstrap / "CANDIDATES.md").write_text(
        f"# Bootstrap CANDIDATES\n\n{CANDIDATE_BLOCK}\n",
        encoding="utf-8",
    )
    (bootstrap / "REJECTED.md").write_text(
        "# Bootstrap REJECTED\n\n", encoding="utf-8",
    )
    # ACCEPTED.md intentionally absent — exercises new-file branch
    # Need .git for find_repo_root fallback (defensive)
    (tmp_path / ".git").mkdir(exist_ok=True)

    # Pre-seed runs table so cmd_learn audit emits don't trip the
    # events.run_id → runs.run_id FK constraint. Reuse db module by
    # pointing VG_REPO_ROOT before import — but db is module-level
    # captured, so use raw sqlite3 to avoid import-order races between
    # tests in the same process.
    import sqlite3
    db_path = tmp_path / ".vg" / "events.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        # Mirror db.py _init_schema (kept inline so test doesn't depend
        # on module-level VG_REPO_ROOT capture at db import time).
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
              run_id TEXT PRIMARY KEY,
              command TEXT NOT NULL,
              phase TEXT NOT NULL,
              args TEXT NOT NULL DEFAULT '',
              started_at TEXT NOT NULL,
              completed_at TEXT,
              outcome TEXT,
              session_id TEXT,
              git_sha TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL,
              ts TEXT NOT NULL,
              event_type TEXT NOT NULL,
              phase TEXT NOT NULL,
              command TEXT NOT NULL,
              step TEXT,
              actor TEXT NOT NULL,
              outcome TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              prev_hash TEXT NOT NULL,
              this_hash TEXT NOT NULL UNIQUE,
              FOREIGN KEY (run_id) REFERENCES runs(run_id)
            );
            """
        )
        for run_id in ("learn-promote", "learn-reject"):
            conn.execute(
                "INSERT OR IGNORE INTO runs(run_id, command, phase, args, "
                "started_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, "learn", "", "", "2026-04-26T00:00:00Z"),
            )
        conn.commit()
    finally:
        conn.close()
    return tmp_path


def _run_cli(
    args: list[str], cwd: Path,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    # Strip inherited human-operator state for determinism
    env.pop("VG_HUMAN_OPERATOR", None)
    env.pop("VG_ALLOW_FLAGS_LEGACY_RAW", None)
    env.pop("VG_ALLOW_FLAGS_STRICT_MODE", None)
    if extra_env:
        env.update(extra_env)
    # CRITICAL: capture_output=True redirects stdout/stderr but on Windows
    # leaves stdin attached to parent terminal — child's os.isatty(0)
    # returns True, defeating the no-TTY scenario. Even subprocess.DEVNULL
    # for stdin returns isatty=True on Windows due to console handle
    # inheritance quirks (verified empirically on Python 3.11 / Win10).
    # The reliable cross-platform fix: pass input="" which forces stdin=PIPE
    # and writes empty bytes. Child's stdin fd then points at a real
    # disconnected pipe → os.isatty()=False on every platform.
    return subprocess.run(
        [sys.executable, str(ORCHESTRATOR_MAIN), *args],
        input="",
        capture_output=True, text=True, timeout=30, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _query_events(repo_path: Path, event_type: str) -> list[dict]:
    """Read events.jsonl projection at repo_path. Return matching events."""
    proj = repo_path / ".vg" / "events.jsonl"
    if not proj.exists():
        return []
    out = []
    for line in proj.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event_type") == event_type:
            out.append(ev)
    return out


def _mint_hmac_token(repo_path: Path, flag: str = "learn-promote") -> str | None:
    """Mint a real HMAC token via vg-auth.py if available. Returns token
    string or None when vg-auth.py is missing (test will skip the bypass
    case in that environment).

    vg-auth.py signs against ~/.vg/.approver-key by default. Tests may not
    have a key — we override via VG_APPROVER_KEY_DIR env if vg-auth supports
    it. Fall back to None on any error so tests don't false-fail in CI
    without HMAC infra.
    """
    if not VG_AUTH.exists():
        return None
    # Use repo-local key dir to avoid touching ~
    key_dir = repo_path / ".vg" / "auth"
    key_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["VG_APPROVER_KEY_DIR"] = str(key_dir)
    env["VG_REPO_ROOT"] = str(repo_path)
    try:
        # First create signing key (idempotent)
        r = subprocess.run(
            [sys.executable, str(VG_AUTH), "init"],
            capture_output=True, text=True, timeout=10, env=env,
            encoding="utf-8", errors="replace",
        )
        if r.returncode != 0 and "already exists" not in (r.stderr + r.stdout):
            return None
        # Then mint approval token for our flag — JSON output for robust parse
        r = subprocess.run(
            [sys.executable, str(VG_AUTH), "approve", "--flag", flag,
             "--ttl-days", "1", "--quiet"],
            capture_output=True, text=True, timeout=10, env=env,
            encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            return None
        # --quiet emits just the token on stdout
        token = (r.stdout or "").strip().splitlines()[-1].strip()
        if "." in token:  # heuristic: signed tokens contain b64-payload "." sig
            return token
    except Exception:
        return None
    return None


# ─────────────────────────────── cases ────────────────────────────────────


def test_01_promote_with_valid_auth_succeeds_and_emits_audit(repo: Path):
    """Case 1: TTY-equivalent (HMAC token) + valid reason → PASS, mutation
    + learn.promoted audit event.

    Subprocess inherits no real TTY (capture_output=True), so we use the
    documented HMAC escape hatch as the "approved" signal. The mint helper
    falls back gracefully if vg-auth.py infrastructure is absent in CI —
    in that case we skip with a marker rather than false-fail.
    """
    token = _mint_hmac_token(repo, flag="learn-promote")
    if not token:
        pytest.skip(
            "vg-auth.py HMAC token mint unavailable in this environment "
            "— bypass-path case 4 also skipped. Functional case 1 needs "
            "real signed token to exercise PASS branch in non-TTY subprocess."
        )

    # Re-use the same key-dir for verify side (must match the dir used
    # by _mint_hmac_token to sign the token).
    key_dir = repo / ".vg" / "auth"
    result = _run_cli(
        ["learn", "promote", "--candidate", "L-042",
         "--reason", VALID_REASON],
        cwd=repo,
        extra_env={
            "VG_HUMAN_OPERATOR": token,
            "VG_APPROVER_KEY_DIR": str(key_dir),
        },
    )
    assert result.returncode == 0, (
        f"Expected PASS rc=0, got {result.returncode}\n"
        f"stderr: {result.stderr[-400:]}\nstdout: {result.stdout[-400:]}"
    )

    # Candidate removed from CANDIDATES.md
    candidates_text = (repo / ".vg" / "bootstrap" / "CANDIDATES.md") \
        .read_text(encoding="utf-8", errors="replace")
    assert "id: L-042" not in candidates_text, \
        "candidate should be removed from CANDIDATES.md"

    # Block appears in ACCEPTED.md with auth comment
    accepted_text = (repo / ".vg" / "bootstrap" / "ACCEPTED.md") \
        .read_text(encoding="utf-8", errors="replace")
    assert "id: L-042" in accepted_text
    assert "promote L-id=L-042" in accepted_text
    assert "auth=hmac" in accepted_text or "auth=tty" in accepted_text

    # Audit event emitted
    events = _query_events(repo, "learn.promoted")
    assert len(events) >= 1, "learn.promoted event must be emitted"
    payload = events[0]["payload"]  # projection stores parsed dict
    assert payload.get("candidate_id") == "L-042"
    assert payload.get("tier") == "A"
    assert payload.get("auth_method") in ("hmac", "tty")
    # Reason recorded (may be truncated — assert head)
    assert "Operator-approved learn promotion" in (payload.get("reason") or "")


def test_02_promote_no_tty_no_token_blocks(repo: Path):
    """Case 2: subprocess captured (no TTY) + no env token → BLOCK rc=2,
    candidate untouched."""
    result = _run_cli(
        ["learn", "promote", "--candidate", "L-042",
         "--reason", VALID_REASON],
        cwd=repo,
    )
    assert result.returncode == 2, (
        f"Expected BLOCK rc=2 (no auth), got rc={result.returncode}\n"
        f"stderr: {result.stderr[-400:]}"
    )
    body = (result.stderr + result.stdout).lower()
    assert ("tty" in body) or ("hmac" in body) or ("operator" in body), (
        "stderr should explain TTY/HMAC requirement"
    )

    # No mutation
    candidates_text = (repo / ".vg" / "bootstrap" / "CANDIDATES.md") \
        .read_text(encoding="utf-8", errors="replace")
    assert "id: L-042" in candidates_text, \
        "candidate must remain after blocked promote"
    assert not (repo / ".vg" / "bootstrap" / "ACCEPTED.md").exists(), \
        "ACCEPTED.md must not be created on blocked promote"


def test_03_ai_subagent_simulation_blocks_and_emits_forensic_event(
    repo: Path,
):
    """Case 3: AI subagent — no TTY, no env token, no approver-key file.

    Verifies forensic-trail event emission on blocked attempts so we can
    audit unauthenticated promote attempts post-hoc.

    Important: place HOME at a tmp dir so any pre-existing ~/.vg/.approver-key
    on the developer machine doesn't accidentally satisfy the gate.
    """
    home_isolated = repo / "_home"
    home_isolated.mkdir(exist_ok=True)
    extra = {"HOME": str(home_isolated), "USERPROFILE": str(home_isolated)}

    result = _run_cli(
        ["learn", "promote", "--candidate", "L-042",
         "--reason", VALID_REASON],
        cwd=repo,
        extra_env=extra,
    )
    assert result.returncode == 2, (
        f"AI subagent scenario must BLOCK; got rc={result.returncode}\n"
        f"stderr: {result.stderr[-400:]}"
    )

    # Forensic event must be emitted regardless of failure
    events = _query_events(repo, "learn.promote_attempt_unauthenticated")
    assert len(events) >= 1, (
        "Forensic event learn.promote_attempt_unauthenticated MUST be "
        "emitted on blocked attempt"
    )
    payload = events[0]["payload"]
    assert payload.get("candidate_id") == "L-042"
    assert int(payload.get("reason_len", 0)) >= 50, \
        "reason_len recorded for audit"

    # Sanity: no successful event leaked
    success_events = _query_events(repo, "learn.promoted")
    assert success_events == [], \
        "no learn.promoted event on blocked attempt"


def test_04_hmac_token_bypass_succeeds_with_auth_method_hmac(repo: Path):
    """Case 4: TTY=False but signed HMAC token in env → PASS (documented
    automation escape hatch), audit payload tags auth_method=hmac.

    This is structurally the same path as case 1 but explicitly asserts the
    HMAC route. If case 1 succeeds in this environment, case 4 will too;
    if vg-auth.py is missing both skip together — by design.
    """
    token = _mint_hmac_token(repo, flag="learn-promote")
    if not token:
        pytest.skip(
            "vg-auth.py HMAC mint unavailable — bypass case can't run "
            "without real signed token. Case 3 already covers the "
            "no-token BLOCK path so security envelope is validated."
        )

    key_dir = repo / ".vg" / "auth"
    result = _run_cli(
        ["learn", "promote", "--candidate", "L-042",
         "--reason", VALID_REASON],
        cwd=repo,
        extra_env={
            "VG_HUMAN_OPERATOR": token,
            "VG_APPROVER_KEY_DIR": str(key_dir),
        },
    )
    assert result.returncode == 0, (
        f"HMAC token must satisfy gate; got rc={result.returncode}\n"
        f"stderr: {result.stderr[-400:]}"
    )

    events = _query_events(repo, "learn.promoted")
    assert len(events) >= 1
    payload = events[-1]["payload"]
    assert payload.get("auth_method") == "hmac", (
        f"auth_method should tag the HMAC route specifically; "
        f"got {payload.get('auth_method')!r}"
    )
