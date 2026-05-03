#!/usr/bin/env python3
"""
verify-vision-self-verify.py — P19 D-05 design-fidelity-guard (Lớp 5).

Spawns a fresh Haiku subagent with zero parent context to compare a UI
commit diff against the design PNG at semantic-component level. Catches
drift that pixel-diff (L3/L4) and fingerprint validator (L2) miss:
"correct grid count, wrong components in the cells".

Pattern: same as rationalization-guard.md — separate-model adjudication
to avoid echo chamber.

USAGE
  python verify-vision-self-verify.py \
    --phase-dir .vg/phases/07.10-... \
    --task-num 4 \
    --slug home-dashboard \
    --commit-sha HEAD \
    [--design-dir .vg/design-normalized] \
    [--model claude-haiku-4-5-20251001] \
    [--timeout 30] \
    [--output report.json]

EXIT
  0 — PASS, FLAG, or SKIP (skip never blocks)
  1 — BLOCK
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from design_ref_resolver import first_screenshot, resolve_design_assets  # noqa: E402

CORE_COMPONENTS = {"sidebar", "topbar", "header", "maincontent", "appshell", "navigation"}
FE_PATH_PATTERN = (".tsx", ".jsx", ".vue", ".svelte")


def emit(result: dict, output: str | None) -> int:
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if output:
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if result["verdict"] in ("PASS", "FLAG", "SKIP") else 1


def get_fe_diff(commit_sha: str, max_chars: int = 4000) -> tuple[str, list[str]]:
    """Return (truncated diff text, list of FE files)."""
    try:
        files = subprocess.run(
            ["git", "show", "--name-only", "--pretty=", commit_sha],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "", []
    fe_files = [
        line.strip()
        for line in files.stdout.splitlines()
        if line.strip() and line.strip().endswith(FE_PATH_PATTERN)
    ]
    if not fe_files:
        return "", []
    try:
        diff = subprocess.run(
            ["git", "show", commit_sha, "--"] + fe_files,
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return "", fe_files
    text = diff.stdout
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... [truncated, full diff is {len(diff.stdout)} chars]"
    return text, fe_files


def extract_view_components_row(view_components_md: Path, slug: str) -> str:
    if not view_components_md.exists():
        return ""
    text = view_components_md.read_text(encoding="utf-8", errors="ignore")
    # Find ## {slug} section
    lines = text.splitlines()
    in_slug = False
    rows: list[str] = []
    for line in lines:
        if line.strip().startswith("## "):
            in_slug = line.strip()[3:].strip().lower() == slug.lower()
            continue
        if in_slug and line.strip().startswith("|"):
            rows.append(line)
    return "\n".join(rows)


def build_prompt(slug: str, png_path: Path, diff_text: str, view_components: str, fe_files: list[str]) -> str:
    components_block = (
        view_components
        if view_components
        else "(no VIEW-COMPONENTS.md row for this slug — adjudicate from PNG alone)"
    )
    return textwrap.dedent(f"""
        You are an isolated design-fidelity adjudicator. You have no context about the
        author of this code or what they intended. Your sole job: compare the design
        PNG attached to this conversation against the git diff below, and decide
        whether the code ships the components the PNG shows.

        Design PNG: {png_path.name}  (already attached)
        Slug: {slug}
        FE files in commit: {", ".join(fe_files) or "(none)"}

        Expected components (from VIEW-COMPONENTS.md if available):
        ```
        {components_block}
        ```

        Git diff (FE files only, truncated to 4KB):
        ```
        {diff_text or "(empty diff)"}
        ```

        Task: identify components VISIBLE IN THE PNG (Sidebar, TopBar, MainContent,
        cards, panels, navigation, footer, etc. — semantic names, never "div" or
        "Container"). For each expected component, decide if it appears in the diff
        (by tag, className, role, or distinctive text). A component "appears" if any
        of: JSX tag named after it (e.g. `<Sidebar>`), className containing its name
        (e.g. `className="sidebar"`), ARIA role matching, or text label visible in
        both PNG and diff.

        Output STRICT single-line JSON, no prose, no code fences:

        {{"verdict":"PASS|FLAG|BLOCK","reason":"<= 200 chars","missing_components":["Name1","Name2"],"confidence":"low|medium|high"}}

        Rules:
        - PASS: every component visible in PNG appears in diff.
        - FLAG: 1-2 minor components missing (e.g. footer divider, decorative badge).
        - BLOCK: 3+ missing OR core component (Sidebar, TopBar, MainContent, AppShell)
          missing. Core means a layout-defining region.
        - confidence high only if VIEW-COMPONENTS.md row was provided AND diff is
          well-structured. medium if PNG-only adjudication. low if diff is opaque.
    """).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--task-num", type=int, required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--commit-sha", default="HEAD")
    ap.add_argument("--design-dir", default=".vg/design-normalized")
    ap.add_argument("--model", default=os.environ.get("VG_VISION_GUARD_MODEL", "claude-haiku-4-5-20251001"))
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    repo_root = Path.cwd().resolve()
    design_dir = Path(args.design_dir)
    if not design_dir.is_absolute():
        design_dir = (repo_root / design_dir).resolve()

    png_path = first_screenshot(
        resolve_design_assets(
            args.slug,
            repo_root=repo_root,
            phase_dir=phase_dir,
            explicit_design_dir=design_dir,
        )
    )
    if png_path is None:
        png_path = design_dir / "screenshots" / f"{args.slug}.default.png"

    result: dict = {
        "phase": str(phase_dir.name),
        "task": args.task_num,
        "slug": args.slug,
        "commit_sha": args.commit_sha,
        "verdict": "SKIP",
        "missing_components": [],
        "confidence": "low",
    }

    if not png_path.exists():
        result["reason"] = f"baseline PNG missing: {png_path}"
        return emit(result, args.output)

    if not shutil.which("claude"):
        result["reason"] = "claude CLI not on PATH — design-fidelity-guard requires it for separate-model adjudication"
        return emit(result, args.output)

    diff_text, fe_files = get_fe_diff(args.commit_sha)
    if not fe_files:
        result["reason"] = "commit has no FE files (.tsx/.jsx/.vue/.svelte) — guard not applicable"
        return emit(result, args.output)
    if not diff_text:
        result["reason"] = "could not extract diff text via git show"
        return emit(result, args.output)

    view_components_md = phase_dir / "VIEW-COMPONENTS.md"
    view_components = extract_view_components_row(view_components_md, args.slug)
    prompt = build_prompt(args.slug, png_path, diff_text, view_components, fe_files)

    cmd = [
        "claude", "--model", args.model, "--print",
        "--add-dir", str(png_path.parent),
        prompt + f"\n\nIMAGE PATH: {png_path}",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
    except FileNotFoundError:
        result["reason"] = "claude CLI exec failed"
        return emit(result, args.output)
    except subprocess.TimeoutExpired:
        result["reason"] = f"claude CLI timed out after {args.timeout}s"
        return emit(result, args.output)

    out = (proc.stdout or "").strip()
    if not out or proc.returncode != 0:
        result["reason"] = f"claude CLI exit={proc.returncode}, stderr={(proc.stderr or '')[:200]}"
        return emit(result, args.output)

    # Find first line that looks like JSON
    decoded: dict | None = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                decoded = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if decoded is None:
        result["reason"] = f"could not parse JSON from claude output: {out[:200]}"
        return emit(result, args.output)

    verdict = (decoded.get("verdict") or "").upper()
    if verdict not in ("PASS", "FLAG", "BLOCK"):
        result["reason"] = f"invalid verdict from guard: {verdict!r}"
        return emit(result, args.output)

    result["verdict"] = verdict
    result["reason"] = decoded.get("reason", "")[:200]
    missing = [str(m) for m in (decoded.get("missing_components") or []) if m]
    result["missing_components"] = missing
    result["confidence"] = decoded.get("confidence", "low")

    # Promote BLOCK if a core component missed (regardless of count)
    if verdict in ("FLAG", "PASS") and any(m.lower().replace(" ", "") in CORE_COMPONENTS for m in missing):
        result["verdict"] = "BLOCK"
        result["reason"] = f"core component missing ({', '.join(missing)}) — promoted to BLOCK"

    return emit(result, args.output)


if __name__ == "__main__":
    sys.exit(main())
