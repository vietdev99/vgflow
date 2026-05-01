#!/usr/bin/env python3
"""AI-driven UI scope detection for blueprint preflight (replaces grep heuristic).

Spawns an isolated Haiku subagent (zero parent context) to read SPECS.md +
CONTEXT.md and decide whether the phase has UI in scope. Output is cached to
`{phase_dir}/.ui-scope.json` and consumed as authoritative ground truth by:

  - blueprint.md step 0_design_discovery (gates 2b6_ui_spec / 2b6b / 2b6c)
  - validators/verify-ui-scope-coherence.py (cross-check vs PLAN.md FE tasks)

Why AI not grep:
  Phase 4.3 example — SPECS line 5: "Phase này CHỈ build backend APIs...
  UI portal Ở Phase 6/7/8". Keyword grep matches "UI" in the EXCLUSION
  clause and falsely flags has_ui=true. AI semantic reading distinguishes
  scope-inclusion ("phase này có UI") vs scope-exclusion ("UI deferred to
  Phase X"). Same lesson L-002 motivated Phase 19 D-04 view decomposition.

Confidence routing (matches goal-classifier.sh pattern):
  - >= 0.8: auto-apply, write cache, exit 0
  - 0.5-0.8: emit pending JSON for caller to spawn Haiku tie-break, exit 2
  - < 0.5: emit pending JSON for caller to AskUserQuestion, exit 3

Output JSON schema (.ui-scope.json):
  {
    "has_ui": bool,
    "confidence": float (0.0..1.0),
    "evidence": str (quoted phrase from SPECS/CONTEXT),
    "deferred_to": str|null (e.g. "Phase 6"),
    "ui_kinds": list[str] (e.g. ["dashboard","form","modal"]),
    "model": str ("haiku-4.5" or fallback),
    "detected_at": str (ISO8601 UTC),
    "method": "ai-semantic" | "user-confirmed" | "fallback-grep"
  }

Usage:
  python3 detect-ui-scope.py --phase-dir .vg/phases/04.3-... --output .ui-scope.json
  python3 detect-ui-scope.py --phase-dir ... --force          # bypass cache
  python3 detect-ui-scope.py --phase-dir ... --grep-fallback  # skip AI, use legacy grep
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path


HAIKU_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_CLI_TIMEOUT_S = 120

PROMPT_TEMPLATE = """You are a phase scope analyzer. Read the SPECS and CONTEXT below and decide
whether THIS phase ships user-facing UI code (web pages, mobile screens, admin
dashboards, components) — OR — is backend-only / infra / data / tooling.

CRITICAL distinction: many specs mention UI as EXCLUSION ("UI portal in Phase 6/7/8"
or "KHÔNG làm trong phase này: UI portal"). That means UI is OUT of scope here.
Similarly "consumed by Phase X" or "Phase X owns UI" means UI is downstream.

You output ONLY a single-line JSON object. No prose, no code fence, no preamble.

Schema:
{{
  "has_ui": true|false,
  "confidence": 0.0-1.0,
  "evidence": "<one-sentence quote or paraphrase from SPECS/CONTEXT supporting the decision>",
  "deferred_to": "<Phase X>" or null,
  "ui_kinds": ["dashboard","form","modal","table","wizard","sidebar"] or []
}}

Confidence guide:
  0.9-1.0 — explicit clause "this phase has UI" or "this phase is backend-only / no UI"
  0.7-0.9 — strong inference from actor list (merchant clicks form) or file paths (.tsx)
  0.5-0.7 — mixed signals or short SPECS
  0.0-0.5 — ambiguous, not enough evidence

═════════════════════════════════════════════════════════════════════════
SPECS.md
═════════════════════════════════════════════════════════════════════════
{specs}

═════════════════════════════════════════════════════════════════════════
CONTEXT.md (decisions excerpt)
═════════════════════════════════════════════════════════════════════════
{context}

═════════════════════════════════════════════════════════════════════════

