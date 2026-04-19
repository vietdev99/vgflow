#!/usr/bin/env python3
"""
phase-recon.py — Phase reconnaissance: inventory, classify, recommend.

Before any /vg:* command routes or runs a step, call this script to:
  1. Inventory every file in ${PHASE_DIR}/
  2. Classify into 10 buckets (v6_current / v5_numbered_plan / legacy_gsd /
     legacy_superseded / versioned_rot / scan_intermediate / work_intermediate /
     user_convention / v6_marker / orphan)
  3. Detect pipeline position per step (specs/scope/blueprint/build/review/test/accept)
  4. Propose migration candidates (legacy → V6 artifact)
  5. Flag rot (versioned files, stale intermediates)
  6. Write .recon-state.json (machine) + .recon-report.md (human)
  7. Return a recommended_action the caller routes on

READ-ONLY. Does NOT migrate, archive, or delete anything. Use phase-migrate.py
for mutations.

USAGE
  python3 phase-recon.py --phase-dir PATH [--profile PROFILE] [--fresh] [--quiet]
  python3 phase-recon.py --phase-dir PATH --json-only    # prints state JSON to stdout

EXIT CODES
  0 ok
  1 bad args / phase dir missing
  2 parse error (corrupted file)
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_PROFILES = {
    "web-fullstack",
    "web-frontend-only",
    "web-backend-only",
    "cli-tool",
    "library",
}

PIPELINE_STEPS = ["specs", "scope", "blueprint", "build", "review", "test", "accept"]

# ---- Classification tables -------------------------------------------------

V6_CANONICAL = {
    "SPECS.md",
    "CONTEXT.md",
    "PLAN.md",
    "API-CONTRACTS.md",
    "TEST-GOALS.md",
    "GOAL-COVERAGE-MATRIX.md",
    "RUNTIME-MAP.json",
    "RUNTIME-MAP.md",
    "RIPPLE-ANALYSIS.md",
    "SUMMARY.md",
    "SANDBOX-TEST.md",
    "UAT.md",
    "REVIEW-DIRECTION.md",
    "FLOW-SPEC.md",
    "UI-SPEC.md",
    "TEST-PREP.md",
    "GAPS-REPORT.md",
}

# Legacy artifacts with migration target (need content transformation)
LEGACY_MIGRATE: dict[str, dict[str, str]] = {
    "RESEARCH.md":              {"target": "SPECS.md",                 "type": "seed"},
    "DISCUSSION-LOG.md":        {"target": "CONTEXT.md",               "type": "extract_decisions"},
    "DISCUSSION-LOG-2.md":      {"target": "CONTEXT.md",               "type": "extract_decisions"},
    "DEPTH-INPUT.md":           {"target": "CONTEXT.md",               "type": "merge_decisions"},
    "BUSINESS-FLOW-SPECS.md":   {"target": "TEST-GOALS.md",            "type": "flow_to_goals"},
    "BUSINESS-TEST-SPEC.md":    {"target": "TEST-GOALS.md",            "type": "specs_to_goals"},
    "TEST-SPEC.md":             {"target": "TEST-GOALS.md",            "type": "specs_to_goals"},
    "TEST-ASSERTIONS.md":       {"target": "TEST-GOALS.md",            "type": "append_criteria"},
    "PARALLEL-TEST-PLAN.md":    {"target": "PLAN.md",                  "type": "wave_structure"},
    "DEV-TASKS.md":             {"target": "PLAN.md",                  "type": "merge_tasks"},
    "GAP-PLAN.md":              {"target": "PLAN.md",                  "type": "append_gap_wave"},
    "GAP-PLAN-ROUND2.md":       {"target": "PLAN.md",                  "type": "append_gap_wave"},
    "GAP-SUMMARY.md":           {"target": "SUMMARY.md",               "type": "append_gap_wave"},
    "GAP-SUMMARY-ROUND2.md":    {"target": "SUMMARY.md",               "type": "append_gap_wave"},
    "REVIEW-FEEDBACK.md":       {"target": "GOAL-COVERAGE-MATRIX.md",  "type": "extract_goal_status"},
    "HUMAN-UAT.md":             {"target": "UAT.md",                   "type": "rename"},
    "SPEC.md":                  {"target": "SPECS.md",                 "type": "rename"},
}

# Legacy artifacts superseded cleanly — archive-only
LEGACY_SUPERSEDED: dict[str, str] = {
    "COMPONENT-MAP.md":            "superseded by RUNTIME-MAP.json",
    "NAVIGATION-MAP.md":           "superseded by RUNTIME-MAP.json",
    "PAGE-SPECS.md":               "split into RUNTIME-MAP.json + TEST-GOALS.md",
    "AUDIT-ADMIN.md":              "superseded by RUNTIME-MAP.json (role=admin)",
    "AUDIT-ADVERTISER.md":         "superseded by RUNTIME-MAP.json (role=advertiser)",
    "AUDIT-PUBLISHER.md":          "superseded by RUNTIME-MAP.json (role=publisher)",
    "AUDIT-INTERNAL-ADMIN.md":     "superseded by RUNTIME-MAP.json (role=internal_admin)",
    "MODULE-AUDIT.md":             "superseded by RUNTIME-MAP.json",
    "PLAN-monolithic-backup.md":   "backup of old monolithic plan — obsolete",
    "REVIEWS.md":                  "superseded by GOAL-COVERAGE-MATRIX.md + RIPPLE-ANALYSIS.md",
    "VERIFICATION.md":             "superseded by SANDBOX-TEST.md",
    "VALIDATION.md":               "superseded by SANDBOX-TEST.md",
    "RESULT.md":                   "superseded by SANDBOX-TEST.md",
    "SUMMARY.md.v1":               "intermediate backup",
    "SUMMARY.md.v2":               "intermediate backup",
    "SUMMARY.md.v3":               "intermediate backup",
    "PLAN.md.v1":                  "intermediate backup",
    "PLAN.md.v2":                  "intermediate backup",
    "PLAN.md.v3":                  "intermediate backup",
}

# User preference — KEEP, never treat as rot
USER_CONVENTION = {
    "SUMMARY-VI.md": "Vietnamese summary (user convention)",
}

# Work-time intermediates — clean at accept step
WORK_INTERMEDIATES = {
    ".ripple.json",
    ".ripple-input.txt",
    ".callers.json",
    ".god-nodes.json",
    "element-counts.json",
}
WORK_INTERMEDIATE_DIRS = {".wave-context", ".wave-tasks"}

# Recon-owned files (don't reclassify, don't list)
RECON_OWNED = {".recon-state.json", ".recon-report.md"}

# Regex patterns
RE_V5_NUMBERED_PLAN = re.compile(r"^\d+(?:\.\d+)*-\d+-PLAN(?:-[\w-]+)?\.md$")
RE_V5_NUMBERED_SUMMARY = re.compile(r"^\d+(?:\.\d+)*-\d+-SUMMARY(?:-[\w-]+)?\.md$")
RE_PHASE_PREFIXED_V6 = re.compile(
    r"^\d+(?:\.\d+)*-"
    r"(UAT|SANDBOX-TEST|SUMMARY|PLAN|SPECS|CONTEXT|TEST-GOALS|API-CONTRACTS|"
    r"GOAL-COVERAGE-MATRIX|REVIEW-FEEDBACK|BUSINESS-TEST-SPEC|TEST-SPEC|"
    r"RESEARCH|DEPTH-INPUT|COMPONENT-MAP|DISCUSSION-LOG|DISCUSSION-LOG-2|"
    r"VERIFICATION|HUMAN-UAT|GAP-PLAN|GAP-PLAN-ROUND2|GAP-SUMMARY|"
    r"GAP-SUMMARY-ROUND2|RESULT|SUMMARY-VI)\.md$"
)
RE_VERSIONED_ROT = re.compile(r"^(?P<base>.+?)-v(?P<ver>\d+)\.(?P<ext>md|json)$")
RE_SCAN_INTERMEDIATE = re.compile(
    r"^(?:scan-.*\.json|probe-.*\.json|discovery-state\.json|"
    r"view-assignments\.json|nav-discovery\.json|contract-verify\.json)$"
)


# ---- Classification --------------------------------------------------------

def _strip_phase_prefix(name: str, phase_num: str) -> str:
    """Strip '07.3-' style prefix if present. Returns stripped name."""
    # Match phase number at start (with optional leading zero variants)
    for prefix in (f"{phase_num}-", f"0{phase_num}-"):
        if name.startswith(prefix):
            return name[len(prefix):]
    # Also handle generic phase prefix (any numeric-dotted prefix)
    m = re.match(r"^\d+(?:\.\d+)*-(.+)$", name)
    if m:
        return m.group(1)
    return name


def classify_file(name: str, phase_num: str) -> tuple[str, dict[str, Any]]:
    """
    Classify one filename into a bucket. Returns (bucket, meta).
    Meta may contain: canonical_name, reason, suggested_target, rot_canonical.
    """
    meta: dict[str, Any] = {}

    # User convention — highest priority
    if name in USER_CONVENTION:
        meta["reason"] = USER_CONVENTION[name]
        return "user_convention", meta

    # Recon-owned (skip, but flag so we don't reclassify)
    if name in RECON_OWNED:
        return "recon_meta", meta

    # Work intermediates
    if name in WORK_INTERMEDIATES:
        return "work_intermediate", meta

    # V6 canonical (unprefixed)
    if name in V6_CANONICAL:
        meta["canonical_name"] = name
        return "v6_current", meta

    # V6 canonical with phase prefix (e.g., 07.8-UAT.md, 7.3-SANDBOX-TEST.md)
    if RE_PHASE_PREFIXED_V6.match(name):
        stripped = _strip_phase_prefix(name, phase_num)
        if stripped in V6_CANONICAL or stripped in LEGACY_MIGRATE or stripped in LEGACY_SUPERSEDED:
            # Determine whether the stripped name is V6 or legacy
            if stripped in V6_CANONICAL:
                meta["canonical_name"] = stripped
                return "v6_current", meta
            if stripped in LEGACY_MIGRATE:
                meta.update(LEGACY_MIGRATE[stripped])
                meta["canonical_name"] = stripped
                return "legacy_gsd", meta
            if stripped in LEGACY_SUPERSEDED:
                meta["reason"] = LEGACY_SUPERSEDED[stripped]
                meta["canonical_name"] = stripped
                return "legacy_superseded", meta

    # V5 numbered plan/summary (e.g., 07.3-01-PLAN.md)
    if RE_V5_NUMBERED_PLAN.match(name):
        return "v5_numbered_plan", meta
    if RE_V5_NUMBERED_SUMMARY.match(name):
        return "v5_numbered_summary", meta

    # Legacy migrate (by basename)
    if name in LEGACY_MIGRATE:
        meta.update(LEGACY_MIGRATE[name])
        return "legacy_gsd", meta

    # Legacy superseded
    if name in LEGACY_SUPERSEDED:
        meta["reason"] = LEGACY_SUPERSEDED[name]
        return "legacy_superseded", meta

    # Versioned rot (base-v{N}.ext) — but only if version ≥ 2
    m = RE_VERSIONED_ROT.match(name)
    if m and int(m.group("ver")) >= 2:
        base = m.group("base")
        ext = m.group("ext")
        meta["canonical_target"] = f"{base}.{ext}"
        meta["version"] = int(m.group("ver"))
        return "versioned_rot", meta

    # Scan intermediates
    if RE_SCAN_INTERMEDIATE.match(name):
        return "scan_intermediate", meta

    return "orphan", meta


# ---- Scan phase dir --------------------------------------------------------

def scan_phase_dir(phase_dir: Path, phase_num: str) -> dict[str, Any]:
    """Walk phase dir (top-level only for files; also note key sub-dirs)."""
    if not phase_dir.exists() or not phase_dir.is_dir():
        raise FileNotFoundError(f"Phase dir not found: {phase_dir}")

    entries = []
    for p in sorted(phase_dir.iterdir()):
        if p.is_dir():
            name = p.name
            # Treat known work intermediate dirs as special entries
            if name in WORK_INTERMEDIATE_DIRS:
                entries.append({
                    "name": name,
                    "path": str(p.relative_to(phase_dir)),
                    "is_dir": True,
                    "bucket": "work_intermediate",
                    "meta": {"reason": "wave-level scratch space"},
                })
            elif name == ".step-markers":
                entries.append({
                    "name": name,
                    "path": str(p.relative_to(phase_dir)),
                    "is_dir": True,
                    "bucket": "v6_marker",
                    "meta": {"markers": sorted(f.stem for f in p.glob("*.done"))},
                })
            elif name == ".archive":
                entries.append({
                    "name": name,
                    "path": str(p.relative_to(phase_dir)),
                    "is_dir": True,
                    "bucket": "archive",
                    "meta": {"timestamps": sorted(d.name for d in p.iterdir() if d.is_dir())},
                })
            else:
                # checkpoints, crossai, screenshots, generated-tests, etc.
                entries.append({
                    "name": name,
                    "path": str(p.relative_to(phase_dir)),
                    "is_dir": True,
                    "bucket": "keep_subdir",
                    "meta": {"reason": "pipeline subdir — keep as-is"},
                })
            continue

        # Regular file
        try:
            stat = p.stat()
        except OSError:
            continue
        bucket, meta = classify_file(p.name, phase_num)
        entries.append({
            "name": p.name,
            "path": str(p.relative_to(phase_dir)),
            "is_dir": False,
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "bucket": bucket,
            "meta": meta,
        })

    return {"entries": entries}


# ---- Pipeline position detection -------------------------------------------

def _find_first_canonical(entries: list[dict], canonical_name: str) -> dict | None:
    """Find entry where meta.canonical_name OR name == canonical_name."""
    for e in entries:
        if e["is_dir"]:
            continue
        if e["name"] == canonical_name:
            return e
        if e.get("meta", {}).get("canonical_name") == canonical_name:
            return e
    return None


def _find_first_with_name(entries: list[dict], names: set[str]) -> dict | None:
    for e in entries:
        if not e["is_dir"] and e["name"] in names:
            return e
    return None


def _find_all_matching(entries: list[dict], regex: re.Pattern) -> list[dict]:
    return [e for e in entries if not e["is_dir"] and regex.match(e["name"])]


def determine_pipeline_position(entries: list[dict], profile: str) -> dict[str, Any]:
    """Returns per-step: status + v6_artifact + legacy_sources + marker."""
    # Marker presence
    marker_entry = next((e for e in entries if e["is_dir"] and e["name"] == ".step-markers"), None)
    markers = set(marker_entry["meta"].get("markers", [])) if marker_entry else set()

    def marker_has(*patterns):
        return any(any(pat in m for pat in patterns) for m in markers)

    # Specs: SPECS.md
    specs = _find_first_canonical(entries, "SPECS.md")
    specs_legacy = [e["name"] for e in entries
                    if not e["is_dir"]
                    and e["name"] in {"SPEC.md", "REQUIREMENTS.md", "BRIEF.md"}]
    specs_status = ("done" if specs else
                    "legacy_only" if specs_legacy else
                    "missing")

    # Scope: CONTEXT.md (SPECS tracked separately above)
    context = _find_first_canonical(entries, "CONTEXT.md")
    scope_legacy = [e["name"] for e in entries
                    if not e["is_dir"]
                    and e["name"] in {"RESEARCH.md",
                                      "DISCUSSION-LOG.md", "DISCUSSION-LOG-2.md",
                                      "DEPTH-INPUT.md"}]
    scope_status = ("done" if context else
                    "legacy_only" if scope_legacy else
                    "missing")

    # Blueprint: PLAN + API-CONTRACTS + TEST-GOALS
    plan = _find_first_canonical(entries, "PLAN.md")
    api = _find_first_canonical(entries, "API-CONTRACTS.md")
    goals = _find_first_canonical(entries, "TEST-GOALS.md")
    numbered_plans = _find_all_matching(entries, RE_V5_NUMBERED_PLAN)
    bp_legacy = [e["name"] for e in entries
                 if not e["is_dir"]
                 and e["name"] in {"PARALLEL-TEST-PLAN.md", "DEV-TASKS.md",
                                   "BUSINESS-TEST-SPEC.md", "TEST-SPEC.md",
                                   "TEST-ASSERTIONS.md", "BUSINESS-FLOW-SPECS.md",
                                   "GAP-PLAN.md", "GAP-PLAN-ROUND2.md",
                                   "PLAN-monolithic-backup.md"}]
    bp_legacy += [e["name"] for e in numbered_plans]
    if plan and api and goals:
        bp_status = "done"
    elif plan or api or goals:
        bp_status = "partial"
    elif bp_legacy:
        bp_status = "legacy_only"
    else:
        bp_status = "missing"

    # Build: SUMMARY + build markers
    summary = _find_first_canonical(entries, "SUMMARY.md")
    numbered_summaries = _find_all_matching(entries, RE_V5_NUMBERED_SUMMARY)
    b_legacy = [e["name"] for e in numbered_summaries]
    b_legacy += [e["name"] for e in entries
                 if not e["is_dir"]
                 and e["name"] in {"GAP-SUMMARY.md", "GAP-SUMMARY-ROUND2.md"}]
    if summary and marker_has("build"):
        b_status = "done"
    elif summary:
        b_status = "partial"
    elif b_legacy:
        b_status = "legacy_only"
    else:
        b_status = "missing"

    # Review: RUNTIME-MAP.json (required for web profiles) + GOAL-COVERAGE-MATRIX
    runtime = _find_first_canonical(entries, "RUNTIME-MAP.json")
    coverage = _find_first_canonical(entries, "GOAL-COVERAGE-MATRIX.md")
    r_legacy = [e["name"] for e in entries
                if not e["is_dir"]
                and e["name"] in {"NAVIGATION-MAP.md", "PAGE-SPECS.md",
                                  "AUDIT-ADMIN.md", "AUDIT-ADVERTISER.md",
                                  "AUDIT-PUBLISHER.md", "AUDIT-INTERNAL-ADMIN.md",
                                  "MODULE-AUDIT.md", "COMPONENT-MAP.md",
                                  "REVIEW-FEEDBACK.md", "REVIEWS.md"}]
    if profile in ("web-fullstack", "web-frontend-only"):
        if runtime and coverage:
            r_status = "done"
        elif runtime or coverage:
            r_status = "partial"
        elif r_legacy:
            r_status = "legacy_only"
        else:
            r_status = "missing"
    else:
        # Backend-only / library / cli-tool don't need RUNTIME-MAP
        if coverage:
            r_status = "done"
        else:
            r_status = "missing"

    # Test: SANDBOX-TEST.md (may be phase-prefixed)
    sandbox = _find_first_canonical(entries, "SANDBOX-TEST.md")
    versioned_sandbox = [e for e in entries
                        if not e["is_dir"]
                        and e.get("bucket") == "versioned_rot"
                        and e.get("meta", {}).get("canonical_target", "").startswith("SANDBOX-TEST")]
    t_legacy = [e["name"] for e in entries
                if not e["is_dir"]
                and e["name"] in {"VERIFICATION.md", "VALIDATION.md", "RESULT.md"}]
    t_legacy += [e["name"] for e in versioned_sandbox]
    if sandbox:
        t_status = "done"
    elif versioned_sandbox:
        t_status = "legacy_only"  # versioned rot but has the artifact content
    elif t_legacy:
        t_status = "legacy_only"
    else:
        t_status = "missing"

    # Accept: UAT.md
    uat = _find_first_canonical(entries, "UAT.md")
    a_legacy = [e["name"] for e in entries
                if not e["is_dir"]
                and (e["name"] == "HUMAN-UAT.md"
                     or (e.get("bucket") == "versioned_rot"
                         and e.get("meta", {}).get("canonical_target", "").startswith("UAT")))]
    if uat and marker_has("accept"):
        a_status = "done"
    elif uat:
        a_status = "partial"
    elif a_legacy:
        a_status = "legacy_only"
    else:
        a_status = "missing"

    return {
        "specs":     {"status": specs_status,
                      "v6_artifacts": [specs["name"]] if specs else [],
                      "legacy_sources": specs_legacy},
        "scope":     {"status": scope_status,
                      "v6_artifacts": [context["name"]] if context else [],
                      "legacy_sources": scope_legacy},
        "blueprint": {"status": bp_status,
                      "v6_artifacts": [e["name"] for e in (plan, api, goals) if e],
                      "legacy_sources": bp_legacy},
        "build":     {"status": b_status,
                      "v6_artifacts": [summary["name"]] if summary else [],
                      "legacy_sources": b_legacy,
                      "marker_present": marker_has("build")},
        "review":    {"status": r_status,
                      "v6_artifacts": [e["name"] for e in (runtime, coverage) if e],
                      "legacy_sources": r_legacy,
                      "marker_present": marker_has("review")},
        "test":      {"status": t_status,
                      "v6_artifacts": [sandbox["name"]] if sandbox else [],
                      "legacy_sources": t_legacy,
                      "marker_present": marker_has("test")},
        "accept":    {"status": a_status,
                      "v6_artifacts": [uat["name"]] if uat else [],
                      "legacy_sources": a_legacy,
                      "marker_present": marker_has("accept")},
    }


# ---- Phase type classification ---------------------------------------------

def determine_phase_type(position: dict[str, Any], buckets: dict[str, list]) -> str:
    """
    v6_native       — has SPECS+CONTEXT+PLAN+API-CONTRACTS+TEST-GOALS
                      (at least scope + blueprint V6 done)
    v5_iterative    — numbered PLAN/SUMMARY present, no or partial V6 canonicals
    legacy_gsd      — has RESEARCH / DISCUSSION-LOG / PAGE-SPECS / AUDIT-* etc.
                      and NO V6 blueprint artifacts
    hybrid          — mix of legacy + some V6 artifacts (any mismatch)
    new             — empty or nearly empty
    """
    has_v6_scope = position["scope"]["status"] == "done"
    has_v6_bp = position["blueprint"]["status"] == "done"
    has_any_v6 = any(p["v6_artifacts"] for p in position.values())
    has_legacy = any(
        p.get("legacy_sources") and p["status"] == "legacy_only"
        for p in position.values()
    )
    has_numbered = bool(buckets.get("v5_numbered_plan"))
    has_legacy_bucket = bool(buckets.get("legacy_gsd") or buckets.get("legacy_superseded"))
    has_any_content = bool(
        buckets.get("v6_current")
        or buckets.get("legacy_gsd")
        or buckets.get("legacy_superseded")
        or has_numbered
    )

    if not has_any_content:
        return "new"
    if has_v6_scope and has_v6_bp and not has_legacy_bucket and not has_numbered:
        return "v6_native"
    if has_numbered and not has_v6_bp:
        return "v5_iterative"
    if has_legacy_bucket and not has_any_v6:
        return "legacy_gsd"
    if has_legacy_bucket or has_numbered or has_legacy:
        return "hybrid"
    if has_any_v6:
        return "v6_native"
    return "unknown"


# ---- Migration & rot candidates --------------------------------------------

def build_migration_candidates(entries: list[dict], phase_dir: Path) -> list[dict]:
    """List legacy_gsd files → suggested V6 target."""
    candidates: list[dict] = []
    existing_names = {e["name"] for e in entries if not e["is_dir"]}
    seq = 0
    for e in entries:
        if e["is_dir"] or e.get("bucket") != "legacy_gsd":
            continue
        # Get mapping from meta (set during classification)
        target = e.get("meta", {}).get("target")
        mig_type = e.get("meta", {}).get("type", "unknown")
        if not target:
            # Maybe phase-prefixed — look up by canonical_name
            canonical = e.get("meta", {}).get("canonical_name")
            if canonical and canonical in LEGACY_MIGRATE:
                target = LEGACY_MIGRATE[canonical]["target"]
                mig_type = LEGACY_MIGRATE[canonical]["type"]
        if not target:
            continue

        target_exists = target in existing_names
        seq += 1
        candidates.append({
            "id": f"M{seq:02d}",
            "source": e["name"],
            "target": target,
            "type": mig_type,
            "target_exists": target_exists,
            "priority": "conflict" if target_exists else "recommended",
            "reversible": True,
            "action": ("skip (target exists — offer archive instead)"
                       if target_exists
                       else f"{mig_type} → {target}"),
        })
    return candidates


def build_rot_list(entries: list[dict]) -> list[dict]:
    """Versioned files: keep highest version, archive others. Also stale scan files."""
    rot: list[dict] = []

    # Group versioned files by canonical target
    groups: dict[str, list[tuple[int, dict]]] = {}
    for e in entries:
        if e["is_dir"] or e.get("bucket") != "versioned_rot":
            continue
        target = e.get("meta", {}).get("canonical_target")
        ver = e.get("meta", {}).get("version")
        if target is None or ver is None:
            continue
        groups.setdefault(target, []).append((ver, e))

    existing_names = {e["name"] for e in entries if not e["is_dir"]}
    seq = 0
    for canonical, versions in groups.items():
        versions.sort(reverse=True)  # highest ver first
        max_ver, max_entry = versions[0]
        # If canonical exists, all versioned are rot
        # If canonical missing, max_ver becomes canonical (rename), rest are rot
        canonical_exists = canonical in existing_names

        for ver, entry in versions:
            seq += 1
            if not canonical_exists and entry is max_entry:
                rot.append({
                    "id": f"R{seq:02d}",
                    "file": entry["name"],
                    "action": "rename",
                    "target": canonical,
                    "reason": f"v{ver} is highest — promote to canonical",
                })
            else:
                rot.append({
                    "id": f"R{seq:02d}",
                    "file": entry["name"],
                    "action": "archive",
                    "reason": (f"superseded by {canonical}" if canonical_exists
                               else f"superseded by v{max_ver}"),
                })

    # Scan intermediates — only flag stale (>7d) or if pipeline past review
    now = datetime.now(tz=timezone.utc)
    for e in entries:
        if e["is_dir"] or e.get("bucket") != "scan_intermediate":
            continue
        try:
            mtime = datetime.fromisoformat(e["mtime"])
            age_days = (now - mtime).days
        except (KeyError, ValueError):
            age_days = 0
        if age_days > 7:
            seq += 1
            rot.append({
                "id": f"R{seq:02d}",
                "file": e["name"],
                "action": "archive",
                "reason": f"stale scan intermediate ({age_days}d old)",
            })

    # legacy_superseded items → archive straight
    for e in entries:
        if e["is_dir"] or e.get("bucket") != "legacy_superseded":
            continue
        seq += 1
        rot.append({
            "id": f"R{seq:02d}",
            "file": e["name"],
            "action": "archive",
            "reason": e.get("meta", {}).get("reason", "superseded"),
        })

    return rot


# ---- Numbered-plan consolidation candidate ---------------------------------

def build_consolidation_candidate(entries: list[dict]) -> dict | None:
    """If v5_numbered_plan bucket has 2+ files, offer consolidation into PLAN.md."""
    numbered = [e for e in entries if e.get("bucket") == "v5_numbered_plan"]
    if len(numbered) < 2:
        return None
    existing_names = {e["name"] for e in entries if not e["is_dir"]}
    return {
        "id": "C01",
        "source_files": sorted(e["name"] for e in numbered),
        "target": "PLAN.md",
        "target_exists": "PLAN.md" in existing_names,
        "type": "consolidate_waves",
        "priority": "recommended" if "PLAN.md" not in existing_names else "skip",
    }


# ---- Recommendation --------------------------------------------------------

def recommend_action(position: dict, phase_type: str, migrations: list,
                     consolidation: dict | None, phase_num: str) -> dict[str, Any]:
    """Pick the next concrete action for the user."""
    # If phase_type is legacy_gsd / v5_iterative / hybrid → recommend migration first
    pre_action = None
    if phase_type in ("legacy_gsd", "v5_iterative", "hybrid"):
        has_actionable = any(m["priority"] == "recommended" for m in migrations)
        has_consol = consolidation and consolidation.get("priority") == "recommended"
        if has_actionable or has_consol:
            pre_action = {
                "type": "migrate",
                "reason": f"Phase detected as {phase_type} — migrate legacy artifacts before routing.",
                "hint": "Run migrations via phase-recon interactive menu (phase-recon.md step R8).",
            }

    # Find first step not done
    next_step = None
    for step in PIPELINE_STEPS:
        if position[step]["status"] == "done":
            continue
        next_step = step
        break

    if next_step is None:
        return {
            "pre_action": None,
            "step": "complete",
            "reason": "All pipeline steps done — phase is complete.",
            "next_command": None,
        }

    return {
        "pre_action": pre_action,
        "step": next_step,
        "reason": (f"{next_step} status is {position[next_step]['status']}"
                   + (f" — legacy sources: {position[next_step]['legacy_sources'][:3]}"
                      if position[next_step]['legacy_sources'] else "")),
        "next_command": f"/vg:{next_step} {phase_num}",
    }


# ---- State assembly + fingerprint ------------------------------------------

def compute_fingerprint(entries: list[dict]) -> str:
    """Hash of (name, size, mtime) tuples — detects phase dir mutations."""
    h = hashlib.sha256()
    for e in sorted(entries, key=lambda x: x["path"]):
        h.update(f"{e['path']}|{e.get('size', '')}|{e.get('mtime', '')}".encode())
    return h.hexdigest()[:16]


def bucketize(entries: list[dict]) -> dict[str, list]:
    buckets: dict[str, list] = {}
    for e in entries:
        buckets.setdefault(e.get("bucket", "unknown"), []).append(e)
    return buckets


def assemble_state(phase_dir: Path, phase_num: str, profile: str) -> dict[str, Any]:
    scan = scan_phase_dir(phase_dir, phase_num)
    entries = scan["entries"]
    position = determine_pipeline_position(entries, profile)
    buckets = bucketize(entries)
    phase_type = determine_phase_type(position, buckets)
    migrations = build_migration_candidates(entries, phase_dir)
    rot = build_rot_list(entries)
    consolidation = build_consolidation_candidate(entries)
    action = recommend_action(position, phase_type, migrations, consolidation, phase_num)

    return {
        "phase": phase_num,
        "phase_dir": str(phase_dir),
        "profile": profile,
        "classified_at": datetime.now(tz=timezone.utc).isoformat(),
        "fingerprint": compute_fingerprint(entries),
        "phase_type": phase_type,
        "pipeline_position": position,
        "bucket_counts": {k: len(v) for k, v in buckets.items()},
        "migration_candidates": migrations,
        "consolidation_candidate": consolidation,
        "rot_to_archive": rot,
        "recommended_action": action,
        "entries": entries,  # full detail
    }


# ---- Cache logic -----------------------------------------------------------

def cache_is_fresh(phase_dir: Path, cached_state: dict[str, Any]) -> bool:
    """Return True iff fingerprint matches current dir scan."""
    try:
        phase_num = cached_state.get("phase", "")
        if not phase_num:
            return False
        scan = scan_phase_dir(phase_dir, phase_num)
        fp = compute_fingerprint(scan["entries"])
        return fp == cached_state.get("fingerprint")
    except Exception:
        return False


# ---- Report rendering ------------------------------------------------------

def render_report(state: dict[str, Any]) -> str:
    """Human-readable markdown report."""
    lines: list[str] = []
    p = state["pipeline_position"]
    phase = state["phase"]
    lines.append(f"# Phase {phase} — Reconnaissance Report\n")
    lines.append(f"- **Phase type:** `{state['phase_type']}`")
    lines.append(f"- **Profile:** `{state['profile']}`")
    lines.append(f"- **Classified at:** {state['classified_at']}")
    lines.append("")

    lines.append("## Pipeline position")
    lines.append("")
    lines.append("| Step | Status | V6 artifacts | Legacy sources | Marker |")
    lines.append("|------|--------|--------------|----------------|--------|")
    for step in PIPELINE_STEPS:
        s = p[step]
        v6 = ", ".join(s["v6_artifacts"]) or "—"
        leg = ", ".join(s["legacy_sources"][:3]) or "—"
        if len(s["legacy_sources"]) > 3:
            leg += f" (+{len(s['legacy_sources']) - 3})"
        mk = "✓" if s.get("marker_present") else ("—" if "marker_present" in s else "n/a")
        lines.append(f"| {step} | {s['status']} | {v6} | {leg} | {mk} |")
    lines.append("")

    # Bucket counts
    lines.append("## File buckets")
    lines.append("")
    lines.append("| Bucket | Count |")
    lines.append("|--------|-------|")
    for k, v in sorted(state["bucket_counts"].items()):
        lines.append(f"| {k} | {v} |")
    lines.append("")

    # Migration candidates
    lines.append("## Migration candidates")
    lines.append("")
    if not state["migration_candidates"]:
        lines.append("_None._")
    else:
        lines.append("| ID | Source | → Target | Type | Priority | Action |")
        lines.append("|----|--------|----------|------|----------|--------|")
        for m in state["migration_candidates"]:
            lines.append(
                f"| {m['id']} | `{m['source']}` | `{m['target']}` | {m['type']} | "
                f"{m['priority']} | {m['action']} |"
            )
    lines.append("")

    # Consolidation
    if state.get("consolidation_candidate"):
        c = state["consolidation_candidate"]
        lines.append("## Numbered plan consolidation")
        lines.append("")
        src_list = "\n".join(f"  - `{f}`" for f in c["source_files"])
        lines.append(f"- **Target:** `{c['target']}` (priority: {c['priority']})")
        lines.append(f"- **Sources ({len(c['source_files'])}):**\n{src_list}")
        lines.append("")

    # Rot
    lines.append("## Rot to archive")
    lines.append("")
    if not state["rot_to_archive"]:
        lines.append("_None._")
    else:
        lines.append("| ID | File | Action | Reason |")
        lines.append("|----|------|--------|--------|")
        for r in state["rot_to_archive"]:
            tgt = r.get("target")
            action = r["action"] + (f" → `{tgt}`" if tgt else "")
            lines.append(f"| {r['id']} | `{r['file']}` | {action} | {r['reason']} |")
    lines.append("")

    # Recommendation
    a = state["recommended_action"]
    lines.append("## Recommended next action")
    lines.append("")
    if a.get("pre_action"):
        lines.append(f"- **First:** `{a['pre_action']['type']}` — {a['pre_action']['reason']}")
        lines.append(f"  {a['pre_action'].get('hint', '')}")
    lines.append(f"- **Step:** `{a['step']}`")
    lines.append(f"- **Reason:** {a['reason']}")
    if a.get("next_command"):
        lines.append(f"- **Command:** `{a['next_command']}`")
    lines.append("")

    return "\n".join(lines)


# ---- Main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Phase reconnaissance")
    ap.add_argument("--phase-dir", required=True, type=Path)
    ap.add_argument("--profile", default="web-fullstack", choices=sorted(VALID_PROFILES))
    ap.add_argument("--fresh", action="store_true", help="Ignore cache, rescan")
    ap.add_argument("--quiet", action="store_true", help="Minimal stdout")
    ap.add_argument("--json-only", action="store_true", help="Print state JSON to stdout, no file writes")
    args = ap.parse_args()

    phase_dir: Path = args.phase_dir
    if not phase_dir.exists():
        print(f"⛔ Phase dir missing: {phase_dir}", file=sys.stderr)
        sys.exit(1)

    # Derive phase num from dir name (handle both "7.3-foo" and "07.3-foo")
    m = re.match(r"^0?(\d+(?:\.\d+)*)", phase_dir.name)
    phase_num = m.group(1) if m else phase_dir.name

    state_path = phase_dir / ".recon-state.json"
    report_path = phase_dir / ".recon-report.md"

    # Cache check
    if not args.fresh and state_path.exists() and not args.json_only:
        try:
            cached = json.loads(state_path.read_text(encoding="utf-8"))
            if cache_is_fresh(phase_dir, cached):
                if not args.quiet:
                    print(f"✓ recon cache fresh (fingerprint {cached['fingerprint']})")
                    print(f"STATE_FILE: {state_path}")
                    print(f"REPORT_FILE: {report_path}")
                    print(f"PHASE_TYPE: {cached['phase_type']}")
                    print(f"RECOMMENDED_STEP: {cached['recommended_action']['step']}")
                else:
                    print(f"STATE_FILE: {state_path}")
                return 0
        except (json.JSONDecodeError, KeyError):
            pass  # fall through to fresh scan

    # Fresh scan
    try:
        state = assemble_state(phase_dir, phase_num, args.profile)
    except FileNotFoundError as e:
        print(f"⛔ {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"⛔ Recon parse error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json_only:
        print(json.dumps(state, indent=2))
        return 0

    # Write state + report
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    report_path.write_text(render_report(state), encoding="utf-8")

    if not args.quiet:
        # Short summary to stdout
        print(f"═══ Phase {phase_num} Reconnaissance ═══")
        print(f"Phase type:     {state['phase_type']}")
        print(f"Bucket summary:")
        for k, v in sorted(state["bucket_counts"].items()):
            print(f"  {k:25s} {v}")
        a = state["recommended_action"]
        if a.get("pre_action"):
            print(f"⚠ Pre-action needed: {a['pre_action']['type']}")
            print(f"    {a['pre_action']['reason']}")
        print(f"Recommended step: {a['step']}")
        print(f"Next command:     {a.get('next_command') or '—'}")
        print(f"State:  {state_path}")
        print(f"Report: {report_path}")
    else:
        print(f"STATE_FILE: {state_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
