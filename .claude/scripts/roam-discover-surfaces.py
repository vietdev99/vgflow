#!/usr/bin/env python3
"""roam-discover-surfaces.py (v1.1)

Discover CRUD-bearing surfaces in a phase. Emit SURFACES.md table with
columns: id | url | role | entity | crud | sub_views.

v1.1 (round-2 D1/D2 fix):
- PLAN.md is consumed via `vg-load --phase N --artifact plan --index` (slim
  TOC, NOT 8K-line flat read). Falls back to PLAN/index.md direct read or
  flat PLAN.md only when vg-load shell is unavailable.
- CRUD-SURFACES.md is loaded when present and treated as the AUTHORITATIVE
  source of truth — its `resources[]` block becomes a separate "surface
  seed" path that bypasses route/entity heuristics. Heuristic discovery
  still augments (not replaces) for routes that the resource block omits.
- API-CONTRACTS.md uses the same vg-load `--artifact contracts --index`
  path when available; flat read remains the fallback.
- CONTEXT.md and RUNTIME-MAP.md remain KEEP-FLAT (small / pre-filtered).

Spec: .vg/research/ROAM-RFC-v1.md section 3 + round-2 review D1/D2.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


CRUD_KEYWORDS = {
    "create": "C",
    "new": "C",
    "add": "C",
    "list": "R",
    "view": "R",
    "show": "R",
    "edit": "U",
    "update": "U",
    "delete": "D",
    "remove": "D",
}


# Reasonable per-source byte cap when we DO have to flat-read (e.g. when
# vg-load is missing). Keeps PLAN.md from blowing context budget on large
# phases. The slim index path (vg-load --index) is preferred and uncapped.
FLAT_READ_BYTE_CAP = 64_000


def extract_routes(text: str) -> list[str]:
    """Find route-like strings: /admin/foo, /merchant/bar/{id}, etc.

    Filter out filesystem paths that share the prefix (e.g. apps/admin/src/...,
    /admin/src/api/foo.api.ts). Routes do not contain file extensions and
    don't have segments matching common code-tree dirs.
    """
    candidates = set(re.findall(r"/(?:admin|merchant|vendor|api|app|user|m)/[\w/{}\-:.]+", text))

    code_segments = {"src", "dist", "node_modules", "build", "public", "static", "assets",
                     "lib", "tests", "test", "__tests__", "components", "pages"}
    file_ext_re = re.compile(r"\.(ts|tsx|js|jsx|mjs|cjs|css|scss|sass|json|html|md|sql|py|rs|go|rb|java)\b")

    filtered = []
    for c in candidates:
        segs = [s for s in c.split("/") if s]
        if any(seg in code_segments for seg in segs):
            continue
        if file_ext_re.search(c):
            continue
        c = c.rstrip(".").rstrip("-")
        if c:
            filtered.append(c)
    return list(set(filtered))


def extract_entities(text: str) -> set[str]:
    """Pull noun phrases that look like entities (heuristic)."""
    candidates = set()
    for m in re.finditer(
        r"\b(invoice|order|product|user|customer|account|payment|credit|design|task|review|comment|payout|shipment|vendor|merchant|inventory|catalog|listing|coupon|discount|notification|webhook|setting|preference|role|permission|tag|category|brand|file|attachment|message|thread)s?\b",
        text, re.I,
    ):
        candidates.add(m.group(1).lower())
    return candidates


def _resolve_vg_load() -> str | None:
    """Find the vg-load shell helper. Prefer .claude mirror, fall back to scripts/."""
    for cand in (".claude/scripts/vg-load.sh", "scripts/vg-load.sh"):
        if Path(cand).exists():
            return cand
    found = shutil.which("vg-load")
    return found


def _load_via_vg_load(phase_arg: str, artifact: str, mode: str = "index") -> str | None:
    """Invoke vg-load --phase X --artifact Y --<mode>. Return stdout or None."""
    helper = _resolve_vg_load()
    if not helper:
        return None
    cmd = ["bash", helper, "--phase", phase_arg, "--artifact", artifact, f"--{mode}", "--quiet"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        print(f"[roam-discover] vg-load invoke failed: {e}", file=sys.stderr)
        return None
    if out.returncode != 0:
        # Quietly fall through; caller will try the index file directly.
        if out.stderr:
            print(f"[roam-discover] vg-load rc={out.returncode}: {out.stderr.strip()[:200]}", file=sys.stderr)
        return None
    return out.stdout


def _load_index_text(phase_dir: Path, artifact_subdir: str, vg_load_phase: str | None, artifact_name: str) -> tuple[str, str] | None:
    """Resolve the SLIM index for an artifact.

    Order of preference:
      1) vg-load --phase X --artifact Y --index
      2) <phase_dir>/<ARTIFACT_SUBDIR>/index.md flat read
      3) <phase_dir>/<ARTIFACT>.md flat read CAPPED at FLAT_READ_BYTE_CAP

    Returns (label, text) or None when nothing found.
    """
    if vg_load_phase:
        body = _load_via_vg_load(vg_load_phase, artifact_name, mode="index")
        if body:
            return (f"vg-load:{artifact_name}:index", body)

    idx = phase_dir / artifact_subdir / "index.md"
    if idx.exists():
        return (f"{artifact_subdir}/index.md", idx.read_text(encoding="utf-8", errors="replace"))

    flat = phase_dir / f"{artifact_subdir}.md"
    if flat.exists():
        raw = flat.read_text(encoding="utf-8", errors="replace")
        if len(raw) > FLAT_READ_BYTE_CAP:
            print(
                f"[roam-discover] WARN: {flat.name} is {len(raw)} bytes — capped at "
                f"{FLAT_READ_BYTE_CAP} (no vg-load index available). Consider running "
                f"/vg:blueprint to split into per-task files.",
                file=sys.stderr,
            )
            raw = raw[:FLAT_READ_BYTE_CAP]
        return (f"{flat.name} (flat, capped)", raw)
    return None


def _load_crud_surfaces(phase_dir: Path) -> tuple[str, dict] | None:
    """Load the AUTHORITATIVE CRUD-SURFACES.md JSON block.

    The file's body wraps a single ```json fence. Returns (label, parsed_dict)
    or None when missing or malformed.
    """
    p = phase_dir / "CRUD-SURFACES.md"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"```json\s*\n(.*?)\n```", text, re.S)
    if not m:
        print(f"[roam-discover] WARN: CRUD-SURFACES.md present but no ```json block — falling back to heuristic only", file=sys.stderr)
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"[roam-discover] WARN: CRUD-SURFACES.md JSON parse failed: {e}", file=sys.stderr)
        return None
    return ("CRUD-SURFACES.md", data)


_OP_TO_CRUD = {
    "list": "R",
    "detail": "R",
    "view": "R",
    "show": "R",
    "read": "R",
    "create": "C",
    "new": "C",
    "add": "C",
    "update": "U",
    "edit": "U",
    "patch": "U",
    "approve": "U",
    "reject": "U",
    "delete": "D",
    "remove": "D",
}


def _surfaces_from_crud_block(crud_data: dict) -> list[dict]:
    """Translate CRUD-SURFACES.md `resources[]` into surface rows.

    Each resource → 1 surface row. URL is the resource's first base path /
    canonical route hint when present; otherwise a placeholder `?` (commander
    will fill in). Role is `scope` or first entry under `roles`.
    """
    out: list[dict] = []
    resources = crud_data.get("resources") or []
    for i, r in enumerate(resources, 1):
        if not isinstance(r, dict):
            continue
        name = r.get("name") or r.get("entity") or f"resource_{i}"

        # URL hint — try platforms.web.routes[0], then base.path, then resource.url
        url = "?"
        platforms = r.get("platforms") or {}
        web = platforms.get("web") if isinstance(platforms, dict) else None
        if isinstance(web, dict):
            routes = web.get("routes") or web.get("paths")
            if isinstance(routes, list) and routes:
                url = str(routes[0])
        if url == "?":
            base = r.get("base") or {}
            for key in ("path", "route", "url"):
                if base.get(key):
                    url = str(base[key])
                    break
        if url == "?" and r.get("url"):
            url = str(r["url"])

        # Role — scope OR base.roles[0]
        role = r.get("scope") or "?"
        if role == "?":
            base = r.get("base") or {}
            roles = base.get("roles")
            if isinstance(roles, list) and roles:
                role = str(roles[0])

        # CRUD ops — operations[] OR keys under expected_behavior[role]
        ops_str = ""
        ops = r.get("operations") or []
        if not ops:
            eb = r.get("expected_behavior") or {}
            for v in eb.values() if isinstance(eb, dict) else []:
                if isinstance(v, dict):
                    ops = list(v.keys())
                    break
        for op in ops:
            letter = _OP_TO_CRUD.get(str(op).lower())
            if letter and letter not in ops_str:
                ops_str += letter
        if not ops_str:
            ops_str = "R"

        out.append({
            "id": f"S{i:02d}",
            "url": url,
            "role": str(role),
            "entity": str(name).lower(),
            "crud": ops_str,
            "sub_views": "",
            "_origin": "CRUD-SURFACES.md",
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--max-surfaces", type=int, default=50)
    ap.add_argument(
        "--use-vg-load-index",
        action="store_true",
        default=True,
        help="Consume PLAN/API-CONTRACTS via vg-load --index (default ON, round-2 D1/D2).",
    )
    ap.add_argument(
        "--no-vg-load-index",
        dest="use_vg_load_index",
        action="store_false",
        help="Force flat read (debug only — capped at 64KB per source).",
    )
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    if not phase_dir.exists():
        print(f"[roam-discover] phase dir missing: {phase_dir}", file=sys.stderr)
        return 2

    # Resolve phase name for vg-load (trailing component, e.g. "7.14")
    phase_name = phase_dir.name if args.use_vg_load_index else None
    # Allow VG_PHASES_DIR override to point vg-load at a non-default root
    vg_load_phase = phase_name

    sources: list[tuple[str, str]] = []
    crud_data: dict | None = None

    # 1) AUTHORITATIVE — CRUD-SURFACES.md
    crud_load = _load_crud_surfaces(phase_dir)
    if crud_load:
        sources.append((crud_load[0], "<JSON>"))
        crud_data = crud_load[1]

    # 2) PLAN.md via vg-load --index (preferred)
    plan_load = _load_index_text(phase_dir, "PLAN", vg_load_phase, "plan")
    if plan_load:
        sources.append(plan_load)

    # 3) API-CONTRACTS via vg-load --index
    contracts_load = _load_index_text(phase_dir, "API-CONTRACTS", vg_load_phase, "contracts")
    if contracts_load:
        sources.append(contracts_load)

    # 4) Small / pre-filtered docs — KEEP-FLAT
    for f in ("CONTEXT.md", "RUNTIME-MAP.md", "RUNTIME-MAP-DRAFT.md"):
        p = phase_dir / f
        if p.exists():
            sources.append((f, p.read_text(encoding="utf-8", errors="replace")))

    if not sources:
        print(
            f"[roam-discover] no source artifacts in {phase_dir} — phase too early?",
            file=sys.stderr,
        )
        return 2

    # Heuristic surfaces from text sources (excluding the crud-surfaces JSON
    # placeholder, which is structured)
    text_corpus = "\n".join(t for label, t in sources if t != "<JSON>")
    routes = extract_routes(text_corpus)
    entities = extract_entities(text_corpus)

    surfaces: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()

    # PASS 1 — authoritative CRUD-SURFACES rows
    if crud_data:
        for s in _surfaces_from_crud_block(crud_data):
            key = (s["entity"], s["url"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            surfaces.append(s)
            if len(surfaces) >= args.max_surfaces:
                break

    # PASS 2 — heuristic route surfaces (augment, do not replace)
    next_idx = len(surfaces) + 1
    for route in sorted(routes):
        if len(surfaces) >= args.max_surfaces:
            break
        role = (
            "admin" if "/admin/" in route
            else "merchant" if "/merchant/" in route
            else "vendor" if "/vendor/" in route
            else "user"
        )
        entity = next((e for e in entities if e in route.lower()), "?")
        crud = ""
        for kw, op in CRUD_KEYWORDS.items():
            if kw in route.lower() and op not in crud:
                crud += op
        if not crud:
            crud = "R"
        key = (entity, route)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        surfaces.append({
            "id": f"S{next_idx:02d}",
            "url": route,
            "role": role,
            "entity": entity,
            "crud": crud,
            "sub_views": "",
            "_origin": "heuristic",
        })
        next_idx += 1

    # Write SURFACES.md
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    src_labels = ", ".join(label for label, _ in sources)
    lines = [
        f"# Surfaces — Phase {phase_dir.name}",
        "",
        f"Auto-discovered from: {src_labels}",
        f"Total: {len(surfaces)} (max cap: {args.max_surfaces})",
        "",
        "| ID  | URL | Role | Entity | CRUD | Sub-views | Source |",
        "|-----|-----|------|--------|------|-----------|--------|",
    ]
    for s in surfaces:
        lines.append(
            f"| {s['id']} | `{s['url']}` | {s['role']} | {s['entity']} | "
            f"{s['crud']} | {s['sub_views']} | {s.get('_origin', 'heuristic')} |"
        )

    lines += [
        "",
        "**Origin column:**",
        "- `CRUD-SURFACES.md` — authoritative resource contract (round-2 D2 fix).",
        "- `heuristic` — route + entity inference from PLAN/CONTEXT/contracts. Edit "
        "manually before composing briefs if URL/entity guess is wrong.",
        "",
        "**Loader path:** PLAN/API-CONTRACTS read via `vg-load --index` (slim TOC) "
        "when available; flat read is a capped fallback (64KB per file).",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"[roam-discover] wrote {len(surfaces)} surfaces to {out} "
        f"(crud-surfaces:{'present' if crud_data else 'absent'}, "
        f"vg-load:{'on' if args.use_vg_load_index else 'off'})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
