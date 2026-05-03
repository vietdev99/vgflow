#!/usr/bin/env python3
"""
maestro-mcp.py — Cross-platform Maestro CLI wrapper for VG mobile review/test.

Exposes a subcommand interface the VG workflow can call just like the
Playwright MCP tool chain, but without depending on an unofficial Maestro
MCP server. Everything is subprocess-based, tool-detected, OS-aware.

CALLED BY
  /vg:review Phase 2 (mobile discovery) — via Bash + JSON parse
  /vg:test step 5c/5d (mobile flows + codegen) — same pattern

SUBCOMMANDS
  check-prereqs                                     — report tool availability
  list-devices                                      — connected simulators/emulators
  launch-app    --bundle-id X   [--device N]        — install + start app
  discover      --flow NAME     [--device N] [--max-steps N]
                                                    — organic screen exploration
  run-flow      --yaml PATH     [--device N]        — execute declarative flow
  screenshot    --device N      --out PATH

GLOBAL FLAGS
  --json              emit JSON result (default: human-friendly)
  --timeout SEC       subprocess timeout per call (default: 120)

EXIT CODES
  0  ok
  1  real failure (tool present, operation failed)
  2  tool missing (expected for non-darwin host, informational)
  3  bad arguments

OS MATRIX
  macOS:           maestro, adb, xcrun-simctl all available
  Linux:           maestro, adb available; xcrun-simctl missing (iOS skipped)
  Windows/msys:    maestro, adb via Android Studio SDK; xcrun-simctl missing

PORTABILITY
  P2: uname-based host detection; never assume Mac.
  P3: shutil.which gates every subprocess call; tool-missing returns exit 2.
  All JSON output serialized via json.dumps — safe for pipe to VG bash.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 120


# ---------------------------------------------------------------------
# Host + tool detection
# ---------------------------------------------------------------------
def host_os() -> str:
    """Return normalized host: darwin | linux | windows | unknown."""
    sysname = platform.system().lower()
    if "darwin" in sysname or sysname == "mac":
        return "darwin"
    if "linux" in sysname:
        return "linux"
    if "windows" in sysname or "mingw" in sysname or "msys" in sysname:
        return "windows"
    return "unknown"


def tool_path(name: str) -> str | None:
    """Return absolute path of tool or None if missing."""
    return shutil.which(name)


def tool_status(name: str) -> dict[str, Any]:
    p = tool_path(name)
    return {
        "tool": name,
        "available": p is not None,
        "path": p,
    }


# ---------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------
def run_cmd(
    argv: list[str],
    timeout: int = DEFAULT_TIMEOUT,
    cwd: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Run a subprocess. Never raises — returns dict with stdout/stderr/returncode.

    Caller decides how to interpret returncode. tool_missing (2) must be
    detected BEFORE calling this by checking shutil.which.
    """
    binary = argv[0]
    resolved = tool_path(binary)
    if resolved is None:
        return {
            "ok": False,
            "status": "tool_missing",
            "tool": binary,
            "returncode": 2,
            "stdout": "",
            "stderr": f"tool '{binary}' not found on PATH",
            "reason": f"{binary} is not installed or not on PATH",
        }

    # Use the full resolved path as argv[0] so Windows subprocess can locate
    # .bat/.cmd/.exe shims without shell=True (which would need quoting tricks).
    exec_argv = [resolved] + list(argv[1:])

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)

    try:
        proc = subprocess.run(
            exec_argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            env=env,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "status": "ok" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "reason": f"{binary} exited with {proc.returncode}" if proc.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "status": "timeout",
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "reason": f"{binary} timed out after {timeout}s",
        }
    except FileNotFoundError:
        # Race: PATH lookup ok but exec failed
        return {
            "ok": False,
            "status": "tool_missing",
            "tool": binary,
            "returncode": 2,
            "stdout": "",
            "stderr": "",
            "reason": f"{binary} vanished between PATH lookup and exec",
        }


