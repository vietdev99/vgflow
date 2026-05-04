#!/usr/bin/env python3
"""
Validator: verify-rcrurd-implementation.py — R7 Task 3 (G1)

Post-spawn RCRURD implementation audit. For every task capsule under
${PHASE_DIR}/.task-capsules/task-*.capsule.json with non-empty
`rcrurd_invariants_paths[]`, this validator HEURISTICALLY checks that
the modified handler files honor the per-goal RCRURD invariants.

Why heuristic + WARN by default:
  Static analysis cannot prove invariant compliance without full type
  checking + symbolic execution. A WARN tells the operator "look here";
  BLOCK only triggers on a clear contradiction (e.g. a DELETE invariant
  asserts 404 but the handler hardcodes a 200 status code on the
  not-found branch).

Severity matrix:
  - PASS: heuristic match (DELETE handler emits 404/NotFoundError;
          POST/PUT/PATCH handler emits an `id` field in its response),
          OR no mutation invariants in the wave.
  - WARN: heuristic miss (invariant is present, no relevant grep hit).
          Includes malformed yaml (graceful degradation — Codex finding
          #36 pattern, do not crash on stale phases).
  - BLOCK: clear contradiction. Only DELETE/404 vs hardcoded 200 today.

Pairs with R7 Task 2 (G7 source unification — `yaml-rcrurd` inline
fences inside TEST-GOALS/G-NN.md) and R6 Task 9 (TDD evidence audit at
post-spawn 8d.5b). Wave-complete BLOCKs only on contradiction; WARN
surfaces but does not stop the wave.

Usage:
  verify-rcrurd-implementation.py --phase 7.14
  verify-rcrurd-implementation.py --phase-dir /abs/path/to/phase

Output: vg.validator-output JSON on stdout (rc 0 PASS/WARN, rc 1 BLOCK).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402

# Heuristic markers we recognize as "DELETE invariant honored".
# Multiple synonyms because handler dialect varies across stacks (Next
# Route Handler, Fastify, Express, Nest controllers, Bun routers).
_DELETE_NOT_FOUND_PATTERNS = [
    r"\b404\b",
    r"\bNotFoundError\b",
    r"\bnot[_-]?found\b",
    r"\bStatus\.NOT_FOUND\b",
    r"\bHttpStatus\.NOT_FOUND\b",
    r"\bHTTPException\b.*404",
]

# Patterns that suggest a hardcoded contradiction: the handler's
# not-found branch (text mentioning not_found/notfound) is paired
# with a 200 status code.
_NOT_FOUND_CONTRADICTION_RE = re.compile(
    r"not[_-]?found"  # mention of the not-found case
    r"[^\n]{0,200}?"  # within ~200 chars on same logical block
    r"\bstatus\s*[:=]\s*200\b",  # paired with status 200
    re.IGNORECASE | re.DOTALL,
)


def _load_capsule(capsule_path: Path) -> dict | None:
    try:
        return json.loads(capsule_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_yaml_safe(yaml_path: Path) -> tuple[dict | None, str | None]:
    """Returns (parsed_dict_or_None, error_message_or_None).

    Graceful degradation: missing pyyaml or parse errors return
    (None, msg) so the caller can WARN rather than crash the build.
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        return None, "pyyaml not installed; cannot parse RCRURD invariant"
    try:
        text = yaml_path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"unreadable yaml file: {e}"
    try:
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            return None, "yaml root is not a mapping"
        return data, None
    except Exception as e:
        return None, f"yaml parse error: {type(e).__name__}: {e}"


def _extract_invariant(doc: dict) -> dict | None:
    """Pull `read_after_write_invariant` block from a parsed yaml doc."""
    inv = doc.get("read_after_write_invariant")
    if isinstance(inv, dict):
        return inv
    return None


