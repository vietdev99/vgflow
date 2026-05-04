#!/usr/bin/env python3
"""
Validator: verify-design-ref-required.py — Phase 15 D-02

Hard-required <design-ref slug="..."> on every UI task (file path matches
*.tsx/.vue/.jsx/.svelte). Slug must exist in slug-registry.json.

Closes the warn-only R4 gap where AI silently skipped design references.
Per CLAUDE.md feedback rule: rules auto-detectable → BLOCK, no warn-only.

Logic:
  1. Read PLAN.md tasks. Each <task> has zero+ <file-path> + zero+ <design-ref>.
  2. For each task with at least one UI file path:
       - assert ≥1 <design-ref slug="..."> child element
       - per slug: cross-check against slug-registry.json (T3.1 territory but
         opportunistic check here too)
  3. Missing design-ref OR invalid slug → BLOCK with task_id + remediation.

Usage:  verify-design-ref-required.py --phase 7.14.3
Output: vg.validator-output JSON on stdout
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

UI_FILE_RE = re.compile(r"\.(tsx|vue|jsx|svelte)\b", re.IGNORECASE)

# Loose XML-ish match for tasks. Real PLAN.md uses <task id="T-X">..</task>
# blocks; this regex captures the body for inspection.
TASK_BLOCK_RE = re.compile(
    r"<task\s+([^>]*?)>(.*?)</task>",
    re.IGNORECASE | re.DOTALL,
)
TASK_ID_RE = re.compile(r'\b(?:id|task[-_]?id)\s*=\s*"([^"]+)"', re.IGNORECASE)
FILE_PATH_RE = re.compile(r"<file-path>(.*?)</file-path>", re.IGNORECASE | re.DOTALL)
DESIGN_REF_RE = re.compile(
    r'<design-ref\s+(?:[^>]*?\s+)?slug\s*=\s*"([^"]+)"', re.IGNORECASE,
)


def _load_slug_registry() -> dict:
    repo = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
    for candidate in (
        repo / ".planning" / "design-normalized" / "slug-registry.json",
        repo / ".planning" / "design-normalized" / "manifest.json",
    ):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
    return {}


def _registry_slugs(registry: dict) -> set[str]:
    slugs = set()
    for s in (registry.get("slugs") or {}).keys():
        slugs.add(s)
    for asset in registry.get("assets") or []:
        s = asset.get("slug")
        if s:
            slugs.add(s)
    return slugs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument(
        "--profile",
        default=None,
        choices=("prototype", "default", "production"),
        help=(
            "Phase 15 D-08 fidelity profile. When 'production', missing "
            "<design-ref> on UI tasks is BLOCK (was WARN in default). When "
            "'prototype', missing refs degrade to advisory only. Resolved "
            "upstream by scope.md / blueprint.md via threshold-resolver.py."
        ),
    )
    args = ap.parse_args()

    out = Output(validator="design-ref-required")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        if not phase_dir:
            out.add(Evidence(type="missing_file",
                             message=f"Phase dir not found for {args.phase}"))
            emit_and_exit(out)

        plan_files = sorted(phase_dir.glob("PLAN*.md"))
        if not plan_files:
            out.add(Evidence(
                type="missing_file",
                message="No PLAN*.md found in phase dir",
                fix_hint="Run /vg:blueprint to generate PLAN.md before this validator.",
            ))
            emit_and_exit(out)

        registry = _load_slug_registry()
        valid_slugs = _registry_slugs(registry)

        # D-08 profile gate (Phase 15): production = BLOCK on missing ref;
        # default = WARN; prototype = advisory (no escalation). Default to
        # 'default' when caller didn't pass --profile so behavior matches the
        # legacy WARN convention.
        profile = (args.profile or "default").lower()

        def _emit_missing(evidence: Evidence) -> None:
            if profile == "production":
                out.add(evidence)               # escalate → BLOCK
            elif profile == "prototype":
                evidence.type = "info"
                out.evidence.append(evidence)   # advisory; no escalation
            else:
                out.warn(evidence)              # escalate → WARN

        any_ui_task = False
        for plan_path in plan_files:
            text = plan_path.read_text(encoding="utf-8", errors="ignore")
            for task_match in TASK_BLOCK_RE.finditer(text):
                attrs = task_match.group(1)
                body = task_match.group(2)
                id_m = TASK_ID_RE.search(attrs) or TASK_ID_RE.search(body)
                task_id = id_m.group(1) if id_m else "(unknown)"

                file_paths = [m.group(1).strip() for m in FILE_PATH_RE.finditer(body)]
                ui_paths = [p for p in file_paths if UI_FILE_RE.search(p)]
                if not ui_paths:
                    continue
                any_ui_task = True

                refs = DESIGN_REF_RE.findall(body)
                if not refs:
                    _emit_missing(Evidence(
                        type="missing_file",
                        message=(f"Task {task_id} touches UI file(s) but has no "
                                 f"<design-ref slug='...'/> child "
                                 f"(profile={profile})"),
                        file=str(plan_path),
                        actual=ui_paths[:5],
                        fix_hint=(
                            "Add `<design-ref slug=\"<slug>\"/>` inside the <task>...</task> "
                            "block. Slug must exist in slug-registry.json (run "
                            "/vg:design-extract first if registry missing). "
                            "OR relax via --fidelity-profile default (logs override-debt)."
                        ),
                    ))
                    continue

                # Validate each slug against registry (if registry available)
                if valid_slugs:
                    for slug in refs:
                        if slug not in valid_slugs:
                            out.add(Evidence(
                                type="malformed_content",
                                message=(f"Task {task_id} references slug "
                                         f"'{slug}' not in slug-registry.json"),
                                file=str(plan_path),
                                actual=slug,
                                expected=sorted(valid_slugs)[:10],
                                fix_hint=(
                                    f"Either add '{slug}' to design_assets.paths "
                                    "and re-run /vg:design-extract, OR fix the "
                                    "slug to an existing one."
                                ),
                            ))

        if not any_ui_task and not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message="No UI tasks (*.tsx/.vue/.jsx/.svelte) in PLAN — nothing to enforce",
            ))
        elif not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message="All UI tasks have valid <design-ref slug='...'/> bindings",
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
