#!/usr/bin/env python3
"""
verify-ui-spec-scan-coverage.py — D-01 sanity gate.

After /vg:blueprint step 2b6 produces UI-SPEC.md, verify the agent did NOT
silently drop scan.json findings. For every <design-ref> slug used in
PLAN.md whose scans/{slug}.scan.json contains modals_discovered or
forms_discovered, UI-SPEC.md must have ## Modals or ## Forms sections
and mention each discovered name.

This is a lightweight regex check, not semantic validation — primary
intent is catching the "agent ignored scan.json entirely" failure mode.

USAGE
  python verify-ui-spec-scan-coverage.py \
    --phase-dir .vg/phases/07.10-... \
    [--design-dir .vg/design-normalized] \
    [--output report.json]

EXIT
  0 — PASS or SKIP (no scan.json or no UI-SPEC.md)
  1 — BLOCK (UI-SPEC.md missing Modals/Forms section while scan.json non-empty)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def load_scan(scan_path: Path) -> dict:
    try:
        return json.loads(scan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--design-dir", default=".vg/design-normalized")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    ui_spec = phase_dir / "UI-SPEC.md"
    design_dir = Path(args.design_dir)
    if not design_dir.is_absolute():
        design_dir = (Path.cwd() / design_dir).resolve()
    scans_dir = design_dir / "scans"

    result: dict = {
        "phase_dir": str(phase_dir),
        "ui_spec": str(ui_spec),
        "scans_dir": str(scans_dir),
        "verdict": "SKIP",
        "modal_gaps": [],
        "form_gaps": [],
        "scan_files_consumed": 0,
    }

    if not ui_spec.exists():
        result["reason"] = "UI-SPEC.md not found — step 2b6 likely skipped"
        return _emit(result, args)
    if not scans_dir.exists():
        result["reason"] = f"no scans/ dir at {scans_dir} — design-extract not run or no slug assets"
        return _emit(result, args)

    spec_text = ui_spec.read_text(encoding="utf-8", errors="ignore")
    has_modals_section = bool(re.search(r"^##\s+Modals\b", spec_text, re.MULTILINE | re.IGNORECASE))
    has_forms_section = bool(re.search(r"^##\s+Forms\b", spec_text, re.MULTILINE | re.IGNORECASE))

    expected_modals: set[str] = set()
    expected_forms: set[str] = set()
    consumed = 0
    for scan_file in sorted(scans_dir.glob("*.scan.json")):
        scan = load_scan(scan_file)
        if not scan:
            continue
        consumed += 1
        for m in scan.get("modals_discovered") or []:
            name = m.get("name") if isinstance(m, dict) else m
            if isinstance(name, str) and name.strip():
                expected_modals.add(name.strip())
        for f in scan.get("forms_discovered") or []:
            name = f.get("name") if isinstance(f, dict) else f
            if isinstance(name, str) and name.strip():
                expected_forms.add(name.strip())

    result["scan_files_consumed"] = consumed
    result["expected_modals"] = sorted(expected_modals)
    result["expected_forms"] = sorted(expected_forms)

    if not expected_modals and not expected_forms:
        result["verdict"] = "PASS"
        result["reason"] = "no modals/forms discovered in any scan.json — nothing to enforce"
        return _emit(result, args)

    if expected_modals and not has_modals_section:
        result["modal_gaps"].append("UI-SPEC.md missing '## Modals' section while scan.json discovered modals")
    else:
        for name in sorted(expected_modals):
            if name.lower() not in spec_text.lower():
                result["modal_gaps"].append(name)

    if expected_forms and not has_forms_section:
        result["form_gaps"].append("UI-SPEC.md missing '## Forms' section while scan.json discovered forms")
    else:
        for name in sorted(expected_forms):
            if name.lower() not in spec_text.lower():
                result["form_gaps"].append(name)

    if result["modal_gaps"] or result["form_gaps"]:
        result["verdict"] = "BLOCK"
        result["reason"] = (
            f"UI-SPEC dropped {len(result['modal_gaps'])} modal(s) "
            f"and {len(result['form_gaps'])} form(s) from scan.json"
        )
    else:
        result["verdict"] = "PASS"

    return _emit(result, args)


def _emit(result: dict, args) -> int:
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if result["verdict"] in ("PASS", "SKIP") else 1


if __name__ == "__main__":
    sys.exit(main())