def _parse_artifacts_from_build_log(phase_dir: Path, task_id: str) -> list[str]:
    """Read BUILD-LOG/task-NN.md and extract `Files modified` paths.

    Format (per agents/vg-build-task-executor/SKILL.md step 15):
        **Files modified**:
        - path/a.ts (lines added: N, removed: M)
        - path/b.spec.ts (...)

    Returns empty list when the log is missing or cannot be parsed —
    caller uses this as a signal to skip with a soft note rather than
    hard-fail.
    """
    bl = phase_dir / "BUILD-LOG" / f"{task_id}.md"
    if not bl.exists():
        return []
    try:
        body = bl.read_text(encoding="utf-8")
    except OSError:
        return []

    paths: list[str] = []
    in_section = False
    for line in body.splitlines():
        stripped = line.strip()
        if "Files modified" in stripped:
            in_section = True
            continue
        if in_section:
            if stripped.startswith("- "):
                # "- path/a.ts (lines added: N, removed: M)"
                rest = stripped[2:]
                m = re.match(r"([^\s(]+)", rest)
                if m:
                    paths.append(m.group(1))
            elif stripped == "" or stripped.startswith("##") or stripped.startswith("```"):
                # blank line / next section / fence terminates the list
                if paths:
                    break
    return paths


def _looks_like_handler(path: str) -> bool:
    """Crude filter: is this artifact a backend handler/route/controller?"""
    p = path.lower()
    if "/route." in p or p.endswith("/route.ts") or p.endswith("/route.js"):
        return True
    if "controller" in p or "handler" in p:
        return True
    # Heuristic for backend src paths in monorepos
    if "/api/" in p and (p.endswith(".ts") or p.endswith(".js") or p.endswith(".py")):
        return True
    return False


def _read_handler_text(repo_root: Path, rel: str) -> str | None:
    full = repo_root / rel
    if not full.exists() or not full.is_file():
        return None
    try:
        return full.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _audit_delete(
    out: Output,
    *,
    task_id: str,
    goal_id: str,
    yaml_path: Path,
    handler_texts: dict[str, str],
) -> None:
    """DELETE invariant requires a not-found / 404 path.

    Emits:
      BLOCK (rcrurd_delete_contradiction) — handler explicitly returns
              200 on the not-found branch.
      WARN  (rcrurd_delete_missing_404)   — no 404/NotFoundError marker
              found in any modified handler text.
      PASS  (no evidence appended)        — heuristic match.
    """
    if not handler_texts:
        out.warn(Evidence(
            type="rcrurd_delete_no_handler",
            message=(
                f"Goal {goal_id} (DELETE invariant): no handler/route file "
                f"in artifacts_written for task {task_id}. Cannot verify "
                f"404 path implementation."
            ),
            file=str(yaml_path),
            fix_hint=(
                "Confirm the implementing task wrote to a route/controller "
                "file. If the invariant is purely client-side, drop it from "
                "RCRURD-INVARIANTS for this goal."
            ),
        ))
        return

    # BLOCK check first — clear contradiction wins over WARN.
    contradicting: list[str] = []
    for path, text in handler_texts.items():
        if _NOT_FOUND_CONTRADICTION_RE.search(text):
            contradicting.append(path)
    if contradicting:
        out.add(Evidence(
            type="rcrurd_delete_contradiction",
            message=(
                f"Goal {goal_id} (DELETE invariant): handler text matches "
                f"a not-found branch paired with status 200, contradicting "
                f"invariant requirement of 404 / NotFoundError. "
                f"Files: {contradicting}"
            ),
            file=contradicting[0],
            expected="404 / NotFoundError on the not-found branch",
            actual="hardcoded status 200 near 'not_found' literal",
            fix_hint=(
                "Change the not-found branch to return status 404 (or throw "
                "NotFoundError / HTTPException 404). Re-run /vg:build, or "
                "override via --skip-rcrurd-implementation-audit "
                "--override-reason=<ticket>."
            ),
        ))
        return

    # WARN check — no 404 marker anywhere.
    combined_match = False
    for text in handler_texts.values():
        for pat in _DELETE_NOT_FOUND_PATTERNS:
            if re.search(pat, text):
                combined_match = True
                break
        if combined_match:
            break
    if not combined_match:
        out.warn(Evidence(
            type="rcrurd_delete_missing_404",
            message=(
                f"Goal {goal_id} (DELETE invariant): no 404 / NotFoundError "
                f"literal found in modified handler files for task "
                f"{task_id} ({list(handler_texts.keys())}). Heuristic miss "
                f"— manually verify the not-found path is honored."
            ),
            file=str(yaml_path),
            expected="404 / NotFoundError marker in handler",
            actual="none of the recognized synonyms matched",
            fix_hint=(
                "If the handler delegates 404 to a framework default, this "
                "warning is benign. Otherwise add an explicit 404 response "
                "for the not-found branch."
            ),
        ))


