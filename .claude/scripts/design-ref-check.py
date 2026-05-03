#!/usr/bin/env python3
"""Build-time design-ref inventory and resolver gate.

Used by /vg:build before any executor spawn. It turns PLAN design refs into a
machine-readable contract: real slug refs must resolve to concrete PNG paths
through the shared 2-tier resolver, Form B refs remain explicit debt, and stale
`.wave-tasks` caches are detected before the executor reads old task bodies.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
from design_ref_resolver import (  # noqa: E402
    DesignRefEntry,
    extract_design_ref_entries,
    parse_config_file,
    resolve_design_assets,
)


def iter_task_bodies(plan_path: Path):
    text = plan_path.read_text(encoding="utf-8", errors="ignore")
    seen: set[str] = set()
    xml_re = re.compile(
        r'<task\s+id\s*=\s*["\']?(\d+|[A-Za-z][A-Za-z0-9_.-]*)["\']?\s*>(.*?)</task>',
        re.DOTALL | re.IGNORECASE,
    )
    for m in xml_re.finditer(text):
        tid = str(m.group(1)).lstrip("0") or "0"
        seen.add(tid)
        yield tid, m.group(2), plan_path.name

    heading_re = re.compile(r"^#{2,3}\s+Task\s+(0?\d+)\b", re.IGNORECASE | re.MULTILINE)
    lines = text.splitlines()
    heads = [
        (i, m.group(1).lstrip("0") or "0")
        for i, line in enumerate(lines)
        for m in [heading_re.match(line)]
        if m
    ]
    for idx, (line_no, tid) in enumerate(heads):
        if tid in seen:
            continue
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        yield tid, "\n".join(lines[line_no:end]), plan_path.name


def route_for(body: str) -> str:
    m = re.search(r"<route>([^<]+)</route>", body)
    return m.group(1).strip() if m else ""


def collect_entries_from_plan(phase_dir: Path) -> tuple[list[dict], list[str], list[str]]:
    tasks: list[dict] = []
    no_asset: list[str] = []
    descriptive: list[str] = []
    for plan in sorted(phase_dir.glob("*PLAN*.md")):
        for tid, body, plan_name in iter_task_bodies(plan):
            for entry in extract_design_ref_entries(body):
                if entry.kind == "slug":
                    tasks.append({
                        "task": tid,
                        "slug": entry.value,
                        "route": route_for(body),
                        "plan": plan_name,
                    })
                elif entry.kind == "no_asset":
                    no_asset.append(entry.value)
                else:
                    descriptive.append(entry.value)
    return tasks, sorted(set(no_asset)), sorted(set(descriptive))


def collect_refs_from_wave_tasks(wave_tasks_dir: Path) -> list[DesignRefEntry]:
    entries: list[DesignRefEntry] = []
    if not wave_tasks_dir.exists():
        return entries
    for task in sorted(wave_tasks_dir.glob("task-*.md")):
        try:
            entries.extend(extract_design_ref_entries(task.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--config", default=".claude/vg.config.md")
    ap.add_argument("--wave-tasks-dir", default=None)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    phase_dir = Path(args.phase_dir)
    if not phase_dir.is_absolute():
        phase_dir = (repo_root / phase_dir).resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    config = parse_config_file(config_path)

    task_refs, no_asset_refs, descriptive_refs = collect_entries_from_plan(phase_dir)
    resolved: list[dict] = []
    missing: list[dict] = []
    for item in task_refs:
        assets = resolve_design_assets(
            item["slug"],
            repo_root=repo_root,
            phase_dir=phase_dir,
            config=config,
        )
        screenshots = [str(p) for p in assets.screenshots]
        record = {
            **item,
            "screenshots": screenshots,
            "structural": str(assets.structural) if assets.structural else None,
            "interactions": str(assets.interactions) if assets.interactions else None,
            "tier": assets.tier,
            "root": str(assets.root) if assets.root else None,
        }
        resolved.append(record)
        if not screenshots:
            missing.append({
                "task": item["task"],
                "slug": item["slug"],
                "plan": item["plan"],
                "expected": [str(p) for p in assets.missing_candidates[:4]],
                "reason": "png_missing",
            })

    wave_tasks_dir = Path(args.wave_tasks_dir) if args.wave_tasks_dir else phase_dir / ".wave-tasks"
    if not wave_tasks_dir.is_absolute():
        wave_tasks_dir = repo_root / wave_tasks_dir
    wave_entries = collect_refs_from_wave_tasks(wave_tasks_dir)
    plan_slugs = sorted({item["slug"] for item in task_refs})
    wave_slugs = sorted({entry.value for entry in wave_entries if entry.kind == "slug"})
    wave_tasks_stale = wave_tasks_dir.exists() and plan_slugs != wave_slugs

    payload = {
        "phase_dir": str(phase_dir),
        "slug_refs": plan_slugs,
        "task_refs": resolved,
        "missing": missing,
        "no_asset_refs": no_asset_refs,
        "descriptive_refs": descriptive_refs,
        "wave_tasks_dir": str(wave_tasks_dir),
        "wave_tasks_stale": wave_tasks_stale,
        "plan_slug_signature": "|".join(plan_slugs),
        "wave_slug_signature": "|".join(wave_slugs),
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        out = Path(args.output)
        if not out.is_absolute():
            out = repo_root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
