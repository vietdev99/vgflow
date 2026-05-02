#!/usr/bin/env python3
"""Verify every runtime module / validator / lens prompt / lib helper has a
caller in the active pipeline (skill .md or entry-point script).

Background: RFC v9 implementation built 16 runtime modules + 16 lens prompts +
~150 validators, but multiple PRs claimed "skill wiring B/D1/E" while only
adding 50-100 lines of acknowledgment to skill .md. Net effect: tester_pro
artifacts (D17/D18/D21/D22/D23) shipped as code, never wired into a workflow
step. Same for lens-prompts (CSRF/IDOR/BFLA/etc.) — written, not spawned.

This validator audits the call graph end-to-end:

  Source:                        Caller search:
  ─────────────────────────────  ───────────────────────────────────────
  scripts/runtime/X.py           grep `from runtime.X import` OR
                                 `import runtime.X` in:
                                   - commands/vg/**/*.md (heredocs)
                                   - scripts/**/*.py (entry scripts)
                                   - skills/**/*.md
  scripts/validators/X.py        grep `verify-X.py` reference in:
                                   - commands/vg/**/*.md
                                   - scripts/validators/registry.yaml
  commands/vg/_shared/lens-      grep `lens-X` reference in:
    prompts/lens-X.md              - commands/vg/**/*.md
                                   - skills/**/*.md
  commands/vg/_shared/lib/X.sh   grep `source.*lib/X.sh` OR
                                 `lib/X.sh` reference in:
                                   - commands/vg/**/*.md

Verdicts per artifact:
  WIRED   — at least one caller in skill .md or entry script
  PARTIAL — module imported but only some public functions called (Python only)
  ORPHAN  — 0 callers anywhere

Transitive wiring: a runtime module imported only by another runtime module
is WIRED iff that downstream module is WIRED. Cycle-safe.

Output: JSON per validator-output schema. ORPHAN/PARTIAL → BLOCK by default,
--severity warn for migration grace. Optional --report-md writes detailed
markdown.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, emit_and_exit, timer  # noqa: E402


# ─── Surface discovery ─────────────────────────────────────────────


@dataclass
class Artifact:
    """One auditable thing — module, validator, lens, or lib helper."""
    kind: str  # "runtime" | "validator" | "lens" | "lib"
    name: str  # module name (no extension)
    path: Path
    public_symbols: list[str] = field(default_factory=list)
    callers: dict[str, list[str]] = field(default_factory=dict)
    # callers[symbol] = [caller_file_paths...]
    # for non-Python kinds, single key "_module" used


PUBLIC_SYMBOL_RE = re.compile(
    r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)


def discover_runtime_modules(repo: Path) -> list[Artifact]:
    out: list[Artifact] = []
    rt = repo / "scripts" / "runtime"
    if not rt.exists():
        return out
    for p in sorted(rt.glob("*.py")):
        if p.name.startswith("_") or p.name == "__init__.py":
            continue
        symbols = []
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            for m in PUBLIC_SYMBOL_RE.finditer(text):
                sym = m.group(1)
                if sym.startswith("_"):
                    continue  # private
                # Skip exception types — they're auxiliary; "imported in
                # except blocks but not called" is normal usage. Treating
                # them as wireable creates false-positive PARTIAL noise.
                if sym.endswith("Error") or sym.endswith("Exception"):
                    continue
                symbols.append(sym)
        except OSError:
            continue
        out.append(Artifact(kind="runtime", name=p.stem, path=p,
                            public_symbols=symbols))
    return out


def discover_validators(repo: Path) -> list[Artifact]:
    out: list[Artifact] = []
    v = repo / "scripts" / "validators"
    if not v.exists():
        return out
    for p in sorted(v.glob("*.py")):
        if p.name.startswith("_"):
            continue
        out.append(Artifact(kind="validator", name=p.stem, path=p,
                            public_symbols=["_module"]))
    return out


def discover_lens_prompts(repo: Path) -> list[Artifact]:
    out: list[Artifact] = []
    lp = repo / "commands" / "vg" / "_shared" / "lens-prompts"
    if not lp.exists():
        return out
    for p in sorted(lp.glob("lens-*.md")):
        out.append(Artifact(kind="lens", name=p.stem, path=p,
                            public_symbols=["_module"]))
    return out


def discover_lib_helpers(repo: Path) -> list[Artifact]:
    out: list[Artifact] = []
    lib = repo / "commands" / "vg" / "_shared" / "lib"
    if not lib.exists():
        return out
    for p in sorted(lib.glob("*.sh")):
        out.append(Artifact(kind="lib", name=p.stem, path=p,
                            public_symbols=["_module"]))
    return out


# ─── Caller search ─────────────────────────────────────────────────


def _read_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def search_skill_md_files(repo: Path) -> list[Path]:
    """All skill / command .md files where wiring should appear."""
    out: list[Path] = []
    for sub in ("commands/vg", "skills"):
        root = repo / sub
        if not root.exists():
            continue
        out.extend(root.rglob("*.md"))
    return out


def search_entry_scripts(repo: Path) -> list[Path]:
    """Entry-point Python scripts (excluding runtime/ + validators/)."""
    out: list[Path] = []
    s = repo / "scripts"
    if not s.exists():
        return out
    for p in s.rglob("*.py"):
        rel = p.relative_to(s)
        parts = rel.parts
        if parts and parts[0] in ("runtime", "validators"):
            continue
        if p.name.startswith("_"):
            continue
        out.append(p)
    return out


def find_runtime_callers(
    artifact: Artifact,
    skill_files: list[Path],
    entry_scripts: list[Path],
    runtime_files: list[Path],
) -> dict[str, list[str]]:
    """For each public symbol, find files that import + use it.

    Two-stage detection (handles multi-line `from X import (` and comments):

    1. Module-presence: any of these tokens appears in the file:
         - `runtime.<name>`
         - `from .<name> import` (relative inside runtime/)
         - `from . import …<name>…` (relative bare)
       → If yes, the importer module is a candidate caller.

    2. Per-symbol: scan the file for the symbol token (word-bounded). If
       found AND module-presence true → record as caller for that symbol.
       This catches `from runtime.X import Y` (multi-line + commented) +
       direct attribute use `runtime.X.Y` consistently.
    """
    name = artifact.name
    callers: dict[str, list[str]] = {sym: [] for sym in artifact.public_symbols}

    presence_re = re.compile(
        rf"(?:runtime\.{re.escape(name)}\b|"
        rf"from\s+\.{re.escape(name)}\s+import\b|"
        rf"from\s+\.\s+import\s+[^\n]*\b{re.escape(name)}\b)",
    )

    def scan_file(path: Path, label: str) -> None:
        text = _read_safe(path)
        if not text:
            return
        if not presence_re.search(text):
            return
        # Module is imported — now check per-symbol usage.
        for sym in artifact.public_symbols:
            sym_re = re.compile(rf"\b{re.escape(sym)}\b")
            if sym_re.search(text):
                if label not in callers[sym]:
                    callers[sym].append(label)

    for f in skill_files:
        scan_file(f, str(f))
    for f in entry_scripts:
        scan_file(f, str(f))
    for f in runtime_files:
        if f == artifact.path:
            continue
        scan_file(f, f"runtime/{f.name}")

    return callers


def find_validator_callers(
    artifact: Artifact,
    skill_files: list[Path],
    registry_path: Path | None,
) -> dict[str, list[str]]:
    name = artifact.name  # e.g. "verify-blueprint-completeness"
    callers: list[str] = []
    pat = re.compile(rf"\b{re.escape(name)}(?:\.py)?\b")
    for f in skill_files:
        text = _read_safe(f)
        if pat.search(text):
            callers.append(str(f))
    if registry_path and registry_path.exists():
        text = _read_safe(registry_path)
        if pat.search(text):
            callers.append(str(registry_path))
    return {"_module": callers}


def find_lens_callers(
    artifact: Artifact,
    skill_files: list[Path],
) -> dict[str, list[str]]:
    name = artifact.name  # e.g. "lens-csrf"
    callers: list[str] = []
    pat = re.compile(rf"\b{re.escape(name)}\b")
    for f in skill_files:
        # skip the lens prompt itself
        if f.name == f"{name}.md":
            continue
        text = _read_safe(f)
        if pat.search(text):
            callers.append(str(f))
    return {"_module": callers}


def find_lib_callers(
    artifact: Artifact,
    skill_files: list[Path],
) -> dict[str, list[str]]:
    name = artifact.name  # e.g. "block-resolver"
    callers: list[str] = []
    # Match `source ... lib/X.sh` or bare `lib/X.sh`
    pat = re.compile(
        rf"(?:source\s+[^\n]*lib/{re.escape(name)}\.sh|"
        rf"lib/{re.escape(name)}\.sh)",
    )
    for f in skill_files:
        text = _read_safe(f)
        if pat.search(text):
            callers.append(str(f))
    return {"_module": callers}


# ─── Verdict ───────────────────────────────────────────────────────


def classify(artifact: Artifact) -> str:
    """WIRED | PARTIAL | ORPHAN — based on per-symbol caller presence."""
    if not artifact.public_symbols:
        return "ORPHAN"
    wired_syms = sum(1 for s in artifact.public_symbols if artifact.callers.get(s))
    if wired_syms == 0:
        return "ORPHAN"
    if wired_syms == len(artifact.public_symbols):
        return "WIRED"
    return "PARTIAL"


def resolve_transitive_wiring(artifacts: list[Artifact]) -> None:
    """Runtime modules imported only by other runtime modules — wire them
    transitively iff the downstream module reaches a skill / entry script.

    Algorithm: BFS from skill/entry callers. A module's symbol is "true wired"
    if at least one caller is NOT a runtime/ file, OR a runtime caller's
    own symbols are true-wired.
    """
    by_path: dict[str, Artifact] = {str(a.path): a for a in artifacts
                                    if a.kind == "runtime"}
    name_to_artifact: dict[str, Artifact] = {a.name: a for a in artifacts
                                             if a.kind == "runtime"}

    # Seed: artifacts with non-runtime callers
    true_wired_modules: set[str] = set()
    for a in artifacts:
        if a.kind != "runtime":
            continue
        for sym, callers in a.callers.items():
            if any(not c.startswith("runtime/") for c in callers):
                true_wired_modules.add(a.name)
                break

    # Propagate: if module M is wired and M's file imports another runtime
    # module N, then N is also wired.
    changed = True
    while changed:
        changed = False
        for m_name in list(true_wired_modules):
            m = name_to_artifact.get(m_name)
            if not m:
                continue
            text = _read_safe(m.path)
            for n in name_to_artifact.values():
                if n.name in true_wired_modules:
                    continue
                pat = re.compile(
                    rf"from\s+\.{re.escape(n.name)}\s+import|"
                    rf"from\s+runtime\.{re.escape(n.name)}\s+import|"
                    rf"import\s+runtime\.{re.escape(n.name)}\b",
                )
                if pat.search(text):
                    true_wired_modules.add(n.name)
                    changed = True

    # Re-stamp callers: if module is true_wired_modules, ensure at least one
    # symbol shows a transitive label so classify() reports WIRED.
    for a in artifacts:
        if a.kind != "runtime":
            continue
        if a.name in true_wired_modules:
            for sym in a.public_symbols:
                # If this symbol has only runtime callers, add transitive tag
                callers = a.callers.get(sym, [])
                if callers and all(c.startswith("runtime/") for c in callers):
                    a.callers[sym].append("[transitive]")
                elif not callers:
                    # Symbol genuinely unused even within runtime — leave as orphan
                    pass


# ─── Main ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify runtime modules / validators / lens prompts / lib helpers "
            "are wired into the pipeline (no orphan code)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("VG_REPO_ROOT") or os.getcwd(),
        help="Root of the VG repo (defaults to VG_REPO_ROOT or cwd)",
    )
    parser.add_argument(
        "--severity",
        choices=["block", "warn"],
        default="block",
    )
    parser.add_argument(
        "--report-md",
        help="Optional path to write markdown audit report",
    )
    parser.add_argument(
        "--kind",
        choices=["runtime", "validator", "lens", "lib", "all"],
        default="all",
        help="Limit audit to one surface (default: all)",
    )
    parser.add_argument(
        "--allow-orphans",
        action="store_true",
        help="Override: emit WARN instead of BLOCK. Logs override-debt entry.",
    )
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    out = Output(validator="runtime-wired")

    with timer(out):
        # 1. Discover artifacts
        artifacts: list[Artifact] = []
        if args.kind in ("runtime", "all"):
            artifacts.extend(discover_runtime_modules(repo))
        if args.kind in ("validator", "all"):
            artifacts.extend(discover_validators(repo))
        if args.kind in ("lens", "all"):
            artifacts.extend(discover_lens_prompts(repo))
        if args.kind in ("lib", "all"):
            artifacts.extend(discover_lib_helpers(repo))

        if not artifacts:
            out.add(Evidence(
                type="no_artifacts_found",
                message=f"No auditable surfaces under {repo}",
            ), escalate=False)
            emit_and_exit(out)

        # 2. Cache caller corpus
        skill_files = search_skill_md_files(repo)
        entry_scripts = search_entry_scripts(repo)
        runtime_files = [a.path for a in artifacts if a.kind == "runtime"]
        registry_path = repo / "scripts" / "validators" / "registry.yaml"

        # 3. Run searches
        for a in artifacts:
            if a.kind == "runtime":
                a.callers = find_runtime_callers(
                    a, skill_files, entry_scripts, runtime_files,
                )
            elif a.kind == "validator":
                a.callers = find_validator_callers(a, skill_files, registry_path)
            elif a.kind == "lens":
                a.callers = find_lens_callers(a, skill_files)
            elif a.kind == "lib":
                a.callers = find_lib_callers(a, skill_files)

        # 4. Transitive wiring for runtime
        resolve_transitive_wiring(artifacts)

        # 5. Classify + emit
        counts = {"WIRED": 0, "PARTIAL": 0, "ORPHAN": 0}
        rows: list[tuple[Artifact, str]] = []
        for a in artifacts:
            verdict = classify(a)
            counts[verdict] += 1
            rows.append((a, verdict))

        # Summary first
        total = len(artifacts)
        out.add(
            Evidence(
                type="audit_summary",
                message=(
                    f"runtime-wired audit: {total} artifacts. "
                    f"WIRED={counts['WIRED']}, PARTIAL={counts['PARTIAL']}, "
                    f"ORPHAN={counts['ORPHAN']}"
                ),
            ),
            escalate=False,
        )

        # Per-orphan / partial issue
        for a, v in rows:
            if v == "WIRED":
                continue
            unwired = [s for s in a.public_symbols
                       if not a.callers.get(s)]
            if v == "ORPHAN":
                msg = f"{a.kind}/{a.name} — 0 callers in any skill or entry script"
            else:
                msg = (
                    f"{a.kind}/{a.name} — partial wiring: "
                    f"{len(unwired)}/{len(a.public_symbols)} symbols unused "
                    f"({', '.join(unwired[:5])}"
                    f"{'...' if len(unwired) > 5 else ''})"
                )
            fix_hint = ""
            if a.kind == "runtime":
                fix_hint = (
                    f"Wire `from runtime.{a.name} import …` into a skill "
                    f"(commands/vg/*.md heredoc) or a scripts/*.py entry "
                    f"point. If module is intentionally unused, delete it "
                    f"or move to scripts/_attic/."
                )
            elif a.kind == "validator":
                fix_hint = (
                    f"Reference `{a.name}.py` from a skill .md OR add an "
                    f"entry to scripts/validators/registry.yaml so /vg:health "
                    f"+ relevant skill picks it up."
                )
            elif a.kind == "lens":
                fix_hint = (
                    f"Reference `{a.name}` from /vg:review or /vg:roam .md so "
                    f"the lens prompt is dispatched to a Haiku scanner."
                )
            elif a.kind == "lib":
                fix_hint = (
                    f"`source` {a.name}.sh from a skill .md, OR delete if "
                    f"obsolete."
                )
            out.add(
                Evidence(
                    type=f"{v.lower()}_artifact",
                    message=msg,
                    file=str(a.path),
                    fix_hint=fix_hint,
                ),
                escalate=(args.severity == "block" and not args.allow_orphans),
            )

        # 6. Optional markdown report
        if args.report_md:
            _write_report(Path(args.report_md), rows, counts, repo)

        # 7. Severity downgrade
        if (counts["ORPHAN"] or counts["PARTIAL"]) and (
            args.severity == "warn" or args.allow_orphans
        ):
            if out.verdict == "BLOCK":
                out.verdict = "WARN"
            out.add(
                Evidence(
                    type="severity_downgraded",
                    message=(
                        f"{counts['ORPHAN']} orphan + {counts['PARTIAL']} "
                        f"partial artifacts downgraded to WARN."
                    ),
                ),
                escalate=False,
            )

    emit_and_exit(out)


def _write_report(
    path: Path,
    rows: list[tuple[Artifact, str]],
    counts: dict[str, int],
    repo: Path,
) -> None:
    lines = [
        "# Runtime wire-up audit",
        "",
        f"Repo: `{repo}`",
        "",
        "## Summary",
        "",
        f"- WIRED:   {counts['WIRED']}",
        f"- PARTIAL: {counts['PARTIAL']}",
        f"- ORPHAN:  {counts['ORPHAN']}",
        "",
        "## Orphan + partial",
        "",
        "| Kind | Name | Verdict | Unused symbols |",
        "|------|------|---------|----------------|",
    ]
    for a, v in rows:
        if v == "WIRED":
            continue
        unused = [s for s in a.public_symbols if not a.callers.get(s)]
        unused_str = ", ".join(unused[:8]) or "_module"
        if len(unused) > 8:
            unused_str += f", … (+{len(unused) - 8})"
        lines.append(f"| {a.kind} | `{a.name}` | {v} | {unused_str} |")
    lines.append("")
    lines.append("## Wired")
    lines.append("")
    lines.append("| Kind | Name | Symbol count |")
    lines.append("|------|------|--------------|")
    for a, v in rows:
        if v != "WIRED":
            continue
        lines.append(f"| {a.kind} | `{a.name}` | {len(a.public_symbols)} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