Output the JSON object on a single line. Nothing else.
"""


def trim(text: str, max_lines: int = 200) -> str:
    """Limit prompt context to keep token cost low + Haiku focused."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    head = lines[: max_lines * 2 // 3]
    tail = lines[-(max_lines // 3):]
    return "\n".join(head + ["", f"... [{len(lines) - max_lines} lines truncated] ...", ""] + tail)


def parse_haiku_output(raw: str) -> dict | None:
    """Extract single JSON object from Haiku stdout. Tolerate prose preamble."""
    raw = raw.strip()
    # Try whole output first
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Find first `{...}` block
    m = re.search(r"\{[^{}]*\"has_ui\"[^{}]*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    # Fallback: try line-by-line
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("{") and "has_ui" in line:
            try:
                return json.loads(line)
            except Exception:
                continue
    return None


def grep_fallback(specs: str, context: str) -> dict:
    """Legacy heuristic — only used when AI unavailable. Conservative.

    Inclusion signals: actor list + file paths + UI verbs.
    Exclusion signals: "Phase này CHỈ build backend", "UI portal ở Phase X",
    "no UI", "API only".
    """
    text = (specs + "\n" + context).lower()

    # Strong exclusions first
    exclusion_patterns = [
        r"\bui portal\b.*\bphase\b",
        r"\bphase này chỉ build\b.*\bbackend\b",
        r"\bbackend[- ]only\b",
        r"\bno ui\b",
        r"\bapi only\b",
        r"\bui.*ở phase \d+\b",
        r"\bdefer.*ui.*to phase\b",
    ]
    for pat in exclusion_patterns:
        if re.search(pat, text, re.IGNORECASE):
            return {
                "has_ui": False,
                "confidence": 0.7,
                "evidence": f"grep matched exclusion pattern: {pat}",
                "deferred_to": None,
                "ui_kinds": [],
            }

    # Inclusion signals (count weighted)
    score = 0
    if re.search(r"\.tsx\b|\.jsx\b|\.vue\b|\.svelte\b", text):
        score += 3
    if re.search(r"\bapps/(admin|merchant|vendor|web)/", text):
        score += 3
    if re.search(r"\b(dashboard|form|modal|wizard|sidebar|topbar)\b", text):
        score += 2
    if re.search(r"\bgiao diện\b|\bmàn hình\b", text):
        score += 2

    has_ui = score >= 3
    return {
        "has_ui": has_ui,
        "confidence": min(0.6, score / 10),  # cap fallback confidence at 0.6
        "evidence": f"grep heuristic score={score}",
        "deferred_to": None,
        "ui_kinds": [],
    }


def invoke_haiku(specs: str, context: str) -> tuple[dict | None, str]:
    """Invoke Haiku via `claude --model haiku -p`. Returns (parsed_json, raw_stdout)."""
    prompt = PROMPT_TEMPLATE.format(
        specs=trim(specs, 250),
        context=trim(context, 200),
    )

    cmd = [
        "claude",
        "--model", HAIKU_MODEL,
        "-p",
        prompt,
    ]

    # CRITICAL: run subprocess from /tmp so VG Stop hook doesn't fire on exit
    # (Stop hook lives in .claude/settings.json under project root and would
    # intercept stdout to inject orchestrator verifier output otherwise).
    # Using --bare instead would skip auth/keychain — fails in interactive setups.
    import tempfile
    sandbox_cwd = tempfile.gettempdir()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CLAUDE_CLI_TIMEOUT_S,
            cwd=sandbox_cwd,
        )
    except FileNotFoundError:
        return None, "claude CLI not found in PATH"
    except subprocess.TimeoutExpired:
        return None, f"claude CLI timeout after {CLAUDE_CLI_TIMEOUT_S}s"
    except Exception as e:
        return None, f"claude CLI error: {e}"

    if proc.returncode != 0:
        return None, f"claude exit={proc.returncode} stderr={proc.stderr[:500]}"

    parsed = parse_haiku_output(proc.stdout)
    return parsed, proc.stdout


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase-dir", required=True, help="phase directory (contains SPECS.md, CONTEXT.md)")
    p.add_argument("--output", default=".ui-scope.json", help="output JSON path (relative to phase-dir)")
    p.add_argument("--force", action="store_true", help="bypass cache, re-detect")
    p.add_argument("--grep-fallback", action="store_true", help="skip AI, use legacy grep heuristic")
    p.add_argument("--quiet", action="store_true", help="suppress narrative; emit only JSON to stdout")
    args = p.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    out_path = phase_dir / args.output

    if not phase_dir.is_dir():
        print(f"⛔ phase dir not found: {phase_dir}", file=sys.stderr)
        return 1

    # Cache hit
    if out_path.exists() and not args.force:
        cached = json.loads(out_path.read_text(encoding="utf-8"))
        if not args.quiet:
            print(f"✓ cached: has_ui={cached.get('has_ui')} confidence={cached.get('confidence')} ({out_path})", file=sys.stderr)
        print(json.dumps(cached))
        return 0

    specs_path = phase_dir / "SPECS.md"
    context_path = phase_dir / "CONTEXT.md"

    if not specs_path.exists():
        print(f"⛔ SPECS.md not found: {specs_path}", file=sys.stderr)
        return 1

    specs = specs_path.read_text(encoding="utf-8", errors="ignore")
    context = context_path.read_text(encoding="utf-8", errors="ignore") if context_path.exists() else ""

    if args.grep_fallback:
        result = grep_fallback(specs, context)
        result["model"] = "fallback-grep"
        result["method"] = "fallback-grep"
    else:
        if not args.quiet:
            print(f"▸ Detecting UI scope via Haiku ({HAIKU_MODEL})...", file=sys.stderr)
        parsed, raw = invoke_haiku(specs, context)
        if parsed is None:
            print(f"⚠ Haiku failed ({raw[:200]}), falling back to grep heuristic", file=sys.stderr)
            result = grep_fallback(specs, context)
            result["model"] = "fallback-grep"
            result["method"] = "fallback-grep-after-ai-failure"
            result["ai_error"] = raw[:200]
        else:
            result = parsed
            result["model"] = HAIKU_MODEL
            result["method"] = "ai-semantic"

    # Required fields normalization
    result.setdefault("has_ui", False)
    result.setdefault("confidence", 0.0)
    result.setdefault("evidence", "")
    result.setdefault("deferred_to", None)
    result.setdefault("ui_kinds", [])
    result["detected_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    result["phase_dir"] = str(phase_dir)

    # Confidence band routing
    confidence = float(result.get("confidence", 0.0))
    if confidence >= 0.8:
        result["band"] = "auto"
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if not args.quiet:
            print(
                f"✓ has_ui={result['has_ui']} confidence={confidence:.2f} (AUTO-APPLY)\n"
                f"  evidence: {result['evidence'][:120]}\n"
                f"  written: {out_path}",
                file=sys.stderr,
            )
        print(json.dumps(result))
        return 0
    elif confidence >= 0.5:
        result["band"] = "tie-break-needed"
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if not args.quiet:
            print(
                f"⚠ has_ui={result['has_ui']} confidence={confidence:.2f} (TIE-BREAK NEEDED)\n"
                f"  caller should spawn second AI with adversarial prompt or AskUserQuestion",
                file=sys.stderr,
            )
        print(json.dumps(result))
        return 2
    else:
        result["band"] = "user-confirmation-needed"
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if not args.quiet:
            print(
                f"⛔ has_ui={result['has_ui']} confidence={confidence:.2f} (USER CONFIRMATION REQUIRED)\n"
                f"  caller should AskUserQuestion: 'Phase này có UI không?'",
                file=sys.stderr,
            )
        print(json.dumps(result))
        return 3


if __name__ == "__main__":
    sys.exit(main())