def _audit_create_or_update(
    out: Output,
    *,
    task_id: str,
    goal_id: str,
    yaml_path: Path,
    handler_texts: dict[str, str],
    inv: dict,
) -> None:
    """POST/PUT/PATCH invariant: handler should return an identifier or
    echo body whose JSONPath matches assert[].path.

    Heuristic: pull the leaf field from the first assert path (e.g.
    `$.id` → `id`; `$.roles[*].name` → `name`). Search handler text
    for that field appearing in a return-style position.
    """
    if not handler_texts:
        # Soft note — no handler in artifacts could just mean shared lib only.
        return

    asserts = inv.get("assert") or []
    leaf_fields: list[str] = []
    for a in asserts:
        if not isinstance(a, dict):
            continue
        path = a.get("path", "")
        if not isinstance(path, str):
            continue
        # `$.id` → `id`; `$.roles[*].name` → `name`; `$.user.id` → `id`.
        m = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)", path)
        if m:
            leaf_fields.append(m[-1])
    if not leaf_fields:
        return  # No usable assertion fields → silent skip.

    # Match if ANY leaf field appears anywhere in any handler. This is a
    # very permissive heuristic — we only WARN on miss, never BLOCK.
    matched = False
    for text in handler_texts.values():
        for field in leaf_fields:
            if re.search(rf"\b{re.escape(field)}\b", text):
                matched = True
                break
        if matched:
            break
    if not matched:
        out.warn(Evidence(
            type="rcrurd_mutation_field_missing",
            message=(
                f"Goal {goal_id}: invariant assert paths reference fields "
                f"{leaf_fields!r} but none appear in modified handler files "
                f"for task {task_id} ({list(handler_texts.keys())}). "
                f"Manually verify the response shape includes them."
            ),
            file=str(yaml_path),
            expected=f"handler response references fields {leaf_fields!r}",
            actual="no mention found in modified handler text",
            fix_hint=(
                "Either the response shape is missing the asserted fields, "
                "or the heuristic missed a serialization layer (DTO mapper, "
                "response builder). Inspect manually."
            ),
        ))


def _audit_task(
    out: Output,
    *,
    repo_root: Path,
    phase_dir: Path,
    capsule_path: Path,
) -> None:
    capsule = _load_capsule(capsule_path)
    if capsule is None:
        out.warn(Evidence(
            type="rcrurd_malformed_capsule",
            message=f"Capsule unreadable: {capsule_path.name}",
            file=str(capsule_path),
        ))
        return

    rcrurd_paths = capsule.get("rcrurd_invariants_paths") or []
    if not rcrurd_paths:
        return  # No invariants → nothing to audit.

    task_id = (
        capsule.get("task_id")
        or capsule.get("task_id_str")
        or capsule_path.stem.replace(".capsule", "")
    )
    task_id_str = str(task_id)

    # Resolve modified handler files from BUILD-LOG/task-NN.md.
    artifacts = _parse_artifacts_from_build_log(phase_dir, task_id_str)
    handler_paths = [p for p in artifacts if _looks_like_handler(p)]
    handler_texts: dict[str, str] = {}
    for rel in handler_paths:
        text = _read_handler_text(repo_root, rel)
        if text is not None:
            handler_texts[rel] = text

    for yaml_path_str in rcrurd_paths:
        yaml_path = Path(yaml_path_str)
        if not yaml_path.exists():
            out.warn(Evidence(
                type="rcrurd_invariant_missing",
                message=(
                    f"Task {task_id_str}: invariant yaml path does not exist: "
                    f"{yaml_path}. Stale capsule or extracted file pruned."
                ),
                file=str(yaml_path),
                fix_hint=(
                    "Re-run pre-executor-check.py to re-extract inline "
                    "yaml-rcrurd fences from TEST-GOALS/G-NN.md."
                ),
            ))
            continue

        doc, err = _read_yaml_safe(yaml_path)
        if err or doc is None:
            out.warn(Evidence(
                type="rcrurd_malformed_invariant",
                message=(
                    f"Task {task_id_str}: invariant yaml malformed at "
                    f"{yaml_path.name} — {err or 'unknown'}. Skipping audit "
                    f"for this goal."
                ),
                file=str(yaml_path),
                fix_hint=(
                    "Fix the yaml syntax in TEST-GOALS/<goal>.md inline "
                    "yaml-rcrurd fence. Re-run /vg:blueprint or /vg:build."
                ),
            ))
            continue

        inv = _extract_invariant(doc)
        if inv is None:
            # Goal yaml present but no invariant block — silent skip
            # (e.g. read-only goals don't carry RCRURD).
            continue

        write = inv.get("write") or {}
        method = str(write.get("method", "")).upper()
        # Derive goal_id from yaml filename stem (e.g. G-01.yaml).
        goal_id = yaml_path.stem

        if method == "DELETE":
            _audit_delete(
                out,
                task_id=task_id_str,
                goal_id=goal_id,
                yaml_path=yaml_path,
                handler_texts=handler_texts,
            )
        elif method in {"POST", "PUT", "PATCH"}:
            _audit_create_or_update(
                out,
                task_id=task_id_str,
                goal_id=goal_id,
                yaml_path=yaml_path,
                handler_texts=handler_texts,
                inv=inv,
            )
        # GET / unspecified → no implementation audit.