# ---------------------------------------------------------------------
# Subcommand: check-prereqs
# ---------------------------------------------------------------------
def cmd_check_prereqs(args: argparse.Namespace) -> dict[str, Any]:
    host = host_os()
    tools = {
        "maestro": tool_status("maestro"),
        "adb": tool_status("adb"),
    }
    if host == "darwin":
        tools["xcrun"] = tool_status("xcrun")
        tools["simctl"] = {
            "tool": "xcrun simctl",
            "available": tool_path("xcrun") is not None,
            "path": tool_path("xcrun"),
        }
    else:
        # non-darwin: iOS simulator not supported, mark intentionally skipped
        tools["xcrun"] = {
            "tool": "xcrun",
            "available": False,
            "path": None,
            "reason": f"not applicable on {host}",
        }
        tools["simctl"] = {
            "tool": "xcrun simctl",
            "available": False,
            "path": None,
            "reason": f"iOS simulator unsupported on {host}",
        }

    # Summary: can we do android flows? ios flows?
    can_android = tools["maestro"]["available"] and tools["adb"]["available"]
    can_ios = host == "darwin" and tools["maestro"]["available"] and tools["xcrun"]["available"]

    return {
        "status": "ok",
        "host_os": host,
        "tools": tools,
        "capabilities": {
            "android_flows": can_android,
            "ios_flows": can_ios,
        },
        "hints": _install_hints(host, tools),
    }


def _install_hints(host: str, tools: dict[str, dict]) -> list[str]:
    hints = []
    if not tools["maestro"]["available"]:
        if host == "darwin" or host == "linux":
            hints.append("Install Maestro: curl -Ls 'https://get.maestro.mobile.dev' | bash")
        elif host == "windows":
            hints.append("Install Maestro on Windows: follow https://maestro.mobile.dev/getting-started/installing-maestro/windows")
    if not tools["adb"]["available"]:
        hints.append("Install adb via Android Studio SDK Tools or standalone platform-tools: https://developer.android.com/tools/releases/platform-tools")
    if host != "darwin" and not tools.get("xcrun", {}).get("available"):
        hints.append("iOS simulator requires macOS. Use EAS/Codemagic cloud build for iOS targets.")
    return hints


# ---------------------------------------------------------------------
# Subcommand: list-devices
# ---------------------------------------------------------------------
def cmd_list_devices(args: argparse.Namespace) -> dict[str, Any]:
    devices: list[dict[str, Any]] = []

    # Android via adb
    if tool_path("adb"):
        adb_res = run_cmd(["adb", "devices", "-l"], timeout=10)
        if adb_res["ok"]:
            for line in adb_res["stdout"].splitlines()[1:]:  # skip header
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1] in ("device", "emulator"):
                    devices.append({
                        "platform": "android",
                        "id": parts[0],
                        "state": parts[1],
                        "details": " ".join(parts[2:]) if len(parts) > 2 else "",
                    })

    # iOS via xcrun simctl (darwin only)
    if host_os() == "darwin" and tool_path("xcrun"):
        sim_res = run_cmd(["xcrun", "simctl", "list", "devices", "--json"], timeout=15)
        if sim_res["ok"]:
            try:
                data = json.loads(sim_res["stdout"])
                for runtime, dev_list in data.get("devices", {}).items():
                    for d in dev_list:
                        if d.get("state") == "Booted" or d.get("isAvailable"):
                            devices.append({
                                "platform": "ios",
                                "id": d.get("udid"),
                                "name": d.get("name"),
                                "state": d.get("state"),
                                "runtime": runtime,
                            })
            except json.JSONDecodeError:
                pass

    return {
        "status": "ok",
        "count": len(devices),
        "devices": devices,
    }


