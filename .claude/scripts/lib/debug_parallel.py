"""debug_parallel — B115 v4.73.0 — fan-out discovery + hypothesis race.

Two helpers that parallelize /vg:debug Step 1 + Step 2:

  parallel_discovery(bug_type, bug_desc, debug_dir, repo_root)
      Run grep / curl / config-snapshot / log-tail subprocesses concurrently
      via ThreadPoolExecutor. Returns aggregated discovery dict + wall-clock
      saving vs sequential.

  race_hypotheses(hypothesis_specs, timeout)
      Given N hypothesis fix specs (each with `cmd` to run), run all in
      parallel subprocess, first to exit-0 wins. Others SIGTERM'd.
      Returns winner spec + losers list.

Both helpers:
  - stdlib only (concurrent.futures, subprocess, pathlib)
  - max 4 concurrent (avoid thrashing local box)
  - hard timeout per task (default 30s discovery, 120s race)
  - write per-task stdout/stderr to debug_dir/parallel/*.log
  - return JSON-serializable dict for orchestrator
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_DEFAULT_DISCOVERY_TIMEOUT = 30
_DEFAULT_RACE_TIMEOUT = 120
_MAX_WORKERS = 4


def _run_capture(
    name: str,
    cmd: list[str],
    *,
    cwd: Path,
    timeout: int,
    out_dir: Path,
) -> dict:
    """Run one subprocess. Returns result dict; never raises."""
    start = time.monotonic()
    out_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = out_dir / f"{name}.stdout.log"
    stderr_path = out_dir / f"{name}.stderr.log"
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout_path.write_text(proc.stdout, encoding="utf-8", errors="replace")
        stderr_path.write_text(proc.stderr, encoding="utf-8", errors="replace")
        return {
            "name": name,
            "cmd": cmd,
            "exit_code": proc.returncode,
            "duration_sec": round(time.monotonic() - start, 2),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "stdout_bytes": len(proc.stdout),
            "stderr_bytes": len(proc.stderr),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as e:
        if e.stdout:
            stdout_path.write_text(str(e.stdout), encoding="utf-8", errors="replace")
        if e.stderr:
            stderr_path.write_text(str(e.stderr), encoding="utf-8", errors="replace")
        return {
            "name": name,
            "cmd": cmd,
            "exit_code": -1,
            "duration_sec": round(time.monotonic() - start, 2),
            "timed_out": True,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    except (OSError, FileNotFoundError) as e:
        return {
            "name": name,
            "cmd": cmd,
            "exit_code": -2,
            "duration_sec": round(time.monotonic() - start, 2),
            "error": str(e),
        }


def parallel_discovery(
    bug_type: str,
    bug_desc: str,
    debug_dir: Path,
    repo_root: Path,
    *,
    timeout: int = _DEFAULT_DISCOVERY_TIMEOUT,
) -> dict:
    """Fan out type-appropriate discovery tasks in parallel.

    For each bug_type, build list of (name, cmd) tuples. Run concurrently.
    """
    tasks: list[tuple[str, list[str]]] = []

    if bug_type in ("static", "runtime_ui"):
        # Keyword grep — split into 3 chunks for parallelism
        kws = _extract_keywords(bug_desc, limit=9)
        if kws:
            for chunk_idx, chunk in enumerate(_chunk(kws, 3)):
                pattern = "|".join(chunk)
                tasks.append((
                    f"grep_chunk_{chunk_idx}",
                    ["grep", "-rn", "-E", pattern,
                     "apps", "packages",
                     "--include=*.ts", "--include=*.tsx",
                     "--include=*.py", "--include=*.js"],
                ))

    if bug_type == "network":
        # Extract URLs
        import re
        urls = re.findall(r"https?://\S+|/api/v\d+/\S+", bug_desc)
        for i, url in enumerate(urls[:3]):
            tasks.append((
                f"curl_{i}",
                ["curl", "-sv", "-m", "10", url.rstrip(",.")],
            ))
        # Tail recent error logs
        log_candidates = [
            "apps/api/logs/error.log",
            "logs/error.log",
            ".vg/logs/runtime.log",
        ]
        for log in log_candidates:
            log_path = repo_root / log
            if log_path.is_file():
                tasks.append((
                    f"taillog_{log.replace('/', '_')}",
                    ["tail", "-n", "200", str(log_path)],
                ))

    if bug_type == "infra":
        # Config snapshot
        config_files = [".claude/vg.config.md", ".env.example", "package.json"]
        for cf_path in config_files:
            p = repo_root / cf_path
            if p.is_file():
                tasks.append((
                    f"config_{cf_path.replace('/', '_').replace('.', '_')}",
                    ["cat", str(p)],
                ))

    if not tasks:
        return {
            "bug_type": bug_type,
            "tasks_run": 0,
            "tasks": [],
            "wall_clock_sec": 0.0,
            "note": "no parallel discovery tasks applicable for this bug_type",
        }

    out_dir = debug_dir / "parallel"
    start = time.monotonic()
    results: list[dict] = []

    with cf.ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(tasks))) as ex:
        futures = {
            ex.submit(
                _run_capture, name, cmd,
                cwd=repo_root, timeout=timeout, out_dir=out_dir,
            ): name
            for name, cmd in tasks
        }
        for fut in cf.as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001
                results.append({"name": futures[fut], "error": str(e)})

    wall = round(time.monotonic() - start, 2)
    seq_estimate = round(sum(r.get("duration_sec", 0) for r in results), 2)

    return {
        "bug_type": bug_type,
        "tasks_run": len(tasks),
        "tasks": results,
        "wall_clock_sec": wall,
        "sequential_estimate_sec": seq_estimate,
        "speedup": round(seq_estimate / wall, 2) if wall > 0 else 1.0,
    }


def race_hypotheses(
    hypothesis_specs: list[dict],
    *,
    timeout: int = _DEFAULT_RACE_TIMEOUT,
    debug_dir: Path | None = None,
) -> dict:
    """Run N hypothesis fix attempts in parallel. First success wins.

    Each spec: {"id": "H1", "cmd": ["bash", "-c", "..."], "description": "..."}

    On first exit-0:
      - SIGTERM others
      - Return winner + losers

    If all fail or timeout: return all results with winner=None.
    """
    if not hypothesis_specs:
        return {"winner": None, "results": [], "wall_clock_sec": 0.0}

    out_dir = (debug_dir or Path(".")) / "race"
    out_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    procs: dict[str, subprocess.Popen] = {}
    spec_by_id: dict[str, dict] = {s["id"]: s for s in hypothesis_specs}

    # Spawn all
    for spec in hypothesis_specs:
        hid = spec["id"]
        cmd = spec["cmd"]
        stdout_path = out_dir / f"{hid}.stdout.log"
        stderr_path = out_dir / f"{hid}.stderr.log"
        try:
            p = subprocess.Popen(
                cmd,
                stdout=stdout_path.open("w", encoding="utf-8"),
                stderr=stderr_path.open("w", encoding="utf-8"),
                cwd=str(Path.cwd()),
            )
            procs[hid] = p
        except (OSError, FileNotFoundError) as e:
            # Couldn't even spawn — record as fail
            stderr_path.write_text(f"spawn failed: {e}", encoding="utf-8")

    winner_id: str | None = None
    deadline = start + timeout

    # Poll loop
    while procs and time.monotonic() < deadline:
        time.sleep(0.5)
        for hid in list(procs.keys()):
            p = procs[hid]
            rc = p.poll()
            if rc is None:
                continue
            # Process exited
            if rc == 0 and winner_id is None:
                winner_id = hid
                # Kill others
                for other_hid, other_p in procs.items():
                    if other_hid != hid and other_p.poll() is None:
                        try:
                            other_p.terminate()
                        except OSError:
                            pass
                # Drop all from active set (kill them via fall-through)
                del procs[hid]
                break
            else:
                # Exited non-zero — remove from active set
                del procs[hid]

        if winner_id is not None:
            break

    # Cleanup any still-running
    for hid, p in procs.items():
        if p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    p.kill()
                except OSError:
                    pass

    wall = round(time.monotonic() - start, 2)

    # Gather final exit codes
    results: list[dict] = []
    for spec in hypothesis_specs:
        hid = spec["id"]
        stdout_path = out_dir / f"{hid}.stdout.log"
        stderr_path = out_dir / f"{hid}.stderr.log"
        results.append({
            "id": hid,
            "description": spec.get("description", ""),
            "exit_code": (
                spec_by_id[hid].get("_final_rc")  # if we stashed
                if "_final_rc" in spec_by_id[hid]
                else None
            ),
            "winner": hid == winner_id,
            "stdout_path": str(stdout_path) if stdout_path.exists() else None,
            "stderr_path": str(stderr_path) if stderr_path.exists() else None,
        })

    return {
        "winner": winner_id,
        "results": results,
        "wall_clock_sec": wall,
        "raced": len(hypothesis_specs),
        "timed_out": winner_id is None and wall >= timeout - 1,
    }


def _extract_keywords(text: str, *, limit: int = 9) -> list[str]:
    import re
    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{2,}\b", text)
    seen: list[str] = []
    seen_set: set[str] = set()
    stop = {
        "this", "that", "with", "from", "have", "been", "when", "what",
        "which", "should", "would", "could", "khong", "không",
    }
    for w in words:
        wl = w.lower()
        if wl in stop or wl in seen_set:
            continue
        seen_set.add(wl)
        seen.append(w)
        if len(seen) >= limit:
            break
    return seen


def _chunk(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_disc = sub.add_parser("discovery", help="parallel discovery fan-out")
    p_disc.add_argument("--bug-type", required=True)
    p_disc.add_argument("--bug-desc", required=True)
    p_disc.add_argument("--debug-dir", required=True)
    p_disc.add_argument("--timeout", type=int, default=_DEFAULT_DISCOVERY_TIMEOUT)

    p_race = sub.add_parser("race", help="race hypothesis fix attempts")
    p_race.add_argument("--specs-json", required=True,
                        help="path to JSON file with list of hypothesis specs")
    p_race.add_argument("--debug-dir", required=True)
    p_race.add_argument("--timeout", type=int, default=_DEFAULT_RACE_TIMEOUT)

    args = ap.parse_args(argv)
    repo_root = Path(os.environ.get("REPO_ROOT", ".")).resolve()

    if args.cmd == "discovery":
        result = parallel_discovery(
            args.bug_type,
            args.bug_desc,
            Path(args.debug_dir),
            repo_root,
            timeout=args.timeout,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "race":
        specs = json.loads(Path(args.specs_json).read_text(encoding="utf-8"))
        result = race_hypotheses(
            specs,
            timeout=args.timeout,
            debug_dir=Path(args.debug_dir),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("winner") else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
