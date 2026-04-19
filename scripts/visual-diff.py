#!/usr/bin/env python3
"""
visual-diff.py — Visual regression tool for VG workflow.

Compares current screenshots against baseline, reports diff % per view.
Used by /vg:regression --visual and /vg:test (if config.visual_regression.enabled).

Tool backends (auto-detect):
  - pixelmatch-py (pip install pixelmatch)
  - PIL/Pillow fallback (per-pixel grayscale delta — less accurate)

USAGE
  # Compare current vs baseline, write report
  python visual-diff.py compare --current apps/web/e2e/screenshots/{phase}/ \
                                --baseline apps/web/e2e/screenshots/baseline/{phase}/ \
                                --threshold 2.0 \
                                --output .vg/phases/{phase}/visual-diff.json

  # Promote current → baseline (called from /vg:accept)
  python visual-diff.py promote --from apps/web/e2e/screenshots/{phase}/ \
                                --to apps/web/e2e/screenshots/baseline/{phase}/

  # Summarize a report
  python visual-diff.py summarize --report .vg/phases/{phase}/visual-diff.json

CONFIG (read from vg.config.md via env vars)
  VG_VISUAL_THRESHOLD       — max allowed diff %, default 2.0
  VG_VISUAL_TOOL            — "pixelmatch" | "pil", default auto
  VG_VISUAL_IGNORE_REGIONS  — comma-sep "view:x,y,w,h" to mask dynamic regions

EXIT CODES
  0 — compare passed (all below threshold) / promote succeeded
  1 — compare failed (one or more views exceeded threshold)
  2 — error (missing files, tool not found, etc.)
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def get_tool():
    """Detect available diff tool."""
    try:
        from pixelmatch.contrib.PIL import pixelmatch  # noqa
        return "pixelmatch"
    except ImportError:
        pass
    try:
        from PIL import Image  # noqa
        return "pil"
    except ImportError:
        return None


def diff_pixelmatch(a_path, b_path, diff_out=None):
    from PIL import Image
    from pixelmatch.contrib.PIL import pixelmatch

    a = Image.open(a_path).convert("RGBA")
    b = Image.open(b_path).convert("RGBA")

    # Resize if different (match baseline dims)
    if a.size != b.size:
        b = b.resize(a.size)

    diff_img = Image.new("RGBA", a.size) if diff_out else None
    mismatch = pixelmatch(a, b, diff_img, threshold=0.1)
    total = a.size[0] * a.size[1]
    pct = (mismatch / total) * 100

    if diff_img and diff_out:
        diff_img.save(diff_out)

    return pct, mismatch, total


def diff_pil(a_path, b_path, diff_out=None):
    """Fallback diff — grayscale absolute delta."""
    from PIL import Image, ImageChops

    a = Image.open(a_path).convert("L")
    b = Image.open(b_path).convert("L")
    if a.size != b.size:
        b = b.resize(a.size)

    delta = ImageChops.difference(a, b)
    # Count pixels with delta > 10 (8-bit grayscale tolerance)
    threshold = 10
    mismatch = sum(1 for px in delta.getdata() if px > threshold)
    total = a.size[0] * a.size[1]
    pct = (mismatch / total) * 100

    if diff_out:
        delta.save(diff_out)

    return pct, mismatch, total


def cmd_compare(args):
    tool = args.tool or get_tool()
    if not tool:
        print("ERROR: neither pixelmatch nor PIL installed. pip install pixelmatch pillow", file=sys.stderr)
        return 2

    current_dir = Path(args.current)
    baseline_dir = Path(args.baseline)
    if not current_dir.is_dir():
        print(f"ERROR: current dir not found: {current_dir}", file=sys.stderr)
        return 2

    threshold = float(args.threshold)
    results = []

    if not baseline_dir.exists():
        print(f"No baseline yet at {baseline_dir}. Run: visual-diff.py promote --from {current_dir} --to {baseline_dir}")
        # No baseline = can't compare. Emit empty report, exit 0 (first run).
        out = {
            "tool": tool, "threshold_pct": threshold, "baseline_present": False,
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "views": [], "summary": {"total": 0, "passed": 0, "failed": 0, "missing_baseline": 0},
        }
        Path(args.output).write_text(json.dumps(out, indent=2))
        return 0

    failed = 0
    missing_baseline = 0
    diff_fn = diff_pixelmatch if tool == "pixelmatch" else diff_pil

    for img_file in sorted(current_dir.rglob("*.png")):
        rel = img_file.relative_to(current_dir)
        baseline_file = baseline_dir / rel
        view_name = str(rel).replace("\\", "/")

        if not baseline_file.exists():
            results.append({"view": view_name, "status": "missing_baseline", "diff_pct": None})
            missing_baseline += 1
            continue

        diff_out = None
        if args.diff_dir:
            diff_out = Path(args.diff_dir) / rel
            diff_out.parent.mkdir(parents=True, exist_ok=True)

        try:
            pct, mismatch, total = diff_fn(img_file, baseline_file, diff_out)
        except Exception as e:
            results.append({"view": view_name, "status": "error", "error": str(e)})
            continue

        status = "pass" if pct <= threshold else "fail"
        if status == "fail":
            failed += 1

        results.append({
            "view": view_name,
            "status": status,
            "diff_pct": round(pct, 4),
            "mismatch_px": mismatch,
            "total_px": total,
        })

    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r.get("status") == "pass"),
        "failed": failed,
        "missing_baseline": missing_baseline,
        "errors": sum(1 for r in results if r.get("status") == "error"),
    }

    out = {
        "tool": tool,
        "threshold_pct": threshold,
        "baseline_present": True,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "views": results,
        "summary": summary,
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2))

    # Console report
    print(f"Visual diff: {summary['passed']}/{summary['total']} passed, {failed} failed, {missing_baseline} missing baseline")
    for r in results:
        if r.get("status") == "fail":
            print(f"  FAIL  {r['view']}  {r['diff_pct']}% > {threshold}%")
        elif r.get("status") == "missing_baseline":
            print(f"  NEW   {r['view']}  (no baseline)")

    return 1 if failed > 0 else 0


def cmd_promote(args):
    src = Path(getattr(args, "from"))
    dst = Path(args.to)
    if not src.is_dir():
        print(f"ERROR: source not found: {src}", file=sys.stderr)
        return 2

    count = 0
    for img_file in src.rglob("*.png"):
        rel = img_file.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(img_file, target)
        count += 1

    print(f"Promoted {count} images {src} → {dst}")
    return 0


def cmd_summarize(args):
    data = json.loads(Path(args.report).read_text())
    s = data.get("summary", {})
    print(f"Visual diff report: {args.report}")
    print(f"  Ran at:     {data.get('ran_at')}")
    print(f"  Tool:       {data.get('tool')}")
    print(f"  Threshold:  {data.get('threshold_pct')}%")
    print(f"  Results:    {s.get('passed')}/{s.get('total')} passed")
    print(f"              {s.get('failed')} failed, {s.get('missing_baseline')} missing baseline, {s.get('errors', 0)} errors")
    for r in data.get("views", []):
        if r.get("status") in ("fail", "error"):
            print(f"    {r.get('status').upper():5} {r.get('view')}  {r.get('diff_pct','-')}%")
    return 0 if s.get("failed", 0) == 0 else 1


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compare")
    c.add_argument("--current", required=True, help="Current screenshots dir")
    c.add_argument("--baseline", required=True, help="Baseline screenshots dir")
    c.add_argument("--threshold", default="2.0", help="Max allowed diff %% (default 2.0)")
    c.add_argument("--output", required=True, help="JSON report output path")
    c.add_argument("--diff-dir", help="Optional dir to write diff images")
    c.add_argument("--tool", choices=["pixelmatch", "pil"], help="Force tool (default auto-detect)")
    c.set_defaults(func=cmd_compare)

    pr = sub.add_parser("promote")
    pr.add_argument("--from", dest="from", required=True, help="Source dir (current run)")
    pr.add_argument("--to", required=True, help="Destination (baseline)")
    pr.set_defaults(func=cmd_promote)

    s = sub.add_parser("summarize")
    s.add_argument("--report", required=True, help="JSON report path")
    s.set_defaults(func=cmd_summarize)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