def main() -> None:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--phase", help="Phase id (e.g. '7.14')")
    ap.add_argument("--phase-dir", help="Absolute path to phase dir")
    ap.add_argument("--wave-id", help="(Optional) wave number — informational")
    args = ap.parse_args()

    out = Output(validator="rcrurd-implementation")
    with timer(out):
        if args.phase_dir:
            phase_dir = Path(args.phase_dir)
            if not phase_dir.is_absolute():
                phase_dir = Path.cwd() / phase_dir
            if not phase_dir.exists():
                out.warn(Evidence(
                    type="info",
                    message=f"--phase-dir does not exist: {phase_dir}",
                ))
                emit_and_exit(out)
        elif args.phase:
            phase_dir = find_phase_dir(args.phase)
            if not phase_dir:
                out.warn(Evidence(
                    type="info",
                    message=f"Phase dir not found for {args.phase} — skipping",
                ))
                emit_and_exit(out)
        else:
            ap.error("either --phase or --phase-dir is required")

        # Repo root for resolving artifacts_written paths. Default to
        # the env override, else two parents up from .vg/phases/<phase>.
        import os as _os
        repo_root_env = _os.environ.get("VG_REPO_ROOT")
        if repo_root_env:
            repo_root = Path(repo_root_env).resolve()
        else:
            # Walk up from phase_dir looking for .vg or .git marker.
            repo_root = phase_dir
            for parent in [phase_dir, *phase_dir.parents]:
                if (parent / ".git").exists() or (parent / ".vg").exists():
                    repo_root = parent
                    break

        capsule_dir = phase_dir / ".task-capsules"
        if not capsule_dir.exists():
            out.warn(Evidence(
                type="info",
                message=(
                    f"No .task-capsules dir under {phase_dir}. "
                    f"Either build hasn't run yet, or this phase has no tasks."
                ),
            ))
            emit_and_exit(out)

        capsules = sorted(capsule_dir.glob("task-*.capsule.json"))
        if not capsules:
            out.warn(Evidence(
                type="info",
                message=f"No task capsules found under {capsule_dir}.",
            ))
            emit_and_exit(out)

        invariant_count = 0
        for capsule_path in capsules:
            cap = _load_capsule(capsule_path)
            if cap and cap.get("rcrurd_invariants_paths"):
                invariant_count += 1
            _audit_task(
                out,
                repo_root=repo_root,
                phase_dir=phase_dir,
                capsule_path=capsule_path,
            )

        if not out.evidence:
            out.evidence.append(Evidence(
                type="info",
                message=(
                    f"RCRURD implementation audit PASS — {len(capsules)} "
                    f"capsule(s) scanned, {invariant_count} with invariants "
                    f"verified against handler heuristics."
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
