#!/usr/bin/env python3
"""
design-reverse.py — Phase 20 Wave C D-14.

Capture mockup PNGs from a live URL via headless Playwright. Reverse of
/vg:design-scaffold: scaffold creates mockups for greenfield; reverse
captures from existing live UI for projects migrating to VG workflow.

Use case: project already deployed at https://app.example.com/, no
Pencil/Figma source files exist, but team wants to enable Phase 19
L1-L6 gates. Run /vg:design-reverse → captures /, /sites, /users etc.
as PNG mockups → drops into design_assets.paths/ → /vg:design-extract
processes them → existing Form A flow engages.

USAGE
  python design-reverse.py \
    --base-url https://app.example.com \
    --routes /,/sites,/users,/settings \
    --output-dir designs \
    [--cookies cookies.json]   # for authenticated pages
    [--viewport 1440x900]
    [--full-page]              # full-page screenshot vs viewport-only

OUTPUT
  <output-dir>/{slug}.png — viewport screenshot per route
  <output-dir>/.reverse-evidence/{slug}.json — capture metadata

EXIT
  0 — all routes captured
  1 — one or more failed (Node/Playwright missing or render errors)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def slugify_route(route: str) -> str:
    """Convert URL path to filesystem-safe kebab-case slug."""
    # /sites/123/edit → sites-123-edit
    s = route.strip("/").lower() or "home"
    s = re.sub(r"[^a-z0-9_/-]", "-", s)
    s = re.sub(r"/+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "home"


def capture_via_playwright(
    url: str, output_png: Path, viewport: tuple[int, int], full_page: bool, cookies: list[dict] | None
) -> tuple[bool, str]:
    """Spawn `node` + Playwright to capture a single URL."""
    cookies_json = json.dumps(cookies) if cookies else "[]"
    js = f"""
    const {{ chromium }} = require('playwright');
    (async () => {{
      const browser = await chromium.launch();
      const ctx = await browser.newContext({{
        viewport: {{ width: {viewport[0]}, height: {viewport[1]} }}
      }});
      const cookies = {cookies_json};
      if (cookies.length) await ctx.addCookies(cookies);
      const page = await ctx.newPage();
      await page.goto('{url}', {{ waitUntil: 'networkidle', timeout: 20000 }});
      await page.waitForTimeout(800);
      await page.screenshot({{
        path: '{output_png.as_posix()}',
        fullPage: {('true' if full_page else 'false')}
      }});
      await browser.close();
    }})().catch(e => {{ console.error(e.message); process.exit(2); }});
    """
    try:
        r = subprocess.run(
            ["node", "-e", js], capture_output=True, timeout=60, text=True
        )
    except FileNotFoundError:
        return False, "node not on PATH"
    except subprocess.TimeoutExpired:
        return False, f"playwright timed out (>60s) for {url}"
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        if "Cannot find module 'playwright'" in msg:
            return False, "Playwright not installed (npm i -D playwright)"
        if "Executable doesn't exist" in msg:
            return False, "Playwright browsers missing (npx playwright install chromium)"
        return False, f"render failed: {msg[:200]}"
    return output_png.exists(), "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="https://app.example.com (no trailing slash)")
    ap.add_argument("--routes", required=True, help="Comma-sep paths (e.g. /,/sites,/users)")
    ap.add_argument("--output-dir", default="designs")
    ap.add_argument("--cookies", default=None, help="Path to JSON cookies file (Playwright format)")
    ap.add_argument("--viewport", default="1440x900")
    ap.add_argument("--full-page", action="store_true")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    if not shutil.which("node"):
        print(json.dumps({"verdict": "BLOCK", "reason": "node CLI not on PATH"}))
        return 1

    try:
        vw, vh = (int(x) for x in args.viewport.lower().split("x", 1))
    except ValueError:
        print(json.dumps({"verdict": "BLOCK", "reason": f"invalid --viewport: {args.viewport}"}))
        return 1

    cookies = None
    if args.cookies and Path(args.cookies).exists():
        try:
            cookies = json.loads(Path(args.cookies).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"verdict": "BLOCK", "reason": f"cookies parse error: {exc}"}))
            return 1

    output_dir = Path(args.output_dir)
    evidence_dir = output_dir / ".reverse-evidence"
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    base = args.base_url.rstrip("/")
    routes = [r.strip() for r in args.routes.split(",") if r.strip()]
    if not routes:
        print(json.dumps({"verdict": "BLOCK", "reason": "no routes provided"}))
        return 1

    captured: list[dict] = []
    failed: list[dict] = []
    for route in routes:
        slug = slugify_route(route)
        url = base + (route if route.startswith("/") else "/" + route)
        png_path = output_dir / f"{slug}.png"
        print(f"  → {slug}: {url}")
        ok, msg = capture_via_playwright(url, png_path, (vw, vh), args.full_page, cookies)
        if ok:
            captured.append({"slug": slug, "url": url, "png": str(png_path)})
            (evidence_dir / f"{slug}.json").write_text(
                json.dumps(
                    {
                        "slug": slug,
                        "url": url,
                        "png": str(png_path),
                        "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
                        "viewport": [vw, vh],
                        "full_page": args.full_page,
                        "tool": "design-reverse",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        else:
            failed.append({"slug": slug, "url": url, "reason": msg})
            print(f"    ✗ {msg}")

    result = {
        "verdict": "PASS" if not failed else "PARTIAL",
        "captured": captured,
        "failed": failed,
        "output_dir": str(output_dir),
        "total": len(routes),
    }
    if args.report:
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
