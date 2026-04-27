#!/usr/bin/env python3
"""
Validator: verify-uimap-injection.py — Phase 15 D-12a

Asserts that /vg:build step 8c prepared executor prompts contain the required
injection blocks for every UI task BEFORE invoking the Sonnet executor.
Closes the audit gap (codex.out:14459: "build never injects [UI-MAP] into
executor context and only checks it after code has already been written").

Required headers (case-sensitive, on their own line) per UI task prompt:
  ## UI-MAP-SUBTREE-FOR-THIS-WAVE
  ## DESIGN-REF

Each header must be followed by non-empty content (≥1 non-blank line before
the next header or end of prompt).

Logic:
  1. Locate prepared executor prompts in phase dir build artifacts:
       .vg/phases/<phase>/.build/wave-<N>/executor-prompts/*.md
       OR .vg/phases/<phase>/build-trace/wave-<N>/executor-input/*.txt
     Convention may vary — accept multiple locations + glob.
  2. For each prompt file:
       - If filename hints UI task (matches UI extension OR has owner-task-id
         tag pointing to UI file): assert both headers present + non-empty.
  3. Missing → BLOCK with task_id + missing header(s).

Usage:  verify-uimap-injection.py --phase 7.14.3 [--prompts-dir <override>]
Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

UI_FILE_RE = re.compile(r"\.(tsx|vue|jsx|svelte)\b", re.IGNORECASE)
HEADER_UIMAP = "## UI-MAP-SUBTREE-FOR-THIS-WAVE"
HEADER_DESIGN_REF = "## DESIGN-REF"

# Default search paths under phase dir for prepared prompts.
# Phase 16 hot-fix (v2.11.1): build.md step 8c now writes 3 file shapes per
# task — body.md (task body), meta.json (D-01 sidecar), uimap.md (UI-MAP
# wrapper). The first glob (*.uimap.md) catches the new shape; the second
# (*.md) catches the legacy P15 D-12a single-file shape. SKIP_SUFFIXES
# prevents body/meta files (which would false-positive _is_ui_prompt but
# legitimately lack UI-MAP headers) from being audited.
PROMPT_GLOBS = (
    ".build/wave-*/executor-prompts/*.uimap.md",
    ".build/wave-*/executor-prompts/*.md",  # legacy P15 D-12a + general fallback
    ".build/wave-*/executor-prompts/*.txt",
    "build-trace/wave-*/executor-input/*.md",
    "build-trace/wave-*/executor-input/*.txt",
)

# Skip body/meta files (Phase 16 split-persist). Applied to both default
# glob path and CLI override --prompts-dir path so the audit input is
# consistent regardless of how the file list was discovered.
SKIP_SUFFIXES = (".body.md", ".meta.json")


def _passes_skip_filter(p: Path) -> bool:
    return not any(p.name.endswith(s) for s in SKIP_SUFFIXES)


def _section_has_content(prompt_text: str, header: str) -> bool:
    """Return True if header is present AND followed by non-empty content
    (at least one non-blank, non-header line) before the next H2 header."""
    idx = prompt_text.find(header)
    if idx < 0:
        return False
    after = prompt_text[idx + len(header):]
    # Stop at next H2 (^##) — non-greedy slice
    next_h2 = re.search(r"\n##\s", after)
    body = after[:next_h2.start()] if next_h2 else after
    # Strip whitespace; require at least 10 non-whitespace chars to count as "real content"
    stripped = body.strip()
    return len(stripped) >= 10


def _is_ui_prompt(prompt_text: str, prompt_path: Path) -> bool:
    """Heuristic: prompt targets a UI task if it mentions a UI file path."""
    if UI_FILE_RE.search(str(prompt_path)):
        return True
    if UI_FILE_RE.search(prompt_text):
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--prompts-dir", help="Override default search paths (comma-separated)")
    args = ap.parse_args()

    out = Output(validator="uimap-injection")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            out.add(Evidence(type="missing_file",
                             message=f"Phase dir not found for {args.phase}"))
            emit_and_exit(out)

        prompts: list[Path] = []
        if args.prompts_dir:
            for d in args.prompts_dir.split(","):
                base = Path(d.strip())
                if not base.is_absolute():
                    base = phase_dir / base
                if base.is_file():
                    prompts.append(base)
                elif base.is_dir():
                    prompts.extend(
                        p for p in base.glob("*")
                        if p.is_file() and _passes_skip_filter(p)
                    )
        else:
            for g in PROMPT_GLOBS:
                prompts.extend(
                    p for p in phase_dir.glob(g)
                    if p.is_file() and _passes_skip_filter(p)
                )

        if not prompts:
            # No prompts captured — could mean step 8c hasn't run, or
            # build doesn't persist executor prompts. Soft-warn (don't BLOCK
            # if there's no evidence to inspect).
            out.warn(Evidence(
                type="info",
                message=("No prepared executor prompts found in phase dir. "
                         "verify-uimap-injection requires build to persist "
                         "prompts to .build/wave-*/executor-prompts/."),
                fix_hint=(
                    "Ensure /vg:build step 8c writes prepared prompt to "
                    "${PHASE_DIR}/.build/wave-${N}/executor-prompts/${task_id}.md "
                    "BEFORE invoking the Sonnet executor."
                ),
            ))
            emit_and_exit(out)

        ui_prompt_count = 0
        for p in prompts:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError as e:
                out.add(Evidence(type="malformed_content",
                                 message=f"Cannot read prompt {p.name}: {e}",
                                 file=str(p)))
                continue

            if not _is_ui_prompt(text, p):
                continue
            ui_prompt_count += 1

            missing = []
            if not _section_has_content(text, HEADER_UIMAP):
                missing.append(HEADER_UIMAP)
            if not _section_has_content(text, HEADER_DESIGN_REF):
                missing.append(HEADER_DESIGN_REF)

            if missing:
                out.add(Evidence(
                    type="missing_file",
                    message=(f"Executor prompt {p.name} missing required injection "
                             f"section(s): {', '.join(missing)}"),
                    file=str(p),
                    expected=[HEADER_UIMAP, HEADER_DESIGN_REF],
                    actual=[h for h in (HEADER_UIMAP, HEADER_DESIGN_REF) if h not in missing],
                    fix_hint=(
                        "Build step 8c must inject:\n"
                        "  - UI-MAP subtree (Haiku-extracted per owner-wave-id, T4.2)\n"
                        "  - design-ref structural.json + screenshot path + interactions.md\n"
                        "BEFORE Agent/Task call. See commands/vg/build.md step 8c (T7.3)."
                    ),
                ))

        if not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message=(f"All {ui_prompt_count} UI executor prompt(s) have "
                         f"required injection sections"),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
