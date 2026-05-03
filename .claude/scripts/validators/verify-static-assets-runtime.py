#!/usr/bin/env python3
"""Runtime static asset sanity probe.

This catches a class of UI failures that static code review cannot prove:
the built app links a stylesheet, but the live server returns HTML/JS/source
code instead of CSS. Browsers then drop or mis-handle the stylesheet and the
visual review fails downstream.

The validator auto-skips when no target URL is configured. When a target URL is
provided, CSS assets are a hard correctness property:

  - linked stylesheet must be reachable (2xx/3xx)
  - Content-Type must be text/css
  - body must not look like HTML/JS/TS source

Usage:
  verify-static-assets-runtime.py --target-url http://localhost:3000
  VG_TARGET_URL=http://localhost:3000 verify-static-assets-runtime.py --phase 7.14
"""
from __future__ import annotations

import argparse
import html.parser
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, timer  # noqa: E402


CSS_CONTENT_TYPES = {
    "text/css",
}

CSS_SOURCE_SMELLS = [
    re.compile(r"^\s*<!doctype\b", re.IGNORECASE),
    re.compile(r"^\s*<html\b", re.IGNORECASE),
    re.compile(r"^\s*<script\b", re.IGNORECASE),
    re.compile(r"^\s*(?:import|export)\s+(?!url\s*\()", re.IGNORECASE),
    re.compile(r"\bfrom\s+['\"][^'\"]+['\"]"),
    re.compile(r"\b(?:const|let|var|function|class)\s+[A-Za-z_$][\w$]*"),
    re.compile(r"\bReact\b|\bcreateElement\b|\bjsx\b", re.IGNORECASE),
]


@dataclass
class FetchResult:
    ok: bool
    url: str
    status: int | None = None
    headers: dict[str, str] | None = None
    body: bytes = b""
    error: str | None = None


class AssetParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stylesheets: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "link":
            rel = {x.strip().lower() for x in attr.get("rel", "").split()}
            href = attr.get("href", "").strip()
            if "stylesheet" in rel and href:
                self.stylesheets.append(href)
        elif tag.lower() == "script":
            src = attr.get("src", "").strip()
            if src:
                self.scripts.append(src)


def _fetch(url: str, timeout: float, max_bytes: int) -> FetchResult:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "vgflow-static-assets-runtime/1.0",
                "Accept": "text/css,text/html,application/javascript,*/*;q=0.1",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(max_bytes)
            return FetchResult(
                ok=True,
                url=url,
                status=resp.status,
                headers={k.lower(): v for k, v in resp.headers.items()},
                body=body,
            )
    except urllib.error.HTTPError as exc:
        body = exc.read(max_bytes) if exc.fp else b""
        return FetchResult(
            ok=True,
            url=url,
            status=exc.code,
            headers={k.lower(): v for k, v in (exc.headers or {}).items()},
            body=body,
        )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return FetchResult(ok=False, url=url, error=str(exc))


def _content_type(headers: dict[str, str] | None) -> str:
    raw = (headers or {}).get("content-type", "")
    return raw.split(";", 1)[0].strip().lower()


def _decode_sample(body: bytes) -> str:
    return body[:4096].decode("utf-8", errors="replace")


def _looks_like_source_or_html(body: bytes) -> str | None:
    sample = _decode_sample(body)
    for pattern in CSS_SOURCE_SMELLS:
        if pattern.search(sample):
            return pattern.pattern
    return None


def _is_css_path(url: str) -> bool:
    return urllib.parse.urlparse(url).path.lower().endswith(".css")


def _page_urls(base: str, paths: str) -> list[str]:
    out: list[str] = []
    base = base.rstrip("/") + "/"
    for raw in paths.split(","):
        p = raw.strip()
        if not p:
            continue
        out.append(urllib.parse.urljoin(base, p.lstrip("/")))
    return out or [base]


