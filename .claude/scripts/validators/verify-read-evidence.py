#!/usr/bin/env python3
"""
verify-read-evidence.py — P19 D-09 sentinel-with-hash forcing function.

After /vg:build executor commits a UI task, verify the executor wrote a
sentinel file at ${PHASE_DIR}/.read-evidence/task-${N}.json declaring
which PNGs it Read, with the SHA256 of each PNG at read time. Validator
re-hashes the same PNGs and BLOCKs on mismatch — a model fabricating
the sentinel without actually Reading the file would have to know the
exact SHA256 (search space 2^256), which it cannot.

This is the strongest gate available without runtime hook surface for
direct subagent transcript inspection (see RESEARCH.md). Probabilistic
proof: PASS = either Read happened OR cryptographic clairvoyance.

Required sentinel schema:
  {
    "task": <int>,
    "slug": "<design-ref slug>",
    "read_paths": [
      {"path": "<absolute path>", "sha256_at_read": "<64 hex>"},
      ...
    ],
    "read_at": "<ISO 8601 UTC>"
  }

USAGE
  python verify-read-evidence.py \
    --phase-dir .vg/phases/07.10-... \
    --task-num 4 \
    --slug home-dashboard \
    --design-dir .vg/design-normalized \
    [--require true|false] \
    [--output report.json]

EXIT
  0 — PASS or SKIP (no <design-ref> slug, or require=false + sentinel missing)
  1 — BLOCK (missing while required, missing required PNG path, or SHA256 mismatch)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from design_ref_resolver import first_screenshot, resolve_design_assets  # noqa: E402

SHA256_RE = re.compile(r"^[a-f0-9]{64}$", re.IGNORECASE)


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def emit(result: dict, output: str | None) -> int:
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if output:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if result["verdict"] in ("PASS", "SKIP") else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--task-num", type=int, required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--design-dir", default=".vg/design-normalized")
    ap.add_argument("--require", default="true", choices=["true", "false"])
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    repo_root = Path.cwd().resolve()
    design_dir = Path(args.design_dir)
    if not design_dir.is_absolute():
        design_dir = (repo_root / design_dir).resolve()

    sentinel = phase_dir / ".read-evidence" / f"task-{args.task_num}.json"
    expected_png = first_screenshot(
        resolve_design_assets(
            args.slug,
            repo_root=repo_root,
            phase_dir=phase_dir,
            explicit_design_dir=design_dir,
        )
    )
    if expected_png is None:
        expected_png = design_dir / "screenshots" / f"{args.slug}.default.png"

    result: dict = {
        "phase": str(phase_dir.name),
        "task": args.task_num,
        "slug": args.slug,
        "sentinel_path": str(sentinel),
        "expected_png": str(expected_png),
        "verdict": "SKIP",
        "mismatches": [],
    }

    if not expected_png.exists():
        result["reason"] = f"baseline PNG missing at {expected_png} — L1 gate should have caught earlier"
        return emit(result, args.output)

    if not sentinel.exists():
        if args.require == "false":
            result["reason"] = "sentinel not required for this task"
            return emit(result, args.output)
        result["verdict"] = "BLOCK"
        result["reason"] = (
            f"executor did not write {sentinel.name} after Read PNG — D-09 forcing function failed"
        )
        return emit(result, args.output)

    try:
        data = json.loads(sentinel.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result["verdict"] = "BLOCK"
        result["reason"] = f"sentinel parse error: {type(exc).__name__}: {exc}"
        return emit(result, args.output)

    declared_paths = data.get("read_paths") or []
    if not isinstance(declared_paths, list):
        result["verdict"] = "BLOCK"
        result["reason"] = "sentinel.read_paths must be an array"
        return emit(result, args.output)

    declared_normalised: list[dict] = []
    for entry in declared_paths:
        if isinstance(entry, dict):
            declared_normalised.append({
                "path": str(entry.get("path") or "").strip(),
                "sha256": str(entry.get("sha256_at_read") or "").strip().lower(),
            })

    expected_sha = file_sha256(expected_png)
    expected_path_str = str(expected_png)
    expected_path_norm = expected_path_str.replace("\\", "/")

    matched_required = False
    for entry in declared_normalised:
        ep = entry["path"].replace("\\", "/")
        if ep == expected_path_norm or Path(entry["path"]).resolve() == expected_png.resolve():
            matched_required = True
            if not SHA256_RE.match(entry["sha256"]):
                result["mismatches"].append(
                    {"path": entry["path"], "issue": "sha256 missing or malformed"}
                )
            elif entry["sha256"].lower() != (expected_sha or "").lower():
                result["mismatches"].append(
                    {
                        "path": entry["path"],
                        "issue": "sha256 mismatch — sentinel claim differs from disk",
                        "declared": entry["sha256"],
                        "actual": expected_sha,
                    }
                )

    if not matched_required:
        result["verdict"] = "BLOCK"
        result["reason"] = (
            f"required PNG {expected_png.name} not in sentinel.read_paths — executor did not Read it"
        )
        result["declared_paths"] = [e["path"] for e in declared_normalised]
        return emit(result, args.output)

    if result["mismatches"]:
        result["verdict"] = "BLOCK"
        result["reason"] = f"{len(result['mismatches'])} sha256 issue(s) — likely fabricated sentinel"
        return emit(result, args.output)

    result["verdict"] = "PASS"
    result["expected_sha256"] = expected_sha
    return emit(result, args.output)


if __name__ == "__main__":
    sys.exit(main())
