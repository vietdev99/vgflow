#!/usr/bin/env python3
"""
verify-design-ref-coverage.py — planner-side coverage gate for L-002 mandate.

Pairs with vg-planner-rules.md Rule 8: every FE task in PLAN.md MUST emit
<design-ref> in one of two forms.

  Form A: <design-ref>{slug}</design-ref>
          where {slug} matches kebab-case [a-z0-9_-] and is present in
          design/manifest.json (assets[].slug or screens[].slug).
  Form B: <design-ref>no-asset:{reason}</design-ref>
          explicit gap, logged to override-debt, never silent.

A task is FE if its <file-path> (or extracted source code path) matches:
  - apps/{admin,merchant,vendor,web}/**
  - packages/ui/src/{components,theme}/**
  - any path with extension .tsx, .jsx, .vue, .svelte

Verdicts:
  PASS  — every FE task in scope emits Form A (with valid slug) or Form B
  WARN  — phase has no design/manifest.json; SKIP slug validation (Form B
          still enforced for FE tasks); not a blocker
  BLOCK — at least one FE task missing <design-ref>, OR Form A slug not
          in manifest, OR Form B used without {reason}

USAGE
  python verify-design-ref-coverage.py \
    --phase-dir .vg/phases/07.10-... \
    [--manifest .vg/design-normalized/manifest.json] \
    [--output report.json] \
    [--strict]   # promote WARN to BLOCK

EXIT
  0 — PASS or WARN
  1 — BLOCK (or WARN with --strict)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FE_PATH_RE = re.compile(
    r"(apps/(admin|merchant|vendor|web)/|packages/ui/src/(components|theme)/|\.(tsx|jsx|vue|svelte)\b)",
    re.IGNORECASE,
)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")
NO_ASSET_RE = re.compile(r"^no-asset:(.{3,})$")


def extract_file_paths(body: str) -> list[str]:
    paths = re.findall(r"<file-path>([^<]+)</file-path>", body)
    paths += re.findall(r"<files>([^<]+)</files>", body)
    paths += re.findall(
        r"\b(?:apps|packages|src|lib|server|client)/[A-Za-z0-9_./@{}-]+\.(?:ts|tsx|js|jsx|py|go|rs|vue|svelte)",
        body,
    )
    yaml_paths = re.findall(r'^\s*path:\s*"([^"]+)"', body, re.MULTILINE)
    paths += yaml_paths
    return [p.strip() for p in paths if p.strip()]


def is_fe_task(file_paths: list[str]) -> bool:
    return any(FE_PATH_RE.search(p) for p in file_paths)


def extract_design_refs(body: str) -> list[str]:
    refs: list[str] = []
    for raw in re.findall(r"<design-ref>([^<]+)</design-ref>", body):
        for r in re.split(r"[,\s]+", raw.strip()):
            r = r.strip()
            if r:
                refs.append(r)
    return refs


def iterate_tasks(plan_path: Path):
    text = plan_path.read_text(encoding="utf-8", errors="ignore")

    xml_re = re.compile(
        r'<task\s+id\s*=\s*["\']?(\d+|[A-Za-z][A-Za-z0-9_-]*)["\']?\s*>(.*?)</task>',
        re.DOTALL | re.IGNORECASE,
    )
    seen_ids: set[str] = set()
    for m in xml_re.finditer(text):
        tid = m.group(1)
        seen_ids.add(tid)
        yield tid, m.group(2)

    heading_re = re.compile(
        r"^#{2,3}\s+Task\s+(0?\d+)\b", re.IGNORECASE | re.MULTILINE
    )
    lines = text.splitlines()
    heads = [
        (i, m.group(1).lstrip("0") or "0")
        for i, line in enumerate(lines)
        for m in [heading_re.match(line)]
        if m
    ]
    for idx, (line_no, tid) in enumerate(heads):
        if tid in seen_ids:
            continue
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        yield tid, "\n".join(lines[line_no:end])


def load_manifest_slugs(manifest_path: Path) -> set[str] | None:
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    slugs: set[str] = set()
    for key in ("assets", "screens"):
        for entry in data.get(key, []) or []:
            if isinstance(entry, dict):
                slug = entry.get("slug")
                if isinstance(slug, str) and slug:
                    slugs.add(slug)
    return slugs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--manifest", default=None, help="path to design manifest.json (auto-detect if omitted)")
    ap.add_argument("--output", default=None)
    ap.add_argument("--strict", action="store_true", help="promote WARN to BLOCK")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    if not phase_dir.exists():
        print(json.dumps({"verdict": "BLOCK", "reason": f"phase-dir not found: {phase_dir}"}, indent=2))
        return 1

    if args.manifest:
        manifest_path = Path(args.manifest)
    else:
        candidates = [
            phase_dir / "design" / "manifest.json",
            Path(".vg/design-normalized/manifest.json"),
            Path(".planning/design-normalized/manifest.json"),
        ]
        manifest_path = next((c for c in candidates if c.exists()), candidates[0])

    slugs = load_manifest_slugs(manifest_path)
    manifest_present = slugs is not None

    plan_files = sorted(phase_dir.glob("*PLAN*.md"))
    if not plan_files:
        result = {
            "verdict": "WARN",
            "reason": "no PLAN*.md files in phase-dir",
            "phase_dir": str(phase_dir),
        }
        return _emit(result, args)

    fe_tasks = 0
    missing_design_ref: list[dict] = []
    invalid_slug: list[dict] = []
    form_b_no_reason: list[dict] = []
    form_b_used: list[dict] = []
    skipped_no_path: list[dict] = []

    for plan in plan_files:
        for tid, body in iterate_tasks(plan):
            file_paths = extract_file_paths(body)
            if not file_paths:
                skipped_no_path.append({"task": tid, "plan": plan.name})
                continue
            if not is_fe_task(file_paths):
                continue
            fe_tasks += 1
            refs = extract_design_refs(body)
            if not refs:
                missing_design_ref.append(
                    {"task": tid, "plan": plan.name, "file_paths": file_paths[:3]}
                )
                continue
            for ref in refs:
                m = NO_ASSET_RE.match(ref)
                if m:
                    reason = m.group(1).strip()
                    if not reason or len(reason) < 3:
                        form_b_no_reason.append({"task": tid, "plan": plan.name, "ref": ref})
                    else:
                        form_b_used.append({"task": tid, "plan": plan.name, "reason": reason})
                elif SLUG_RE.match(ref):
                    if manifest_present and ref not in (slugs or set()):
                        invalid_slug.append(
                            {"task": tid, "plan": plan.name, "slug": ref}
                        )
                else:
                    invalid_slug.append(
                        {"task": tid, "plan": plan.name, "slug": ref, "reason": "not kebab-case slug or no-asset:"}
                    )

    blocking = bool(missing_design_ref or form_b_no_reason or invalid_slug)
    result = {
        "phase_dir": str(phase_dir),
        "manifest_path": str(manifest_path),
        "manifest_present": manifest_present,
        "fe_tasks_total": fe_tasks,
        "form_b_used": form_b_used,
        "missing_design_ref": missing_design_ref,
        "invalid_slug": invalid_slug,
        "form_b_no_reason": form_b_no_reason,
        "skipped_no_path": skipped_no_path,
    }

    if blocking:
        result["verdict"] = "BLOCK"
        bits = []
        if missing_design_ref:
            bits.append(f"{len(missing_design_ref)} FE task(s) missing <design-ref>")
        if invalid_slug:
            bits.append(
                f"{len(invalid_slug)} slug(s) "
                f"{'not in manifest' if manifest_present else 'malformed'}"
            )
        if form_b_no_reason:
            bits.append(f"{len(form_b_no_reason)} Form B without {{reason}}")
        result["reason"] = "; ".join(bits)
    elif not manifest_present:
        result["verdict"] = "WARN"
        result["reason"] = (
            f"manifest not found at {manifest_path}; Form A slugs not validated. "
            "Run /vg:design-extract or pass --manifest."
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
    if result["verdict"] == "BLOCK":
        return 1
    if result["verdict"] == "WARN" and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