def main() -> None:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--phase", help="Ignored; orchestrator passes it to every validator")
    parser.add_argument("--target-url", default=os.environ.get("VG_TARGET_URL"))
    parser.add_argument("--paths", default=os.environ.get("VG_ASSET_PROBE_PATHS", "/"))
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--max-assets", type=int, default=30)
    parser.add_argument("--max-bytes", type=int, default=128 * 1024)
    args = parser.parse_args()

    out = Output(validator="verify-static-assets-runtime")
    with timer(out):
        if not args.target_url:
            out.evidence.append(Evidence(
                type="runtime_probe_skipped",
                message="No target URL configured; set VG_TARGET_URL after starting/deploying the app.",
            ))
            emit_and_exit(out)

        pages = _page_urls(args.target_url, args.paths)
        stylesheet_urls: list[str] = []

        for page_url in pages:
            page = _fetch(page_url, args.timeout, args.max_bytes)
            if not page.ok or not page.status or page.status >= 400:
                out.add(Evidence(
                    type="page_unreachable",
                    message=f"Cannot fetch page for asset probe: {page_url}",
                    actual=page.error or page.status,
                    fix_hint="Start the app and set VG_TARGET_URL to the live web origin.",
                ))
                continue

            parser_obj = AssetParser()
            parser_obj.feed(page.body.decode("utf-8", errors="replace"))
            for href in parser_obj.stylesheets:
                stylesheet_urls.append(urllib.parse.urljoin(page_url, href))

        # Stable de-dupe, cap fan-out to keep runtime bounded.
        stylesheet_urls = list(dict.fromkeys(stylesheet_urls))[:max(args.max_assets, 0)]

        if not stylesheet_urls and out.verdict == "PASS":
            out.warn(Evidence(
                type="no_stylesheet_links_found",
                message=(
                    "No <link rel=\"stylesheet\"> assets found on probed page(s). "
                    "CSS-in-JS apps may be valid, but stylesheet MIME cannot be verified."
                ),
            ))
            emit_and_exit(out)

        for css_url in stylesheet_urls:
            resp = _fetch(css_url, args.timeout, args.max_bytes)
            if not resp.ok or not resp.status or resp.status >= 400:
                out.add(Evidence(
                    type="stylesheet_unreachable",
                    message=f"Stylesheet did not return a successful response: {css_url}",
                    actual=resp.error or resp.status,
                    expected="2xx/3xx response with Content-Type: text/css",
                ))
                continue

            ctype = _content_type(resp.headers)
            if ctype not in CSS_CONTENT_TYPES:
                out.add(Evidence(
                    type="stylesheet_wrong_content_type",
                    message=f"Stylesheet URL is not served as CSS: {css_url}",
                    actual=ctype or "(missing Content-Type)",
                    expected="text/css",
                    fix_hint=(
                        "Fix static asset routing/build output. A CSS URL returning "
                        "HTML, JS, TS, or source text breaks visual rendering."
                    ),
                ))

            source_smell = _looks_like_source_or_html(resp.body)
            if source_smell:
                out.add(Evidence(
                    type="stylesheet_body_not_css",
                    message=f"Stylesheet body looks like HTML/JS/source instead of CSS: {css_url}",
                    actual=source_smell,
                    expected="CSS declarations, @rules, or CSS comments",
                    fix_hint=(
                        "Inspect the asset route. Common causes: SPA fallback catches "
                        "*.css, dev server serves source files, or build output path is wrong."
                    ),
                ))

            if _is_css_path(css_url) and not resp.body.strip():
                out.add(Evidence(
                    type="stylesheet_empty",
                    message=f"Stylesheet response is empty: {css_url}",
                    expected="non-empty CSS response",
                ))

        if out.verdict == "PASS":
            out.evidence.append(Evidence(
                type="static_assets_ok",
                message=f"Verified {len(stylesheet_urls)} stylesheet asset(s) as text/css.",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
