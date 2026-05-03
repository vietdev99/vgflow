#!/usr/bin/env python3
"""
verify-build-visual.py — L3 build-time visual gate (per task).

After an executor commits a UI task, render the live UI via headless
Playwright and pixel-diff against the design baseline PNG. Drift past
threshold = BLOCK; orchestrator can re-spawn executor with reminder.

Skip behaviour (NEVER block on these):
  - dev server not reachable at server-url            → SKIP
  - Node + Playwright not installed                    → SKIP
  - baseline PNG missing for the slug                  → SKIP
  - PIL / pixelmatch not installed                     → SKIP

Skips emit a verdict so the orchestrator can log "L3 not exercised" rather
than silently passing. Only a real diff > threshold triggers BLOCK.

USAGE
  python verify-build-visual.py \
    --phase-dir .vg/phases/07.10-... \
    --task-num 4 \
    --slug sites-list \
    --route /sites \
    [--design-dir .vg/design-normalized] \
    [--server-url http://localhost:3000] \
    [--threshold-pct 5.0] \
    [--viewport 1440x900] \
    --output report.json

EXIT
  0 — PASS or SKIP
  1 — BLOCK (diff > threshold)
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent / "lib"))
from design_ref_resolver import first_screenshot, resolve_design_assets  # noqa: E402


def server_up(url: str, timeout: float = 3.0) -> bool:
    parsed = urlparse(url)
    host, port = parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except (OSError, socket.timeout):
        return False
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        # Non-2xx is still a live server (auth wall, SPA returning 401, etc.).
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def render_via_playwright(url: str, output_png: Path, viewport: tuple[int, int]) -> tuple[bool, str]:
    """Spawn `node` + Playwright to capture a screenshot. Return (ok, message)."""
    js = (
        "const{chromium}=require('playwright');"
        "(async()=>{"
        "const b=await chromium.launch();"
        f"const c=await b.newContext({{viewport:{{width:{viewport[0]},height:{viewport[1]}}}}});"
        "const p=await c.newPage();"
        f"await p.goto('{url}',{{waitUntil:'networkidle',timeout:15000}});"
        "await p.waitForTimeout(500);"
        f"await p.screenshot({{path:'{output_png.as_posix()}',fullPage:false}});"
        "await b.close();"
        "})().catch(e=>{console.error(e.message);process.exit(2);});"
    )
    try:
        r = subprocess.run(
            ["node", "-e", js],
            capture_output=True,
            timeout=45,
            text=True,
        )
    except FileNotFoundError:
        return False, "node not installed"
    except subprocess.TimeoutExpired:
        return False, "playwright render timed out (>45s)"
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        if "Cannot find module 'playwright'" in msg:
            return False, "Playwright npm package not installed (npm i -D playwright)"
        if "browserType.launch" in msg or "Executable doesn't exist" in msg:
            return False, "Playwright browsers not installed (npx playwright install chromium)"
        return False, f"playwright render failed: {msg[:200]}"
    return output_png.exists(), "ok"


def pixel_diff(current: Path, baseline: Path, diff_path: Path) -> tuple[float, str]:
    try:
        from PIL import Image
        from pixelmatch.contrib.PIL import pixelmatch
    except ImportError:
        return -1.0, "pixelmatch+PIL not installed (pip install pixelmatch pillow)"
    try:
        a = Image.open(current).convert("RGBA")
        b = Image.open(baseline).convert("RGBA")
        if a.size != b.size:
            b = b.resize(a.size)
        diff_img = Image.new("RGBA", a.size)
        mismatch = pixelmatch(a, b, diff_img, threshold=0.1)
        total = a.size[0] * a.size[1]
        pct = (mismatch / total) * 100 if total else 0.0
        diff_img.save(diff_path)
        return pct, "ok"
    except Exception as exc:  # pragma: no cover — defensive
        return -1.0, f"pixel-diff error: {type(exc).__name__}: {exc}"


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
    ap.add_argument("--route", default="/")
    ap.add_argument("--design-dir", default=".vg/design-normalized")
    ap.add_argument("--server-url", default=os.environ.get("VG_DEV_SERVER_URL", "http://localhost:3000"))
    ap.add_argument("--threshold-pct", type=float, default=5.0)
    ap.add_argument("--viewport", default="1440x900")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    try:
        vw, vh = (int(x) for x in args.viewport.lower().split("x", 1))
    except ValueError:
        print(f"⛔ invalid --viewport '{args.viewport}' (expect WIDTHxHEIGHT)", file=sys.stderr)
        return 2

    phase_dir = Path(args.phase_dir)
    repo_root = Path.cwd().resolve()
    design_dir = Path(args.design_dir)
    if not design_dir.is_absolute():
        design_dir = (repo_root / design_dir).resolve()
    baseline = first_screenshot(
        resolve_design_assets(
            args.slug,
            repo_root=repo_root,
            phase_dir=phase_dir,
            explicit_design_dir=design_dir,
        )
    )
    if baseline is None:
        baseline = design_dir / "screenshots" / f"{args.slug}.default.png"

    result: dict = {
        "task": args.task_num,
        "slug": args.slug,
        "route": args.route,
        "viewport": [vw, vh],
        "verdict": "SKIP",
    }

    if not baseline.exists():
        result["reason"] = f"baseline missing: {baseline}"
        return emit(result, args.output)

    full_url = args.server_url.rstrip("/") + (
        args.route if args.route.startswith("/") else "/" + args.route
    )
    if not server_up(args.server_url):
        result["reason"] = f"dev server not up at {args.server_url} — start it before /vg:build for L3 to engage"
        result["url"] = full_url
        return emit(result, args.output)

    out_dir = phase_dir / "build-visual" / f"task-{args.task_num}"
    out_dir.mkdir(parents=True, exist_ok=True)
    current_png = out_dir / f"{args.slug}.current.png"
    diff_png = out_dir / f"{args.slug}.diff.png"

    ok, msg = render_via_playwright(full_url, current_png, (vw, vh))
    if not ok:
        result["reason"] = msg
        result["url"] = full_url
        return emit(result, args.output)

    pct, msg = pixel_diff(current_png, baseline, diff_png)
    if pct < 0:
        result["reason"] = msg
        return emit(result, args.output)

    result["url"] = full_url
    result["current_image"] = str(current_png)
    result["baseline_image"] = str(baseline)
    result["diff_image"] = str(diff_png)
    result["diff_pct"] = round(pct, 3)
    result["threshold_pct"] = args.threshold_pct
    if pct <= args.threshold_pct:
        result["verdict"] = "PASS"
    else:
        result["verdict"] = "BLOCK"
        result["reason"] = (
            f"pixel diff {pct:.2f}% > threshold {args.threshold_pct}% — UI does not match design PNG"
        )
    return emit(result, args.output)


if __name__ == "__main__":
    sys.exit(main())
