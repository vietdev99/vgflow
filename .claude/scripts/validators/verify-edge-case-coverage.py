#!/usr/bin/env python3
"""
Validator: verify-edge-case-coverage.py — R7 Task 7 (G3)

Build-time edge-case implementation coverage audit. Sister gate to R7
Task 3 (verify-rcrurd-implementation.py at 8d.5c) and the workflow audit
at 8d.5d.

Why this gate exists (codex audit, 2026-05-05):
  Blueprint generates per-goal EDGE-CASES at `EDGE-CASES/<goal>.md` with
  a variant catalog (variant_id, expected_outcome, priority). The build
  delegation (`waves-delegation.md` lines 152-159) instructs the executor:

      Implementation MUST cover EVERY variant — reference variant_id in
      comments at the relevant code site:
        // vg-edge-case: G-04-b1 (empty domain → 400)

  But before R7 Task 7 there was NO build-side gate verifying the
  executor actually added these markers. `verify-edge-cases-contract.py`
  validates the artifact STRUCTURE (variant_id format, count budget),
  NOT implementation coverage.

What this validator does:
  1. List `${PHASE_DIR}/.task-capsules/task-*.capsule.json`.
  2. For each capsule with non-empty `edge_cases_for_goals[]`:
     a. Read `${PHASE_DIR}/EDGE-CASES/<goal_id>.md`.
     b. Parse the variants table — extract `variant_id` + `priority`.
  3. Read the task's modified files from `BUILD-LOG/task-NN.md`'s
     `Files modified` section.
  4. For each critical/high-priority variant_id, grep modified files for
     `// vg-edge-case: <variant_id>` (or `# vg-edge-case:` for Python /
     shell). Comment style follows the executor instruction; we accept
     any comment-leader prefix (// or # or /*) so we don't false-fail
     based on language.

Severity matrix:
  - PASS: every critical variant has a marker, AND ≥80% of high-priority
          variants have markers, OR no edge cases at all in the wave.
  - WARN: high-priority variants missing markers (heuristic miss —
          operator decides whether to override or fix). Includes
          gracefully degraded cases (missing per-goal file, malformed
          table) so a stale phase doesn't crash the build.
  - BLOCK: any critical variant has no marker in any modified file.

  Critical-only-on-BLOCK is intentional: critical variants are auth /
  data-integrity / cross-tenant boundary cases. A missing critical
  marker means the executor likely skipped a security-relevant code
  path. High-priority misses warrant a WARN (state/concurrency edges
  are commonly handled implicitly by framework defaults).

Pairs with:
  - 8d.5c — RCRURD implementation audit (R7 Task 3, G1)
  - 8d.5d — workflow state audit
  - This file → 8d.5e

Usage:
  verify-edge-case-coverage.py --phase 7.14
  verify-edge-case-coverage.py --phase-dir /abs/path/to/phase

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

# variant_id format from EDGE-CASES contract: G-NN-<letter><N>
VARIANT_ID_RE = re.compile(r"^G-\d+-[a-z]\d+$")
PRIORITY_VALUES = {"critical", "high", "medium", "low"}

# Coverage threshold for high-priority variants — below this triggers WARN.
HIGH_PRIORITY_COVERAGE_FLOOR = 0.80


def _load_capsule(capsule_path: Path) -> dict | None:
    try:
        return json.loads(capsule_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_variant_table(body: str) -> list[dict]:
    """Extract variants from per-goal EDGE-CASES/G-NN.md tables.

    Recognized row shape: `| <variant_id> | <input> | <expected> | <priority> |`
    (3-4 cells; priority lives in the LAST cell that matches a known
    priority literal). Mirrors the parser in verify-edge-cases-contract.py
    to keep the two gates schema-aligned.

    Returns list of {variant_id, priority}. priority lower-cased; None
    when not parseable.
    """
    variants: list[dict] = []
    for m in re.finditer(r"^\|\s*(G-\d+-[a-z]\d+)\s*\|(.+?)\|\s*$", body, re.MULTILINE):
        variant_id = m.group(1).strip()
        cells = [c.strip() for c in m.group(0).split("|")[1:-1]]
        priority: str | None = None
        for cell in reversed(cells):
            cell_low = (cell or "").lower()
            for p in PRIORITY_VALUES:
                # `cell == "critical"` OR `cell` starts with the literal
                # then optional whitespace/markup. Tolerate trailing notes.
                if re.match(rf"^\s*{p}\b", cell_low):
                    priority = p
                    break
            if priority:
                break
        variants.append({
            "variant_id": variant_id,
            "priority": priority,
        })
    return variants


def _parse_artifacts_from_build_log(phase_dir: Path, task_id: str) -> list[str]:
    """Read BUILD-LOG/task-NN.md and extract `Files modified` paths.

    Same parser shape as verify-rcrurd-implementation.py — kept inline
    rather than shared because the two gates have different expectations
    about empty results (RCRURD soft-skips, edge-case must reach across
    every modified file regardless of language).
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
                rest = stripped[2:]
                m = re.match(r"([^\s(]+)", rest)
                if m:
                    paths.append(m.group(1))
            elif stripped == "" or stripped.startswith("##") or stripped.startswith("```"):
                if paths:
                    break
    return paths


