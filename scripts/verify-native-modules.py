#!/usr/bin/env python3
"""
verify-native-modules.py — Gate 9 for /vg:build mobile post-wave.

Runs stack-specific dependency/linking probes to catch "builds on my
machine" drift:

  iOS native:           pod install --dry-run          (CocoaPods)
  Android native:       ./gradlew app:dependencies      (Gradle)
  React Native:         npx react-native config         (autolinking JSON)
  Flutter:              flutter pub deps --style=compact

Each backend is independently probed. If the required tool isn't on
PATH, the check is SKIPPED (not failed) — this is expected when the
user runs /vg:build from a non-full-stack host (e.g. no Xcode on Linux).

USAGE
  python verify-native-modules.py \
      [--profile mobile-rn | mobile-flutter | mobile-native-ios | mobile-native-android | mobile-hybrid] \
      [--ios-cmd "pod install --dry-run"] \
      [--android-cmd "./gradlew app:dependencies --quiet"] \
      [--rn-cmd "npx react-native config"] \
      [--flutter-cmd "flutter pub deps --style=compact"] \
      [--skip-on-missing-tool] [--lenient] [--json]

EXIT CODES
  0 ok — no conflicts detected in enabled checks
  1 fail — at least one enabled check reported a real problem
  2 script error

PORTABILITY
  P1: every command string is injected from config.mobile.gates.native_module_linking
      — script does not hardcode any tool invocation.
  P2: subprocess runs are non-fatal on tool missing; classification happens
      in pure Python.
  P3: shutil.which gates every backend.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT = 120


# ---------------------------------------------------------------------
# Output classifiers — per backend. Keep pattern lists short and explicit.
# ---------------------------------------------------------------------
def classify_pod_output(returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    """
    pod install --dry-run exits 0 when OK, non-zero on dependency conflicts.
    stderr typically contains 'Conflict', 'Unable to find', 'Could not find'.
    """
    text = (stderr + "\n" + stdout).lower()
    if returncode != 0:
        for marker in ("conflict", "unable to find", "could not find", "unable to satisfy"):
            if marker in text:
                return {"verdict": "fail", "reason": f"cocoapods reports: {marker}"}
        return {"verdict": "fail", "reason": f"pod exited {returncode}"}
    return {"verdict": "ok", "reason": "cocoapods resolved cleanly"}


def classify_gradle_output(returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    """
    gradle app:dependencies exits 0 on success. Duplicate class warnings
    usually appear as lines starting with 'WARN' or containing 'Duplicate'.
    """
    if returncode != 0:
        return {"verdict": "fail", "reason": f"gradle exited {returncode}: {stderr.splitlines()[-1][:200] if stderr else 'no stderr'}"}
    dupes = [l for l in stdout.splitlines() if "Duplicate class" in l]
    if dupes:
        return {"verdict": "fail", "reason": f"{len(dupes)} duplicate-class warning(s)"}
    return {"verdict": "ok", "reason": "gradle dependency tree clean"}


def classify_rn_output(returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    """
    npx react-native config emits a JSON dump on success. Any parse error
    or non-zero exit indicates autolinking trouble.
    """
    if returncode != 0:
        return {"verdict": "fail", "reason": f"rn config exited {returncode}"}
    # Heuristic: stdout should parse as JSON (it's large but should start with '{')
    stripped = stdout.strip()
    if not stripped.startswith("{"):
        return {"verdict": "fail", "reason": "rn config output is not JSON (autolinking may be broken)"}
    try:
        json.loads(stripped)
    except Exception as exc:
        return {"verdict": "fail", "reason": f"rn config JSON parse failed: {exc}"}
    return {"verdict": "ok", "reason": "autolinking resolved"}


def classify_flutter_output(returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    """
    flutter pub deps exits 0 when resolution succeeds. Conflicts surface as
    'Because ... depends on ... which ...' messages in stderr.
    """
    if returncode != 0:
        return {"verdict": "fail", "reason": f"flutter pub deps exited {returncode}"}
    if "because" in stderr.lower() and "depends on" in stderr.lower():
        return {"verdict": "fail", "reason": "pub version constraint conflict"}
    return {"verdict": "ok", "reason": "pub resolution clean"}


BACKENDS = [
    ("ios", "--ios-cmd", classify_pod_output, "CocoaPods dry-run"),
    ("android", "--android-cmd", classify_gradle_output, "Gradle dependencies"),
    ("rn", "--rn-cmd", classify_rn_output, "React Native autolinking"),
    ("flutter", "--flutter-cmd", classify_flutter_output, "Flutter pub deps"),
]

# Profile → which backends are relevant (drops irrelevant checks even if user
# left the commands populated). This is a pure logic filter, not tool detection.
PROFILE_ENABLED = {
    "mobile-rn": {"ios", "android", "rn"},
    "mobile-flutter": {"ios", "android", "flutter"},
    "mobile-native-ios": {"ios"},
    "mobile-native-android": {"android"},
    "mobile-hybrid": {"ios", "android"},
    # For unknown / unset profile, run whatever commands are provided.
    None: {"ios", "android", "rn", "flutter"},
}


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------
def run_backend(name: str, cmd: str | None, classifier, skip_on_missing: bool, timeout: int) -> dict[str, Any]:
    if not cmd:
        return {"backend": name, "status": "not_configured", "verdict": "skipped"}

    argv = shlex.split(cmd, posix=(sys.platform != "win32"))
    tool = argv[0]
    if shutil.which(tool) is None:
        if skip_on_missing:
            return {"backend": name, "status": "tool_missing", "verdict": "skipped", "tool": tool}
        return {"backend": name, "status": "tool_missing", "verdict": "fail", "tool": tool, "reason": f"{tool} not on PATH"}

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "backend": name,
            "status": "timeout",
            "verdict": "fail",
            "reason": f"{tool} timed out after {timeout}s",
        }

    verdict = classifier(proc.returncode, proc.stdout, proc.stderr)
    return {
        "backend": name,
        "status": "ran",
        "command": cmd,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout.splitlines()[-10:],
        "stderr_tail": proc.stderr.splitlines()[-10:],
        **verdict,
    }


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", help="Mobile profile (filters which backends run)")
    ap.add_argument("--ios-cmd", help="Command string, e.g. 'pod install --dry-run'")
    ap.add_argument("--android-cmd")
    ap.add_argument("--rn-cmd")
    ap.add_argument("--flutter-cmd")
    ap.add_argument("--skip-on-missing-tool", action="store_true", default=True,
                    help="Treat missing tool as skipped (default true)")
    ap.add_argument("--no-skip-on-missing-tool", dest="skip_on_missing_tool", action="store_false",
                    help="Treat missing tool as failure (strict)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--lenient", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    enabled = PROFILE_ENABLED.get(args.profile, PROFILE_ENABLED[None])

    cmd_map = {
        "ios": args.ios_cmd,
        "android": args.android_cmd,
        "rn": args.rn_cmd,
        "flutter": args.flutter_cmd,
    }

    results: list[dict[str, Any]] = []
    for name, _flag, classifier, label in BACKENDS:
        if name not in enabled:
            continue
        res = run_backend(
            name,
            cmd_map[name],
            classifier,
            skip_on_missing=args.skip_on_missing_tool,
            timeout=args.timeout,
        )
        res["label"] = label
        results.append(res)

    report = {
        "profile": args.profile,
        "results": results,
        "summary": {
            "ok": sum(1 for r in results if r["verdict"] == "ok"),
            "fail": sum(1 for r in results if r["verdict"] == "fail"),
            "skipped": sum(1 for r in results if r["verdict"] == "skipped"),
        },
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for r in results:
            icon = {"ok": "✓", "fail": "✗", "skipped": "·"}.get(r["verdict"], "?")
            extra = r.get("reason", "") or r.get("status", "")
            print(f"  {icon} {r['label']} — {r['verdict']} ({extra})")

    failures = [r for r in results if r["verdict"] == "fail"]
    if failures and not args.lenient:
        print("", file=sys.stderr)
        print(f"\033[38;5;208m{len(failures)} native-module check(s) failed.\033[0m", file=sys.stderr)
        for f in failures:
            print(f"   - {f['label']}: {f.get('reason', 'unknown')}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
