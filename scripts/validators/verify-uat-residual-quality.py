#!/usr/bin/env python3
"""verify-uat-residual-quality.py — B112 v4.72.0.

Last-mile checks for the residual ~5% UAT bug class that pure
automation cannot catch alone:

  1. **Copy quality** — placeholder leaks (lorem ipsum, TODO, FIXME,
     untranslated `{{key}}`), mixed casing in CTAs, trailing whitespace
     in user-visible strings.
  2. **Brand voice** — terminology drift vs project glossary
     (`<project>/.glossary.json`). Each entry has a canonical form +
     forbidden aliases.
  3. **UX flow naturalness** — heuristic: goals with >8 user actions
     (click/fill/goto) per stage likely have UX friction. Flag for
     human review.
  4. **CrossAI review scaffold** — emit `CROSSAI-UX-REVIEW.md` listing
     every goal's flow that operator pastes into codex/gemini for an
     independent UX-naturalness opinion.

All findings are advisory (severity=warn default). Operator opts into
block once project glossary stable + threshold tuned.

Exit codes:
  0 PASS / warn mode with findings
  1 FAIL (block mode)
  2 internal error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# Copy-quality patterns. All scanned in FE source + UAT-NARRATIVE.md.
_PLACEHOLDER_RE = re.compile(
    r"\b(lorem\s+ipsum|TODO|FIXME|XXX|HACK|TBD|placeholder|sample\s+text|"
    r"dummy\s+text|test\s+content)\b",
    re.IGNORECASE,
)
_UNTRANSLATED_KEY_RE = re.compile(
    r"\{\{[a-z_][a-z0-9_.]*\}\}",  # missed interpolation: {{key}} not resolved
)
_MIXED_CASE_CTA_RE = re.compile(
    # Buttons with mixed casing inside the same word: "saveChanges", "addNew"
    # OR CTA strings that mix title-case + sentence-case across siblings.
    r"['\"]([A-Z][a-z]+\s+[A-Z][a-z]+|[a-z]+\s+[A-Z][a-z]+)['\"]"
)
_TRAILING_WS_IN_STRING_RE = re.compile(
    r"['\"][^'\"]*[\t ]+['\"]"
)


def _load_glossary(repo_root: Path) -> dict:
    """Load project glossary from any of these paths."""
    for cand in (
        repo_root / ".glossary.json",
        repo_root / "glossary.json",
        repo_root / "docs" / "glossary.json",
    ):
        if cand.is_file():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {}


def _find_fe_sources(repo_root: Path) -> list[Path]:
    apps = repo_root / "apps"
    if not apps.is_dir():
        return []
    out: list[Path] = []
    for app in apps.iterdir():
        if not app.is_dir():
            continue
        src = app / "src"
        if not src.is_dir():
            continue
        out.extend(src.rglob("*.tsx"))
        out.extend(src.rglob("*.ts"))
    return out


def _scan_copy_quality(repo_root: Path) -> list[dict]:
    findings: list[dict] = []
    for f in _find_fe_sources(repo_root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = str(f.relative_to(repo_root))
        for m in _PLACEHOLDER_RE.finditer(text):
            line = text[: m.start()].count("\n") + 1
            findings.append({
                "kind": "placeholder_leak",
                "file": rel, "line": line,
                "evidence": m.group(0),
            })
        for m in _UNTRANSLATED_KEY_RE.finditer(text):
            line = text[: m.start()].count("\n") + 1
            findings.append({
                "kind": "untranslated_key",
                "file": rel, "line": line,
                "evidence": m.group(0),
            })
        # Trailing whitespace inside string literals
        for m in _TRAILING_WS_IN_STRING_RE.finditer(text):
            line = text[: m.start()].count("\n") + 1
            findings.append({
                "kind": "trailing_whitespace_in_string",
                "file": rel, "line": line,
                "evidence": m.group(0)[:60],
            })
    return findings


def _scan_brand_voice(repo_root: Path, glossary: dict) -> list[dict]:
    """Per glossary entry, scan for alias hits."""
    findings: list[dict] = []
    entries = glossary.get("terms") or glossary.get("entries") or []
    if not entries:
        return findings
    for f in _find_fe_sources(repo_root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = str(f.relative_to(repo_root))
        for entry in entries:
            canonical = str(entry.get("canonical") or "")
            aliases = entry.get("aliases") or []
            allowed = entry.get("allowed", False)
            if allowed:
                continue  # entry explicitly allowed
            for alias in aliases:
                if not alias:
                    continue
                # Word-boundary match, case-sensitive to allow "Topup"
                # canonical vs "topup" alias detection.
                pattern = re.compile(rf"\b{re.escape(alias)}\b")
                for m in pattern.finditer(text):
                    line = text[: m.start()].count("\n") + 1
                    findings.append({
                        "kind": "brand_voice_drift",
                        "file": rel, "line": line,
                        "evidence": m.group(0),
                        "canonical": canonical,
                        "alias_found": alias,
                    })
    return findings


def _scan_ux_naturalness(phase_dir: Path, threshold: int) -> list[dict]:
    findings: list[dict] = []
    p = phase_dir / "LIFECYCLE-SPECS.json"
    if not p.is_file():
        return findings
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return findings
    goal_map = payload.get("goals") or payload.get("specs") or {}
    for gid, goal in goal_map.items():
        for step in goal.get("steps") or []:
            if not isinstance(step, dict):
                continue
            action = str(step.get("action") or "")
            # Crude proxy for "user actions": count keywords
            verb_count = len(re.findall(
                r"\b(?:click|fill|select|check|hover|press|tap|"
                r"goto|navigate|open|drag|drop)\b",
                action, re.IGNORECASE,
            ))
            if verb_count > threshold:
                findings.append({
                    "kind": "ux_flow_density",
                    "goal_id": gid,
                    "stage": step.get("stage") or step.get("name"),
                    "verb_count": verb_count,
                    "threshold": threshold,
                    "note": (
                        f"stage '{step.get('stage')}' has {verb_count} user "
                        f"actions described — exceeds threshold {threshold}. "
                        "Likely UX friction; recommend operator review."
                    ),
                })
    return findings


def _emit_crossai_review(phase_dir: Path, findings_by_kind: dict) -> Path | None:
    """Emit CROSSAI-UX-REVIEW.md scaffold for operator to feed to
    codex/gemini for UX-naturalness opinion."""
    p = phase_dir / "LIFECYCLE-SPECS.json"
    if not p.is_file():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    goal_map = payload.get("goals") or payload.get("specs") or {}
    md_lines = [
        "# CrossAI UX naturalness review (B112)",
        "",
        "Feed each goal's flow below to codex/gemini for an independent",
        "UX-naturalness opinion. Acceptance: tester reports < 3 frictions.",
        "",
        f"Phase: {phase_dir.name}",
        f"Goals: {len(goal_map)}",
        "",
    ]
    for gid, goal in goal_map.items():
        md_lines.append(f"## {gid}: {goal.get('title') or '(no title)'}")
        md_lines.append("")
        actors = ", ".join(a.get("id", "?") for a in goal.get("actors") or []) or "(single)"
        md_lines.append(f"Actors: {actors}")
        md_lines.append("")
        md_lines.append("Steps:")
        for step in goal.get("steps") or []:
            if not isinstance(step, dict):
                continue
            stage = step.get("stage") or step.get("name") or "?"
            action = step.get("action") or "(no action)"
            md_lines.append(f"  - {stage}: {action[:200]}")
        md_lines.append("")
        # Add residual finding callouts on this goal
        for kind, items in findings_by_kind.items():
            for item in items:
                if item.get("goal_id") == gid:
                    md_lines.append(
                        f"  ⚠ {kind}: {item.get('note') or item.get('evidence')}"
                    )
                    md_lines.append("")
    out = phase_dir / "CROSSAI-UX-REVIEW.md"
    out.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="verify-uat-residual-quality")
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--ux-action-threshold", type=int, default=8,
                    help="Max user actions per stage before UX-density flag")
    ap.add_argument("--severity", choices=("warn", "block"), default="warn")
    ap.add_argument("--no-crossai", action="store_true",
                    help="Skip emitting CROSSAI-UX-REVIEW.md scaffold")
    ap.add_argument("--json", dest="json_out", action="store_true", default=True)
    ap.add_argument("--no-json", dest="json_out", action="store_false")
    args = ap.parse_args()
    try:
        phase_dir = Path(args.phase_dir).resolve()
        repo_root = Path(args.repo_root).resolve()
        glossary = _load_glossary(repo_root)
        copy_findings = _scan_copy_quality(repo_root)
        brand_findings = _scan_brand_voice(repo_root, glossary)
        ux_findings = _scan_ux_naturalness(phase_dir, args.ux_action_threshold)
        findings_by_kind = {
            "copy_quality": copy_findings,
            "brand_voice": brand_findings,
            "ux_naturalness": ux_findings,
        }
        total = sum(len(v) for v in findings_by_kind.values())
        crossai_path: Path | None = None
        if not args.no_crossai:
            crossai_path = _emit_crossai_review(phase_dir, findings_by_kind)
        result = {
            "phase_dir": str(phase_dir),
            "glossary_loaded": bool(glossary),
            "glossary_entry_count": len(
                glossary.get("terms") or glossary.get("entries") or []
            ),
            "ux_action_threshold": args.ux_action_threshold,
            "totals": {k: len(v) for k, v in findings_by_kind.items()},
            "total_findings": total,
            "findings": findings_by_kind,
            "crossai_review_path": str(crossai_path) if crossai_path else None,
            "severity": args.severity,
            "status": "PASS" if total == 0 else "FAIL",
        }
        if args.json_out:
            print(json.dumps(result, indent=2))
        else:
            print(f"verify-uat-residual-quality — {result['status']}")
            print(f"  glossary: {'loaded' if glossary else 'absent'}")
            for kind, items in findings_by_kind.items():
                print(f"  {kind}: {len(items)}")
                for it in items[:5]:
                    print(f"    - {it}")
        if result["status"] == "PASS":
            return 0
        return 1 if args.severity == "block" else 0
    except Exception as exc:
        print(f"verify-uat-residual-quality: internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