def _read_text_safe(repo_root: Path, rel: str) -> str | None:
    full = repo_root / rel
    if not full.exists() or not full.is_file():
        return None
    try:
        return full.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _marker_present(file_texts: dict[str, str], variant_id: str) -> list[str]:
    """Return list of relpaths whose content contains a marker for `variant_id`.

    Recognized comment leaders:
      // vg-edge-case: G-04-b1
      # vg-edge-case: G-04-b1   (Python / shell / yaml)
      /* vg-edge-case: G-04-b1  (C-style block)

    The trailing parenthetical on the marker line is informational only
    — we anchor on `vg-edge-case:` + the literal variant_id.
    """
    # Build a single regex that requires `vg-edge-case` + colon + (optional
    # whitespace) + the EXACT variant_id followed by whitespace, paren, or EOL.
    pattern = re.compile(
        rf"vg-edge-case\s*:\s*{re.escape(variant_id)}(?=\s|\(|$|[^A-Za-z0-9_-])",
        re.MULTILINE,
    )
    hits: list[str] = []
    for rel, text in file_texts.items():
        if pattern.search(text):
            hits.append(rel)
    return hits


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
            type="edge_case_malformed_capsule",
            message=f"Capsule unreadable: {capsule_path.name}",
            file=str(capsule_path),
        ))
        return

    goals = capsule.get("edge_cases_for_goals") or []
    if not goals:
        return  # Task does not touch any edge-case-bearing goal.

    task_id = (
        capsule.get("task_id")
        or capsule.get("task_id_str")
        or capsule_path.stem.replace(".capsule", "")
    )
    task_id_str = str(task_id)

    # Resolve modified files from BUILD-LOG/task-NN.md and slurp their text.
    artifacts = _parse_artifacts_from_build_log(phase_dir, task_id_str)
    file_texts: dict[str, str] = {}
    for rel in artifacts:
        text = _read_text_safe(repo_root, rel)
        if text is not None:
            file_texts[rel] = text

    edge_dir = phase_dir / "EDGE-CASES"

    for goal_id in goals:
        if not isinstance(goal_id, str):
            continue
        goal_md = edge_dir / f"{goal_id}.md"
        if not goal_md.exists():
            out.warn(Evidence(
                type="edge_case_goal_file_missing",
                message=(
                    f"Task {task_id_str}: edge-case file missing for goal "
                    f"{goal_id} at {goal_md}. Stale capsule or pruned "
                    f"artifact — skipping coverage audit for this goal."
                ),
                file=str(goal_md),
                fix_hint=(
                    "Re-run `/vg:blueprint <phase> --from=2b5e_edge_cases` "
                    "to regenerate, or remove the stale goal id from the "
                    "task's edge_cases_for_goals[]."
                ),
            ))
            continue

        try:
            body = goal_md.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            out.warn(Evidence(
                type="edge_case_goal_file_unreadable",
                message=f"Task {task_id_str}: cannot read {goal_md}: {e}",
                file=str(goal_md),
            ))
            continue

        variants = _parse_variant_table(body)
        if not variants:
            # Per-goal file exists but has no variant rows — could be a
            # trivial-goal skip (header `**Skipped categories**:`). Soft note.
            out.warn(Evidence(
                type="edge_case_no_variants_parsed",
                message=(
                    f"Task {task_id_str}: no variant rows parseable from "
                    f"{goal_md.name}. If this is a trivial/skipped goal, "
                    f"the audit is a no-op for it."
                ),
                file=str(goal_md),
            ))
            continue

        critical = [v for v in variants if v["priority"] == "critical"]
        high = [v for v in variants if v["priority"] == "high"]

        # Critical variants — every one MUST have a marker. Missing → BLOCK.
        missing_critical: list[str] = []
        for v in critical:
            vid = v["variant_id"]
            if not _marker_present(file_texts, vid):
                missing_critical.append(vid)

        if missing_critical:
            out.add(Evidence(
                type="edge_case_critical_missing",
                message=(
                    f"Task {task_id_str} (goal {goal_id}): critical edge-case "
                    f"variants have no `vg-edge-case:` marker in any modified "
                    f"file. Missing: {missing_critical}. Modified files "
                    f"scanned: {list(file_texts.keys()) or '(none)'}."
                ),
                file=str(goal_md),
                expected=(
                    f"Each critical variant referenced by a code-site comment, "
                    f"e.g. `// vg-edge-case: {missing_critical[0]} (<note>)`."
                ),
                actual="no marker found for critical variants",
                fix_hint=(
                    "Add `// vg-edge-case: <variant_id>` comment at the code "
                    "path that handles each critical variant. Re-run /vg:build, "
                    "or override via --skip-edge-case-coverage-audit "
                    "--override-reason=<ticket>."
                ),
            ))

        # High-priority variants — coverage threshold check (WARN only).
        if high:
            covered = sum(1 for v in high if _marker_present(file_texts, v["variant_id"]))
            ratio = covered / len(high)
            if ratio < HIGH_PRIORITY_COVERAGE_FLOOR:
                missing_high = [
                    v["variant_id"] for v in high
                    if not _marker_present(file_texts, v["variant_id"])
                ]
                out.warn(Evidence(
                    type="edge_case_high_priority_undercovered",
                    message=(
                        f"Task {task_id_str} (goal {goal_id}): high-priority "
                        f"edge-case coverage {covered}/{len(high)} = "
                        f"{ratio:.0%} (floor {int(HIGH_PRIORITY_COVERAGE_FLOOR*100)}%). "
                        f"Missing markers: {missing_high}."
                    ),
                    file=str(goal_md),
                    expected=(
                        f"≥{int(HIGH_PRIORITY_COVERAGE_FLOOR*100)}% of high-priority "
                        f"variants marked"
                    ),
                    actual=f"{ratio:.0%} covered",
                    fix_hint=(
                        "Add `// vg-edge-case: <variant_id>` markers at the "
                        "code paths handling each high-priority variant. "
                        "If a variant is intentionally deferred to a later "
                        "phase, document in capsule scope notes."
                    ),
                ))


def main() -> None:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--phase", help="Phase id (e.g. '7.14')")
    ap.add_argument("--phase-dir", help="Absolute path to phase dir")
    ap.add_argument("--wave-id", help="(Optional) wave number — informational")
    args = ap.parse_args()

    out = Output(validator="edge-case-coverage")
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

        # Repo root for resolving artifact paths.
        import os as _os
        repo_root_env = _os.environ.get("VG_REPO_ROOT")
        if repo_root_env:
            repo_root = Path(repo_root_env).resolve()
        else:
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

        scoped_count = 0
        for capsule_path in capsules:
            cap = _load_capsule(capsule_path)
            if cap and cap.get("edge_cases_for_goals"):
                scoped_count += 1
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
                    f"Edge-case coverage audit PASS — {len(capsules)} "
                    f"capsule(s) scanned, {scoped_count} with edge_cases_for_goals "
                    f"verified against `vg-edge-case:` markers in modified files."
                ),
            ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
