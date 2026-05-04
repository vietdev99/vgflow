#!/usr/bin/env python3
"""generate_recursive_prompts.py — manual-mode prompt fan-out (Task 20, v2.40.2).

Reads a plan JSON (list of {element, lens} dicts produced by
``spawn_recursive_probe.build_plan``) and renders, under
``<phase_dir>/recursive-prompts/<tool>/`` (one subdir per tool):

  - ``MANIFEST.md``         : tool-specific paste runbook listing every probe
  - ``lens-<slug>-<sel>.md``: short (~15 lines) per-probe paste file that REFs
                              the canonical lens prompt at
                              ``commands/vg/_shared/lens-prompts/<lens>.md``
  - ``EXPECTED-OUTPUTS.md`` : manifest of expected ``runs/<tool>/recursive-*.json``
                              paths used by ``verify_manual_run_artifacts.py``
                              (Task 21).

v2.40.2 change: previously every artifact was written under a single
``recursive-prompts/`` dir + ``runs/manual/`` output dir. Now we emit one
subdir per tool (codex / gemini) so users can paste into either CLI without
output collisions, and per-probe files are short paste targets rather than
inline copies of the full lens text.

Templates live under ``commands/vg/_shared/templates/MANUAL-PROBE-*.tmpl`` and
use ``{{var}}`` substitution.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

TEMPLATE_DIR_CANDIDATES: list[Path] = [
    REPO_ROOT / "commands" / "vg" / "_shared" / "templates",
    REPO_ROOT / ".claude" / "commands" / "vg" / "_shared" / "templates",
]

# Default minimum-required probe counts per mode (matches Task 19 caps but is
# advisory for manual runs — verify_manual_run_artifacts.py enforces).
MODE_MIN_REQUIRED: dict[str, int] = {"light": 5, "deep": 15, "exhaustive": 40}

# Per-tool metadata (token env, label, CLI invocation hint).
TOOL_META: dict[str, dict[str, str]] = {
    "gemini": {
        "token_env": "GEMINI_PROBE_TOKEN",
        "label": "Gemini",
        "cli_open": (
            "Open Gemini interactive: `gemini` "
            "(or `gemini --allowed-mcp-server-names playwright1`)"
        ),
    },
    "codex": {
        "token_env": "CODEX_PROBE_TOKEN",
        "label": "Codex",
        "cli_open": "Open Codex interactive: `codex` (CLI command varies by version)",
    },
}


# ---------------------------------------------------------------------------
# Template loading + rendering
# ---------------------------------------------------------------------------
def _find_template(name: str) -> Path:
    for d in TEMPLATE_DIR_CANDIDATES:
        candidate = d / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Template not found in {TEMPLATE_DIR_CANDIDATES}: {name}"
    )


_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _render(template: str, context: dict[str, Any]) -> str:
    """Replace every ``{{name}}`` with ``str(context[name])`` (or empty string)."""
    def sub(m: re.Match[str]) -> str:
        return str(context.get(m.group(1), ""))
    return _VAR_RE.sub(sub, template)


# ---------------------------------------------------------------------------
# Probe rendering
# ---------------------------------------------------------------------------
def _slugify(value: str) -> str:
    """Filename-safe slug: alphanum + dash, capped at 32 chars."""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", value or "unknown").strip("-")
    return s[:32] or "unknown"


def _per_lens_filename(lens: str, selector: str) -> str:
    return f"{_slugify(lens)}-{_slugify(selector)}.md"


def _per_lens_output_path(tool: str, lens: str, selector: str,
                          depth: int = 1) -> str:
    """Stable expected output path under ``runs/<tool>/`` (per-tool isolation)."""
    return (
        f"runs/{tool}/recursive-{_slugify(lens)}-"
        f"{_slugify(selector)}-d{depth}.json"
    )


def _element_description(elem: dict[str, Any]) -> str:
    """Human-friendly element label for headings."""
    parts = []
    if elem.get("element_class"):
        parts.append(str(elem["element_class"]))
    if elem.get("view"):
        parts.append(f"@ {elem['view']}")
    if elem.get("selector"):
        parts.append(f"[{elem['selector']}]")
    return " ".join(parts) or "unknown element"


def render_per_lens(template: str, *, probe_index: int,
                    entry: dict[str, Any],
                    tool: str,
                    base_url: str = "${BASE_URL}",
                    action_budget: int = 25,
                    depth: int = 1) -> tuple[str, str, str]:
    """Render one probe → (filename, body, expected_output_path).

    The per-probe file is a SHORT (~15 lines) paste target that references
    the canonical lens prompt at
    ``commands/vg/_shared/lens-prompts/<lens>.md`` rather than inlining its
    full content (UX win: easy copy-paste).
    """
    elem = entry.get("element", {}) or {}
    lens = str(entry.get("lens", "lens-unknown"))
    selector = str(elem.get("selector", "unknown"))
    role = str(elem.get("role") or "admin")
    resource = str(elem.get("resource") or "unknown")
    view = str(elem.get("view") or "unknown")
    element_class = str(elem.get("element_class") or "unknown")
    element_slug = _slugify(selector)

    output_path = _per_lens_output_path(tool, lens, selector, depth=depth)
    meta = TOOL_META.get(tool, TOOL_META["gemini"])
    rendered = _render(template, {
        "probe_index": probe_index,
        "lens": lens,
        "tool": tool,
        "tool_token_env": meta["token_env"],
        "element_class": element_class,
        "element_description": _element_description(elem),
        "element_slug": element_slug,
        "view": view,
        "selector": selector,
        "resource": resource,
        "role": role,
        "base_url": base_url,
        "action_budget": action_budget,
        "depth": depth,
        "output_path": output_path,
    })
    fname = _per_lens_filename(lens, selector)
    return fname, rendered, output_path


def render_manifest(template: str, *, phase_name: str, phase_dir: Path,
                    probes: list[dict[str, Any]], mode: str,
                    tool: str) -> str:
    meta = TOOL_META.get(tool, TOOL_META["gemini"])
    lines: list[str] = []
    for i, p in enumerate(probes, start=1):
        elem = p["element"] if isinstance(p.get("element"), dict) else {}
        lines.append(
            f"### Probe {i}: {p['lens']} on {elem.get('element_class','?')}\n"
            f"**File**: `{tool}/{p['prompt_file']}`\n"
            f"**Output**: `{p['output_path']}`"
        )
    probe_list = "\n\n".join(lines) if lines else "_(no probes planned)_"
    return _render(template, {
        "phase_name": phase_name,
        "phase_dir": str(phase_dir),
        "mode": mode,
        "tool": tool,
        "tool_label": meta["label"],
        "tool_token_env": meta["token_env"],
        "cli_open_instruction": meta["cli_open"],
        "probe_list": probe_list,
        "probe_count": len(probes),
        "min_required": MODE_MIN_REQUIRED.get(mode, 1),
    })


def render_expected_outputs(probes: list[dict[str, Any]]) -> str:
    """Plain Markdown list — read by verify_manual_run_artifacts.py (Task 21)."""
    body = ["# EXPECTED OUTPUTS — recursive manual run\n"]
    if not probes:
        body.append("_(no probes planned)_\n")
    for i, p in enumerate(probes, start=1):
        elem = p["element"] if isinstance(p.get("element"), dict) else {}
        body.append(
            f"- {i}. lens=`{p['lens']}` element_class=`{elem.get('element_class','?')}` "
            f"selector=`{elem.get('selector','?')}` → `{p['output_path']}`"
        )
    return "\n".join(body) + "\n"


# ---------------------------------------------------------------------------
# Per-tool generation
# ---------------------------------------------------------------------------
def _generate_for_tool(tool: str, *, plan: list[dict[str, Any]],
                        phase_dir: Path, mode: str,
                        manifest_tmpl: str, per_lens_tmpl: str) -> int:
    """Write the per-tool subdir tree. Returns number of probes written."""
    tool_dir = phase_dir / "recursive-prompts" / tool
    tool_dir.mkdir(parents=True, exist_ok=True)

    probes_meta: list[dict[str, Any]] = []
    for i, entry in enumerate(plan, start=1):
        if not isinstance(entry, dict):
            continue
        fname, body, output_path = render_per_lens(
            per_lens_tmpl, probe_index=i, entry=entry, tool=tool,
        )
        (tool_dir / fname).write_text(body, encoding="utf-8")
        probes_meta.append({
            "lens": str(entry.get("lens", "lens-unknown")),
            "element": entry.get("element", {}),
            "prompt_file": fname,
            "output_path": output_path,
        })

    manifest = render_manifest(
        manifest_tmpl,
        phase_name=phase_dir.name,
        phase_dir=phase_dir,
        probes=probes_meta,
        mode=mode,
        tool=tool,
    )
    (tool_dir / "MANIFEST.md").write_text(manifest, encoding="utf-8")

    expected = render_expected_outputs(probes_meta)
    (tool_dir / "EXPECTED-OUTPUTS.md").write_text(expected, encoding="utf-8")
    return len(probes_meta)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="generate_recursive_prompts.py",
        description="Render manual-mode probe prompts under "
                    "<phase>/recursive-prompts/<tool>/",
    )
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--plan-json", required=True,
                    help="JSON-encoded list of {element, lens} dicts.")
    ap.add_argument("--mode", choices=["light", "deep", "exhaustive"],
                    default="light")
    ap.add_argument(
        "--tools",
        default="gemini,codex",
        help="Comma-separated tool list. Each tool gets its own subdir under "
             "recursive-prompts/<tool>/ + runs/<tool>/. "
             "Default: 'gemini,codex' (both subdirs).",
    )
    return ap


def _parse_tools(raw: str) -> list[str]:
    items = [t.strip().lower() for t in (raw or "").split(",") if t.strip()]
    valid: list[str] = []
    for t in items:
        if t not in TOOL_META:
            raise ValueError(
                f"unknown tool '{t}'. Supported: {sorted(TOOL_META.keys())}"
            )
        if t not in valid:
            valid.append(t)
    return valid or ["gemini", "codex"]


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.is_dir():
        sys.stderr.write(f"phase dir not found: {phase_dir}\n")
        return 2

    try:
        plan = json.loads(args.plan_json)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"--plan-json is not valid JSON: {exc}\n")
        return 2
    if not isinstance(plan, list):
        sys.stderr.write("--plan-json must decode to a JSON array.\n")
        return 2

    try:
        tools = _parse_tools(args.tools)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    try:
        manifest_tmpl = _find_template(
            "MANUAL-PROBE-MANIFEST.tmpl"
        ).read_text(encoding="utf-8")
        per_lens_tmpl = _find_template(
            "MANUAL-PROBE-PER-LENS.tmpl"
        ).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    total_per_tool: dict[str, int] = {}
    for tool in tools:
        n = _generate_for_tool(
            tool,
            plan=plan,
            phase_dir=phase_dir,
            mode=args.mode,
            manifest_tmpl=manifest_tmpl,
            per_lens_tmpl=per_lens_tmpl,
        )
        total_per_tool[tool] = n

    summary = ", ".join(f"{t}={n}" for t, n in total_per_tool.items())
    print(
        f"Wrote per-tool probe prompts under "
        f"{phase_dir / 'recursive-prompts'} ({summary})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
