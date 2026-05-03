"""
Phase D — orphan validator triage orchestrator subcommands.

Spec: .vg/workflow-hardening-v2.7/SPEC-D.md sections 1-7.

Three subcommands implemented as functions; __main__.py registers them.

  orphans-list     — compute 3-way diff (script vs registry vs dispatch),
                     partition deterministically into 3 agent slices,
                     write .vg/workflow-hardening-v2.7/orphan-list.json.
  orphans-collect  — merge per-agent decision JSONs into a single file,
                     validate every assigned validator has a decision,
                     aggregate stats, write orphan-decisions.json.
  orphans-apply    — apply WIRE/RETIRE/MERGE/NEEDS_HUMAN outcomes:
                     wire entries into registry+dispatch, git-mv retired
                     scripts to _retired/, tag pending entries.

The triage RUN itself (3 sub-agents producing decision JSONs) is OUT OF
SCOPE for this module. Sub-agents write
.vg/workflow-hardening-v2.7/orphan-decisions-{1,2,3}.json which
orphans-collect then merges.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml  # pyyaml is present (used by other scripts)

# Allow `python -m vg_orchestrator orphans-* …` style invocation as well as
# direct `python __main__.py …`. _repo_root is sibling.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _repo_root import find_repo_root  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PHASE_DIR_REL = Path(".vg") / "workflow-hardening-v2.7"
VALIDATORS_DIR_REL = Path(".claude") / "scripts" / "validators"
RETIRED_DIR_REL = VALIDATORS_DIR_REL / "_retired"

REGISTRY_REL = VALIDATORS_DIR_REL / "registry.yaml"
DISPATCH_REL = VALIDATORS_DIR_REL / "dispatch-manifest.json"

ORPHAN_LIST_NAME = "orphan-list.json"
DECISIONS_MERGED_NAME = "orphan-decisions.json"
DECISIONS_AGENT_TEMPLATE = "orphan-decisions-{n}.json"

VALID_OUTCOMES = {"WIRE", "RETIRE", "MERGE", "NEEDS_HUMAN"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return find_repo_root(__file__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_registry(repo: Path) -> dict:
    path = repo / REGISTRY_REL
    if not path.exists():
        return {"validators": []}
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not data.get("validators"):
        data["validators"] = []
    return data


def _dump_registry(repo: Path, data: dict) -> None:
    path = repo / REGISTRY_REL
    text = yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=False,
    )
    path.write_text(text, encoding="utf-8")


def _load_dispatch(repo: Path) -> dict:
    path = repo / DISPATCH_REL
    if not path.exists():
        return {"version": "1.0", "validators": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_dispatch(repo: Path, data: dict) -> None:
    path = repo / DISPATCH_REL
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# Non-validator utility scripts that live in validators/ but aren't gates.
# Matched by exact stem (no leading underscore prefix needed).
_NON_VALIDATOR_STEMS: frozenset[str] = frozenset({
    "audit-rule-cards",
    "edit-rule-cards",
    "extract-rule-cards",
    "inventory-skill-rules",
    "register-validator",
    "dispatch-validators-by-context",
})


def _canonical_id(name: str) -> str:
    """Return canonical orphan-diff id from any input form.

    Validators on disk use two naming conventions historically:
      - bare stems  (`acceptance-reconciliation.py`)
      - verify-prefixed (`verify-url-state-runtime.py`)

    Registry path fields and dispatch keys can be either. To make the
    3-way diff symmetric we collapse to the bare-stem form (strip
    `verify-` / `validate-` prefix). Output identifiers in apply hooks
    use the same form.
    """
    stem = Path(name).stem  # tolerates `*.py`
    return stem.removeprefix("verify-").removeprefix("validate-")


def _validator_id_from_filename(name: str) -> str:
    """`verify-foo-bar.py` → `foo-bar`. Bare stem is the canonical id."""
    return _canonical_id(name)


def _list_script_validators(repo: Path) -> list[str]:
    """Glob top-level *.py, drop utilities + private modules, return canonical ids.

    Excludes:
      - files under `_retired/` or any other nested folder
      - files starting with `_` (private modules: `_common`, `_i18n`, etc.)
      - explicit non-validator utility scripts in `_NON_VALIDATOR_STEMS`
    """
    vdir = repo / VALIDATORS_DIR_REL
    if not vdir.exists():
        return []
    out: list[str] = []
    for p in vdir.glob("*.py"):
        if not p.is_file() or p.parent != vdir:
            continue
        if p.name.startswith("_"):
            continue
        stem = p.stem
        if stem in _NON_VALIDATOR_STEMS:
            continue
        out.append(_canonical_id(p.name))
    return sorted(set(out))


def _registry_ids(reg: dict) -> list[str]:
    return sorted({
        _canonical_id(e.get("path", "").split("/")[-1])
        for e in reg.get("validators", [])
        if e.get("path")
    })


def _registry_id_for_entry(entry: dict) -> str:
    """Return canonical id for a registry entry — derive from path filename."""
    p = entry.get("path", "")
    if not p:
        return _canonical_id(entry.get("id", ""))
    return _canonical_id(Path(p).name)


def _dispatch_ids(dispatch: dict) -> list[str]:
    """Dispatch keys are usually bare stems but may be verify-prefixed.

    Both forms collapse to the bare canonical id so cross-source diff
    is symmetric.
    """
    return sorted({
        _canonical_id(key) for key in dispatch.get("validators", {}).keys()
    })


def _three_way_diff(
    scripts: Iterable[str],
    registry_ids: Iterable[str],
    dispatch_ids: Iterable[str],
) -> dict[str, list[str]]:
    s_set = set(scripts)
    r_set = set(registry_ids)
    d_set = set(dispatch_ids)
    return {
        "script_only": sorted(s_set - r_set - d_set),
        "registry_only": sorted(r_set - s_set - d_set),
        "dispatch_only": sorted(d_set - s_set - r_set),
    }


def _partition(orphans_sorted: list[str]) -> dict[str, list[str]]:
    return {
        "agent_1": orphans_sorted[0::3],
        "agent_2": orphans_sorted[1::3],
        "agent_3": orphans_sorted[2::3],
    }


def _ensure_phase_dir(repo: Path) -> Path:
    pdir = repo / PHASE_DIR_REL
    pdir.mkdir(parents=True, exist_ok=True)
    return pdir


# ---------------------------------------------------------------------------
# Subcommand: orphans_list
# ---------------------------------------------------------------------------


def orphans_list(args) -> int:
    repo = _repo_root()
    scripts = _list_script_validators(repo)
    reg = _load_registry(repo)
    dispatch = _load_dispatch(repo)

    reg_ids = _registry_ids(reg)
    disp_ids = _dispatch_ids(dispatch)

    diff = _three_way_diff(scripts, reg_ids, disp_ids)
    union_sorted = sorted(
        set(diff["script_only"]) | set(diff["registry_only"])
        | set(diff["dispatch_only"])
    )
    partitions = _partition(union_sorted)

    payload = {
        "generated_at": _utc_now_iso(),
        "total_orphans": len(union_sorted),
        "by_kind": diff,
        "agents": partitions,
    }

    out_dir = _ensure_phase_dir(repo)
    out_path = out_dir / ORPHAN_LIST_NAME
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
        + "\n",
        encoding="utf-8",
    )

    # Human summary
    print("Orphan triage — partition complete")
    print(f"  total orphans: {payload['total_orphans']}")
    print(f"    script_only:   {len(diff['script_only'])}")
    print(f"    registry_only: {len(diff['registry_only'])}")
    print(f"    dispatch_only: {len(diff['dispatch_only'])}")
    print(
        "  agent slices: "
        f"agent_1={len(partitions['agent_1'])}, "
        f"agent_2={len(partitions['agent_2'])}, "
        f"agent_3={len(partitions['agent_3'])}"
    )
    print(f"  artifact: {out_path.relative_to(repo).as_posix()}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: orphans_collect
# ---------------------------------------------------------------------------


def _read_decision_file(p: Path) -> list[dict]:
    text = p.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(
            f"{p.name}: expected JSON array of decisions, got "
            f"{type(data).__name__}"
        )
    return data


def _validate_decision(d: dict) -> str:
    """Return error message if invalid, '' if OK."""
    vid = d.get("validator_id")
    if not vid or not isinstance(vid, str):
        return "missing 'validator_id' (string)"
    outcome = d.get("outcome")
    if outcome not in VALID_OUTCOMES:
        return (
            f"invalid 'outcome' for {vid}: {outcome!r} "
            f"(must be one of {sorted(VALID_OUTCOMES)})"
        )
    if "confidence" in d:
        c = d["confidence"]
        if not isinstance(c, (int, float)) or not (0.0 <= float(c) <= 1.0):
            return f"invalid 'confidence' for {vid}: {c!r}"
    return ""


def orphans_collect(args) -> int:
    repo = _repo_root()
    pdir = repo / PHASE_DIR_REL

    list_path = pdir / ORPHAN_LIST_NAME
    if not list_path.exists():
        print(
            "\033[38;5;208morphans-collect: missing \033[0m"
            f"{list_path.relative_to(repo).as_posix()} — run "
            "`vg-orchestrator orphans-list` first.",
            file=sys.stderr,
        )
        return 1

    list_data = json.loads(list_path.read_text(encoding="utf-8"))
    expected_ids = set()
    for slice_ids in list_data.get("agents", {}).values():
        expected_ids.update(slice_ids)

    merged: list[dict] = []
    seen: set[str] = set()
    missing_files: list[str] = []
    for n in (1, 2, 3):
        f = pdir / DECISIONS_AGENT_TEMPLATE.format(n=n)
        if not f.exists():
            missing_files.append(f.name)
            continue
        try:
            decisions = _read_decision_file(f)
        except (json.JSONDecodeError, ValueError) as exc:
            print(
                f"\033[38;5;208morphans-collect: {f.name} unparseable — {exc}\033[0m",
                file=sys.stderr,
            )
            return 1
        for d in decisions:
            err = _validate_decision(d)
            if err:
                print(
                    f"\033[38;5;208morphans-collect: {f.name} — {err}\033[0m",
                    file=sys.stderr,
                )
                return 1
            vid = d["validator_id"]
            if vid in seen:
                print(
                    f"\033[38;5;208morphans-collect: duplicate decision for {vid} \033[0m"
                    f"(also in earlier file)",
                    file=sys.stderr,
                )
                return 1
            seen.add(vid)
            merged.append(d)

    if missing_files:
        print(
            "\033[38;5;208morphans-collect: missing per-agent decision file(s): \033[0m"
            f"{', '.join(missing_files)} (expected at "
            f"{pdir.relative_to(repo).as_posix()}/)",
            file=sys.stderr,
        )
        return 1

    not_decided = sorted(expected_ids - seen)
    if not_decided:
        print(
            "\033[38;5;208morphans-collect: missing decisions for \033[0m"
            f"{len(not_decided)} validator(s): "
            f"{', '.join(not_decided[:10])}"
            + (" …" if len(not_decided) > 10 else ""),
            file=sys.stderr,
        )
        return 1

    extra = sorted(seen - expected_ids)
    if extra:
        print(
            "\033[38;5;208morphans-collect: decision(s) for validators not in \033[0m"
            f"orphan-list: {', '.join(extra[:10])}"
            + (" …" if len(extra) > 10 else ""),
            file=sys.stderr,
        )
        return 1

    stats = {"wire": 0, "retire": 0, "merge": 0, "needs_human": 0}
    for d in merged:
        outcome = d["outcome"]
        if outcome == "WIRE":
            stats["wire"] += 1
        elif outcome == "RETIRE":
            stats["retire"] += 1
        elif outcome == "MERGE":
            stats["merge"] += 1
        elif outcome == "NEEDS_HUMAN":
            stats["needs_human"] += 1

    out_payload = {
        "generated_at": _utc_now_iso(),
        "source_partition": ORPHAN_LIST_NAME,
        "total_decisions": len(merged),
        "stats": stats,
        "decisions": merged,
    }
    out_path = pdir / DECISIONS_MERGED_NAME
    out_path.write_text(
        json.dumps(out_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("Orphan triage — decisions merged")
    print(f"  total decisions: {len(merged)}")
    print(
        "  by outcome: "
        f"WIRE={stats['wire']}, RETIRE={stats['retire']}, "
        f"MERGE={stats['merge']}, NEEDS_HUMAN={stats['needs_human']}"
    )
    print(f"  artifact: {out_path.relative_to(repo).as_posix()}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: orphans_apply
# ---------------------------------------------------------------------------


def _find_registry_entry(reg: dict, vid: str) -> dict | None:
    """Find entry whose canonical id matches vid. vid is canonicalized
    too so callers can pass either bare or verify-prefixed forms.
    """
    target = _canonical_id(vid)
    for e in reg.get("validators", []):
        if _registry_id_for_entry(e) == target:
            return e
    return None


def _resolve_script_path(repo: Path, vid: str) -> tuple[Path, bool]:
    """Return (path, existed) for a validator script.

    Tolerates both naming conventions on disk: `{vid}.py` and
    `verify-{vid}.py`. If neither exists, returns the verify-prefixed
    form (so retire/merge can still log the intended new location even
    when no script remains on disk).
    """
    bare = _canonical_id(vid)
    bare_path = repo / VALIDATORS_DIR_REL / f"{bare}.py"
    pref_path = repo / VALIDATORS_DIR_REL / f"verify-{bare}.py"
    if bare_path.exists():
        return bare_path, True
    if pref_path.exists():
        return pref_path, True
    # Original input may have come in verify-prefixed; fall back to that.
    raw_path = repo / VALIDATORS_DIR_REL / f"{vid}.py"
    return (raw_path if vid.startswith("verify-") else pref_path), False


def _add_registry_entry(reg: dict, entry: dict) -> None:
    reg.setdefault("validators", []).append(entry)


def _remove_dispatch_entry(dispatch: dict, vid: str) -> bool:
    bare = vid.removeprefix("verify-")
    keys_to_remove = [
        k for k in dispatch.get("validators", {})
        if k == vid or k == bare
    ]
    for k in keys_to_remove:
        dispatch["validators"].pop(k, None)
    return bool(keys_to_remove)


def _dispatch_key_for(vid: str) -> str:
    """Existing dispatch entries are keyed by bare stem (no `verify-` prefix);
    keep that convention for new WIRE entries."""
    return vid.removeprefix("verify-")


def _git_mv(repo: Path, src: Path, dst: Path, dry_run: bool) -> str:
    """Run `git mv src dst`. Falls back to plain rename if not in git or
    the file is untracked. Returns a one-line description for the apply log.
    """
    src_rel = src.relative_to(repo).as_posix()
    dst_rel = dst.relative_to(repo).as_posix()
    if dry_run:
        return f"[dry-run] git mv {src_rel} {dst_rel}"

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "mv", src_rel, dst_rel],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            return f"git mv {src_rel} {dst_rel}"
        # Fallback to plain move (file untracked or not a git repo)
        shutil.move(str(src), str(dst))
        return f"mv (non-git) {src_rel} {dst_rel}"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        shutil.move(str(src), str(dst))
        return f"mv (no-git-binary) {src_rel} {dst_rel}"


def _evidence_ref(vid: str) -> str:
    rel = (PHASE_DIR_REL / DECISIONS_MERGED_NAME).as_posix()
    return f"{rel}#{vid}"


def _retire_block(d: dict, moved_to_rel: str) -> dict:
    today = _today_date()
    reason = d.get("evidence", {}).get("retire_reason") or \
        "Phase D triage — no real callers found"
    # 3-month retention per SPEC-D § 6
    yyyy, mm, dd = today.split("-")
    yy = int(yyyy)
    mi = int(mm) + 3
    while mi > 12:
        mi -= 12
        yy += 1
    removal_planned = f"{yy:04d}-{mi:02d}-{dd}"
    return {
        "reason": reason,
        "moved_to": moved_to_rel,
        "removal_planned": removal_planned,
    }


def _triage_block(d: dict, state: str) -> dict:
    return {
        "state": state,
        "decided_at": _today_date(),
        "decided_by": d.get("decided_by", "agent"),
        "confidence": d.get("confidence"),
        "evidence_ref": _evidence_ref(d["validator_id"]),
    }


def _apply_wire(
    repo: Path, d: dict, reg: dict, dispatch: dict, dry_run: bool,
) -> str:
    vid = d["validator_id"]
    ev = d.get("evidence", {})
    suggested = ev.get("suggested_context", {})
    severity = ev.get("severity", "WARN")

    # Registry entry — create or update
    entry = _find_registry_entry(reg, vid)
    rel_path = (VALIDATORS_DIR_REL / f"{vid}.py").as_posix()
    if entry is None:
        entry = {
            "id": vid.removeprefix("verify-"),
            "path": rel_path,
            "severity": severity.lower(),
            "phases_active": suggested.get("commands", ["all"]),
            "domain": ev.get("domain", "uncategorized"),
            "runtime_target_ms": ev.get("runtime_target_ms", 1000),
            "added_in": "v2.7-D",
            "description": ev.get(
                "docstring_summary", "Wired by Phase D orphan triage",
            ),
        }
        if not dry_run:
            _add_registry_entry(reg, entry)
    if not dry_run:
        entry["triage"] = _triage_block({**d, "decided_by": "agent"}, "wired")

    # Dispatch entry — create if absent
    key = _dispatch_key_for(vid)
    if key not in dispatch.get("validators", {}) and not dry_run:
        dispatch.setdefault("validators", {})[key] = {
            "triggers": {
                "commands": suggested.get("commands", ["*"]),
                "steps": suggested.get("steps", ["*"]),
            },
            "contexts": {
                "profiles": suggested.get("profiles", ["*"]),
                "platforms": suggested.get("platforms", ["*"]),
                "envs": suggested.get("envs", ["*"]),
            },
            "severity": severity,
            "unquarantinable": False,
            "description": ev.get(
                "docstring_summary", "Wired by Phase D orphan triage",
            ),
        }

    return f"WIRE   {vid}  → registry+dispatch ({severity})"


def _apply_retire(
    repo: Path, d: dict, reg: dict, dispatch: dict, dry_run: bool,
) -> str:
    vid = d["validator_id"]
    src, src_existed = _resolve_script_path(repo, vid)
    # Preserve the resolved filename in the retired path so forensics
    # can match the disk artefact 1:1.
    dst = repo / RETIRED_DIR_REL / f"{_today_date()}-{src.name}"

    move_log = ""
    if src_existed:
        move_log = _git_mv(repo, src, dst, dry_run)
    else:
        move_log = f"(no script on disk for {vid} — registry/dispatch only)"

    moved_to_rel = dst.relative_to(repo).as_posix() if src_existed else ""

    entry = _find_registry_entry(reg, vid)
    if entry is None:
        entry = {
            "id": vid.removeprefix("verify-"),
            "path": (VALIDATORS_DIR_REL / f"{vid}.py").as_posix(),
            "severity": "advisory",
            "phases_active": [],
            "domain": "retired",
            "runtime_target_ms": 0,
            "added_in": "pre-v2.7",
            "description": "Retired by Phase D triage",
        }
        if not dry_run:
            _add_registry_entry(reg, entry)
    if not dry_run:
        entry["triage"] = _triage_block(d, "retired")
        if moved_to_rel:
            entry["retired"] = _retire_block(d, moved_to_rel)
        else:
            entry["retired"] = _retire_block(d, "(no-script)")

    if not dry_run:
        _remove_dispatch_entry(dispatch, vid)

    return f"RETIRE {vid}  → {move_log}"


def _apply_merge(
    repo: Path, d: dict, reg: dict, dispatch: dict, dry_run: bool,
) -> str:
    vid = d["validator_id"]
    target = d.get("evidence", {}).get("merged_into_id", "")
    src, src_existed = _resolve_script_path(repo, vid)
    dst = repo / RETIRED_DIR_REL / f"{_today_date()}-{src.name}"

    move_log = ""
    if src_existed:
        move_log = _git_mv(repo, src, dst, dry_run)
    else:
        move_log = f"(no script on disk for {vid})"

    moved_to_rel = dst.relative_to(repo).as_posix() if src_existed else ""

    entry = _find_registry_entry(reg, vid)
    if entry is None:
        entry = {
            "id": vid.removeprefix("verify-"),
            "path": (VALIDATORS_DIR_REL / f"{vid}.py").as_posix(),
            "severity": "advisory",
            "phases_active": [],
            "domain": "merged",
            "runtime_target_ms": 0,
            "added_in": "pre-v2.7",
            "description": f"Merged into {target} by Phase D triage",
        }
        if not dry_run:
            _add_registry_entry(reg, entry)
    if not dry_run:
        entry["triage"] = _triage_block(d, "merged")
        entry["merged_into"] = {
            "target_id": target,
            "reason": d.get("evidence", {}).get(
                "retire_reason", "duplicate logic"
            ),
        }
        if moved_to_rel:
            entry["retired"] = _retire_block(d, moved_to_rel)
        _remove_dispatch_entry(dispatch, vid)

    return f"MERGE  {vid}  → {target} ({move_log})"


def _apply_pending(
    repo: Path, d: dict, reg: dict, dispatch: dict, dry_run: bool,
) -> str:
    vid = d["validator_id"]
    entry = _find_registry_entry(reg, vid)
    if entry is None:
        entry = {
            "id": vid.removeprefix("verify-"),
            "path": (VALIDATORS_DIR_REL / f"{vid}.py").as_posix(),
            "severity": "advisory",
            "phases_active": [],
            "domain": "uncategorized",
            "runtime_target_ms": 0,
            "added_in": "pre-v2.7",
            "description": "Pending Phase D human review",
        }
        if not dry_run:
            _add_registry_entry(reg, entry)
    if not dry_run:
        entry["triage"] = _triage_block(d, "pending")
    return f"PEND   {vid}  → tagged triage:pending (no file move)"


def orphans_apply(args) -> int:
    repo = _repo_root()
    pdir = repo / PHASE_DIR_REL
    decisions_path = pdir / DECISIONS_MERGED_NAME
    if not decisions_path.exists():
        print(
            "\033[38;5;208morphans-apply: missing \033[0m"
            f"{decisions_path.relative_to(repo).as_posix()} — run "
            "`vg-orchestrator orphans-collect` first.",
            file=sys.stderr,
        )
        return 1

    payload = json.loads(decisions_path.read_text(encoding="utf-8"))
    decisions = payload.get("decisions", [])
    if not decisions:
        print("\033[38;5;208morphans-apply: decisions array empty\033[0m", file=sys.stderr)
        return 1

    reg = _load_registry(repo)
    dispatch = _load_dispatch(repo)

    counts = {"WIRE": 0, "RETIRE": 0, "MERGE": 0, "NEEDS_HUMAN": 0}
    log_lines: list[str] = []

    dry_run = bool(getattr(args, "dry_run", False))

    for d in decisions:
        outcome = d["outcome"]
        if outcome == "WIRE":
            log_lines.append(_apply_wire(repo, d, reg, dispatch, dry_run))
        elif outcome == "RETIRE":
            log_lines.append(_apply_retire(repo, d, reg, dispatch, dry_run))
        elif outcome == "MERGE":
            log_lines.append(_apply_merge(repo, d, reg, dispatch, dry_run))
        elif outcome == "NEEDS_HUMAN":
            log_lines.append(_apply_pending(repo, d, reg, dispatch, dry_run))
        counts[outcome] = counts.get(outcome, 0) + 1

    if not dry_run:
        _dump_registry(repo, reg)
        _dump_dispatch(repo, dispatch)

    header = "Orphan triage — apply complete" if not dry_run \
        else "Orphan triage — DRY RUN (no files written)"
    print(header)
    for line in log_lines:
        print(f"  {line}")
    print(
        "  per-outcome: "
        f"WIRE={counts['WIRE']}, RETIRE={counts['RETIRE']}, "
        f"MERGE={counts['MERGE']}, NEEDS_HUMAN={counts['NEEDS_HUMAN']}"
    )
    return 0
