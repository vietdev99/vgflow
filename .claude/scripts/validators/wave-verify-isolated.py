#!/usr/bin/env python3
"""
Validator: wave-verify-isolated.py

Phase A (v2.5 hardening, 2026-04-23): post-wave independent verification.

Executor in build.md step 8 reports wave outcome via commit messages
+ build-state.log. Those claims are agent-authored and may not match
runtime reality (e.g., "typecheck PASS" in message but build actually
broken). This validator re-runs verification in a fresh subprocess
(no parent env, no agent memory) to catch claim-vs-reality drift
BEFORE the next wave mutates the index on top of broken state.

Key design (from CrossAI review):
- POST-WAVE not post-task — 5× frequency reduction + outside commit mutex
- Subprocess spawned AFTER wave commit mutex released (commit_sha stable)
- Verification scoped to files touched this wave only (affected mode)
- Timeout at wave level (600s default, vs task-level 300s)
- Config-driven commands (typecheck + test + contract-runtime per profile)
- Output reports divergence per check: executor_claim vs subprocess_result

Usage:
  wave-verify-isolated.py --phase <N> --wave-tag <git_tag> [--mode strict|advisory]

Exit codes:
  0 PASS (no divergence) or WARN (advisory mode)
  1 BLOCK (divergence + strict mode) → orchestrator rolls back wave commits
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Regex to extract executor claims from wave commit messages.
# Pattern: "typecheck: PASS" or "tests: 12/12" or "contract: PASS"
# Tolerant of various phrasings used historically.
CLAIM_TYPECHECK_RE = re.compile(
    r"(?:typecheck|typechk|tsc|type[- ]check)\s*[:=]?\s*(PASS|FAIL|OK|ERROR|SKIP)",
    re.IGNORECASE,
)
CLAIM_TESTS_RE = re.compile(
    r"(?:tests?|vitest|jest|pytest)\s*[:=]?\s*(\d+)\s*/\s*(\d+)",
    re.IGNORECASE,
)
CLAIM_CONTRACT_RE = re.compile(
    r"(?:contract|api[- ]?contract)\s*[:=]?\s*(PASS|FAIL|OK|ERROR|SKIP)",
    re.IGNORECASE,
)


def _read_config() -> dict:
    """Read independent_verify section from vg.config.md (regex parse)."""
    cfg = REPO_ROOT / ".claude" / "vg.config.md"
    defaults = {
        "enabled": True,
        "mode": "strict",            # strict=block | advisory=warn
        "scope": "affected",         # affected | all
        "timeout_seconds": 600,
        "skip_profiles": ["docs"],
        "typecheck_cmd": "pnpm typecheck",
        "test_cmd_affected": "npx vitest related --run",
        "contract_runtime": True,    # also re-run verify-contract-runtime
    }
    if not cfg.exists():
        return defaults
    text = cfg.read_text(encoding="utf-8", errors="replace")

    m = re.search(
        r"^independent_verify:\s*\n((?:[ \t]+\w+:.+\n?)+)", text, re.MULTILINE,
    )
    if not m:
        return defaults
    block = m.group(1)

    def _get(key, cast=str):
        mm = re.search(rf"^[ \t]+{key}:\s*['\"]?([^'\"#\n]+)['\"]?", block, re.MULTILINE)
        return cast(mm.group(1).strip()) if mm else None

    for k in ("mode", "scope", "typecheck_cmd", "test_cmd_affected"):
        v = _get(k)
        if v is not None:
            defaults[k] = v
    for k in ("enabled", "contract_runtime"):
        v = _get(k)
        if v is not None:
            defaults[k] = v.lower() == "true"
    ts = _get("timeout_seconds")
    if ts is not None:
        try:
            defaults["timeout_seconds"] = int(ts)
        except ValueError:
            pass

    return defaults


def _wave_commit_range(wave_tag: str) -> tuple[str, str] | None:
    """Return (start_sha, end_sha) for commits from wave-start tag to HEAD."""
    try:
        start = subprocess.run(
            ["git", "rev-parse", wave_tag],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
        )
        end = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
        )
        if start.returncode != 0 or end.returncode != 0:
            return None
        return (start.stdout.strip(), end.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _wave_changed_files(start_sha: str, end_sha: str) -> list[str]:
    """Files changed between wave-start and HEAD."""
    try:
        cp = subprocess.run(
            ["git", "diff", "--name-only", f"{start_sha}..{end_sha}"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
        )
        if cp.returncode != 0:
            return []
        return [ln.strip() for ln in cp.stdout.splitlines() if ln.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []


def _executor_claims(start_sha: str, end_sha: str) -> dict:
    """Parse commit messages between start..end for executor claims."""
    claims = {"typecheck": None, "tests": None, "contract": None}
    try:
        cp = subprocess.run(
            ["git", "log", f"{start_sha}..{end_sha}", "--format=%B"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
        )
        if cp.returncode != 0:
            return claims
        text = cp.stdout
        m = CLAIM_TYPECHECK_RE.search(text)
        if m:
            verdict = m.group(1).upper()
            claims["typecheck"] = "PASS" if verdict in ("PASS", "OK") else "FAIL"
        m = CLAIM_TESTS_RE.search(text)
        if m:
            passed, total = int(m.group(1)), int(m.group(2))
            claims["tests"] = ("PASS", passed, total) if passed == total else ("FAIL", passed, total)
        m = CLAIM_CONTRACT_RE.search(text)
        if m:
            verdict = m.group(1).upper()
            claims["contract"] = "PASS" if verdict in ("PASS", "OK") else "FAIL"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return claims


def _run_subprocess_isolated(cmd: str, timeout: int) -> dict:
    """Run shell command in fresh subprocess, return {rc, stdout, stderr, duration_s}."""
    # Strip parent VG_* env vars to ensure isolation
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith("VG_") and not k.startswith("CLAUDE_")
    }
    env["VG_REPO_ROOT"] = str(REPO_ROOT)  # still need repo root for sub-validators
    start = time.time()
    try:
        # Windows needs shell=True for pnpm/npm invocation paths
        cp = subprocess.run(
            cmd, shell=True,
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            timeout=timeout, env=env,
        )
        return {
            "rc": cp.returncode,
            "stdout": cp.stdout[-4000:],  # cap for telemetry
            "stderr": cp.stderr[-2000:],
            "duration_s": time.time() - start,
        }
    except subprocess.TimeoutExpired:
        return {
            "rc": -1, "stdout": "", "stderr": "TIMEOUT",
            "duration_s": timeout, "timeout": True,
        }
    except (FileNotFoundError, OSError) as e:
        return {
            "rc": -2, "stdout": "", "stderr": f"spawn_failed: {e}",
            "duration_s": 0.0,
        }


def _compare(claim: str | None, actual_rc: int) -> tuple[str, str]:
    """Return (divergence_type, description) or ('', '') if consistent."""
    if claim is None:
        return "", ""   # executor didn't claim → nothing to compare
    actual = "PASS" if actual_rc == 0 else "FAIL"
    if claim != actual:
        return "divergence", f"executor claimed {claim}, subprocess returned {actual} (rc={actual_rc})"
    return "", ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--wave-tag", required=True,
                    help="Git tag marking wave start (e.g., vg-build-7.14-wave-3-start)")
    ap.add_argument("--mode", default=None, choices=["strict", "advisory"])
    args = ap.parse_args()

    out = Output(validator="wave-verify-isolated")
    with timer(out):
        cfg = _read_config()
        if not cfg["enabled"]:
            emit_and_exit(out)

        mode = args.mode or cfg["mode"]

        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            emit_and_exit(out)

        commit_range = _wave_commit_range(args.wave_tag)
        if not commit_range:
            out.warn(Evidence(
                type="wave_tag_unresolvable",
                message=t("wave_verify.tag_unresolvable.message", tag=args.wave_tag),
                fix_hint=t("wave_verify.tag_unresolvable.fix_hint"),
            ))
            emit_and_exit(out)

        start_sha, end_sha = commit_range
        if start_sha == end_sha:
            # Wave produced 0 commits — nothing to verify
            emit_and_exit(out)

        changed = _wave_changed_files(start_sha, end_sha)
        if not changed:
            emit_and_exit(out)

        claims = _executor_claims(start_sha, end_sha)

        # ──────────────────────────────────────────────────────────────
        # Run subprocess checks

        subprocess_results: dict[str, dict] = {}

        # Typecheck
        if cfg["typecheck_cmd"]:
            subprocess_results["typecheck"] = _run_subprocess_isolated(
                cfg["typecheck_cmd"], cfg["timeout_seconds"],
            )

        # Affected tests (best-effort — may fail on projects without vitest)
        if cfg["test_cmd_affected"]:
            # Pass changed files as arguments if cmd supports it
            files_arg = " ".join(
                f for f in changed if f.endswith((".ts", ".tsx", ".js", ".jsx", ".py"))
            )[:2000]
            cmd = cfg["test_cmd_affected"]
            if files_arg and "{files}" in cmd:
                cmd = cmd.replace("{files}", files_arg)
            elif files_arg:
                cmd = f"{cmd} {files_arg}"
            subprocess_results["tests"] = _run_subprocess_isolated(
                cmd, cfg["timeout_seconds"],
            )

        # Contract runtime (re-invoke verify-contract-runtime)
        if cfg["contract_runtime"]:
            contract_script = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-contract-runtime.py"
            if contract_script.exists():
                subprocess_results["contract"] = _run_subprocess_isolated(
                    f'"{sys.executable}" "{contract_script}" --phase {args.phase}',
                    cfg["timeout_seconds"],
                )

        # ──────────────────────────────────────────────────────────────
        # Compare claims vs actuals

        divergences: list[dict] = []
        for check, result in subprocess_results.items():
            claim = claims.get(check)
            if isinstance(claim, tuple):
                claim = claim[0]  # unpack (verdict, passed, total) → verdict
            kind, desc = _compare(claim, result["rc"])
            if kind:
                divergences.append({
                    "check": check,
                    "claim": claim,
                    "actual_rc": result["rc"],
                    "description": desc,
                    "duration_s": round(result["duration_s"], 1),
                    "stderr_tail": result.get("stderr", "")[-500:],
                })

        # Also surface timeouts as divergence (subprocess couldn't complete)
        for check, result in subprocess_results.items():
            if result.get("timeout"):
                divergences.append({
                    "check": check,
                    "claim": claims.get(check) or "unknown",
                    "actual_rc": "TIMEOUT",
                    "description": f"subprocess exceeded {cfg['timeout_seconds']}s",
                    "duration_s": cfg["timeout_seconds"],
                    "stderr_tail": "",
                })

        if divergences:
            sample = "; ".join(
                f"[{d['check']}] {d['description']}"
                for d in divergences[:5]
            )
            if mode == "strict":
                out.add(Evidence(
                    type="wave_verify_divergence",
                    message=t(
                        "wave_verify.divergence.message",
                        count=len(divergences),
                        wave_tag=args.wave_tag,
                    ),
                    actual=sample,
                    fix_hint=t("wave_verify.divergence.fix_hint"),
                ))
            else:  # advisory
                out.warn(Evidence(
                    type="wave_verify_divergence_advisory",
                    message=t(
                        "wave_verify.divergence_advisory.message",
                        count=len(divergences),
                        wave_tag=args.wave_tag,
                    ),
                    actual=sample,
                    fix_hint=t("wave_verify.divergence_advisory.fix_hint"),
                ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