# ---------------------------------------------------------------------
# Subcommand: launch-app
# ---------------------------------------------------------------------
def cmd_launch_app(args: argparse.Namespace) -> dict[str, Any]:
    if not args.bundle_id:
        return {"status": "bad_args", "reason": "--bundle-id required", "returncode": 3}
    if not tool_path("maestro"):
        return {"status": "tool_missing", "reason": "maestro not installed", "returncode": 2}

    # Maestro's launchApp/runFlow operates on whatever device it auto-selects.
    # Pass MAESTRO_DEVICE env if --device specified.
    env_extra = {}
    if args.device:
        env_extra["MAESTRO_DEVICE"] = args.device

    # Use an inline flow: launchApp
    launch_flow = f"appId: {args.bundle_id}\n---\n- launchApp\n"
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / f"vg-launch-{os.getpid()}.yaml"
    tmp.write_text(launch_flow, encoding="utf-8")
    try:
        res = run_cmd(["maestro", "test", str(tmp)], timeout=args.timeout, env_extra=env_extra)
        return {
            "status": res["status"],
            "returncode": res["returncode"],
            "bundle_id": args.bundle_id,
            "device": args.device or "(auto)",
            "stdout_tail": res["stdout"].splitlines()[-10:],
            "stderr_tail": res["stderr"].splitlines()[-10:],
        }
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------
# Subcommand: discover (organic exploration)
# ---------------------------------------------------------------------
def cmd_discover(args: argparse.Namespace) -> dict[str, Any]:
    """
    Maestro doesn't have an official "organic explore" primitive. We
    implement discovery by running maestro hierarchy + screenshot per
    step, which the caller can sequence with tapCenter for N steps.

    For V1 this subcommand returns a single snapshot (hierarchy + screenshot
    path) for a given flow trigger. Full organic exploration is a multi-call
    pattern orchestrated by /vg:review.
    """
    if not args.flow:
        return {"status": "bad_args", "reason": "--flow required", "returncode": 3}
    if not tool_path("maestro"):
        return {"status": "tool_missing", "reason": "maestro not installed", "returncode": 2}

    out_dir = Path(args.out_dir) if args.out_dir else Path(os.environ.get("TMPDIR", "/tmp")) / f"vg-discover-{os.getpid()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    env_extra = {}
    if args.device:
        env_extra["MAESTRO_DEVICE"] = args.device

    # Screenshot
    screenshot_path = out_dir / f"{args.flow}.png"
    shot_res = run_cmd(
        ["maestro", "studio", "--help"],  # probe-only; real screenshot below
        timeout=5,
    )
    # Real screenshot via inline flow
    shot_flow = f"appId: discover.probe\n---\n- takeScreenshot: {screenshot_path.stem}\n"
    shot_yaml = out_dir / "shot.yaml"
    shot_yaml.write_text(shot_flow, encoding="utf-8")
    shot_res = run_cmd(["maestro", "test", str(shot_yaml)], timeout=args.timeout, env_extra=env_extra)

    # Hierarchy
    hier_res = run_cmd(["maestro", "hierarchy"], timeout=30, env_extra=env_extra)
    hierarchy_raw = hier_res.get("stdout", "")

    # Write hierarchy to file so caller can pipe to Haiku scanner
    hier_path = out_dir / f"{args.flow}.hierarchy.json"
    hier_path.write_text(hierarchy_raw, encoding="utf-8")

    return {
        "status": "ok" if (shot_res["ok"] and hier_res["ok"]) else "partial",
        "flow": args.flow,
        "device": args.device or "(auto)",
        "artifacts": {
            "screenshot": str(screenshot_path) if screenshot_path.exists() else None,
            "hierarchy": str(hier_path) if hier_path.exists() else None,
        },
        "out_dir": str(out_dir),
    }


# ---------------------------------------------------------------------
# Subcommand: run-flow (declarative YAML)
# ---------------------------------------------------------------------
def cmd_run_flow(args: argparse.Namespace) -> dict[str, Any]:
    if not args.yaml:
        return {"status": "bad_args", "reason": "--yaml required", "returncode": 3}
    yaml_path = Path(args.yaml)
    if not yaml_path.is_file():
        return {"status": "not_found", "reason": f"yaml not found: {yaml_path}", "returncode": 1}
    if not tool_path("maestro"):
        return {"status": "tool_missing", "reason": "maestro not installed", "returncode": 2}

    env_extra = {}
    if args.device:
        env_extra["MAESTRO_DEVICE"] = args.device

    res = run_cmd(["maestro", "test", str(yaml_path)], timeout=args.timeout, env_extra=env_extra)
    return {
        "status": res["status"],
        "returncode": res["returncode"],
        "yaml": str(yaml_path),
        "device": args.device or "(auto)",
        "stdout_tail": res["stdout"].splitlines()[-20:],
        "stderr_tail": res["stderr"].splitlines()[-20:],
    }


# ---------------------------------------------------------------------
# Subcommand: screenshot
# ---------------------------------------------------------------------
def cmd_screenshot(args: argparse.Namespace) -> dict[str, Any]:
    if not args.out:
        return {"status": "bad_args", "reason": "--out required", "returncode": 3}
    if not tool_path("maestro"):
        return {"status": "tool_missing", "reason": "maestro not installed", "returncode": 2}

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    env_extra = {}
    if args.device:
        env_extra["MAESTRO_DEVICE"] = args.device

    # Use inline flow with takeScreenshot
    shot_flow = f"appId: screenshot.probe\n---\n- takeScreenshot: {out_path.stem}\n"
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / f"vg-shot-{os.getpid()}.yaml"
    tmp.write_text(shot_flow, encoding="utf-8")
    try:
        res = run_cmd(["maestro", "test", str(tmp)], timeout=args.timeout, env_extra=env_extra, cwd=str(out_path.parent))
        return {
            "status": res["status"],
            "returncode": res["returncode"],
            "out": str(out_path),
            "device": args.device or "(auto)",
            "exists": out_path.exists(),
        }
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------
def _add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--device", help="Device id / emulator name (env MAESTRO_DEVICE)")
    sub.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Subprocess timeout seconds")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="maestro-mcp",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check-prereqs", help="Report tool availability")
    _add_common(p)

    p = sub.add_parser("list-devices", help="List connected simulators/emulators/devices")
    _add_common(p)

    p = sub.add_parser("launch-app", help="Install + start app on a device")
    p.add_argument("--bundle-id", required=True)
    _add_common(p)

    p = sub.add_parser("discover", help="Capture screenshot + hierarchy for a flow")
    p.add_argument("--flow", required=True, help="Flow identifier (used for output filenames)")
    p.add_argument("--out-dir", help="Where to write artifacts (default: TMPDIR)")
    p.add_argument("--max-steps", type=int, default=1, help="Steps to exercise (V1: 1 = just capture)")
    _add_common(p)

    p = sub.add_parser("run-flow", help="Execute a declarative Maestro YAML flow")
    p.add_argument("--yaml", required=True)
    _add_common(p)

    p = sub.add_parser("screenshot", help="Ad-hoc screenshot capture")
    p.add_argument("--out", required=True)
    _add_common(p)

    return ap


DISPATCH = {
    "check-prereqs": cmd_check_prereqs,
    "list-devices": cmd_list_devices,
    "launch-app": cmd_launch_app,
    "discover": cmd_discover,
    "run-flow": cmd_run_flow,
    "screenshot": cmd_screenshot,
}


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()

    handler = DISPATCH.get(args.cmd)
    if handler is None:
        print(f"ERROR: unknown subcommand '{args.cmd}'", file=sys.stderr)
        return 3

    result = handler(args)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # Human-friendly: show status + key fields
        print(f"[{args.cmd}] status={result.get('status')}")
        for k, v in result.items():
            if k == "status":
                continue
            if isinstance(v, (list, dict)):
                print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:200]}")
            else:
                print(f"  {k}: {v}")

    # Map status -> exit code
    status = result.get("status", "ok")
    rc = result.get("returncode")
    if isinstance(rc, int):
        return rc
    if status in ("ok", "partial"):
        return 0
    if status == "tool_missing":
        return 2
    if status == "bad_args":
        return 3
    return 1


if __name__ == "__main__":
    sys.exit(main())
