"""Failure-time lesson retrieval — R9-A.

Codex audit (2026-05-05) finding: VG learn/lesson loop is PARTLY REAL but
NOT CLOSED. Lessons are captured by `vg-reflector` and `/vg:lesson`,
promoted via `/vg:learn`, and stored in `.vg/bootstrap/ACCEPTED.md`.
Some flows inject `<bootstrap_rules>` at spawn time (scope/blueprint/
build/test). HOWEVER, when a failure occurs (block / override / retry),
the recovery system uses a STATIC violation-type → recovery-path map
(`recovery_paths.py`) and NEVER queries prior lessons.

Result: a bug class that has been seen + learned about in the past does
not get its lesson surfaced when it recurs. The user has to remember.
"fail → learn → never fail again" was not guaranteed.

This module closes the loop by exposing two functions:

- `query_relevant_lessons(violation_type, gate_id, error_signature, phase, limit)`
    Read `.vg/bootstrap/ACCEPTED.md` and return ranked list of lessons
    whose metadata or body match the failure context. Match heuristics:

      1. violation_type substring match against rule's `applies_to` /
         `target_step` / `target.file` / `tags` / `scope`           [HIGH]
      2. gate_id substring match in same fields + body prose         [MED]
      3. error_signature keyword match in body / reason              [LOW]

    Sort: confidence DESC, then success_rate DESC, then hits DESC.

- `format_lessons_for_recovery(lessons)`
    Render a markdown block suitable for prompt injection into recovery
    suggestions / debug step output / orchestrator BLOCK messages.

Both functions are intentionally robust to a missing or malformed
`.vg/bootstrap/ACCEPTED.md`: they return empty / "no lessons found"
rather than raising.

Telemetry: callers should emit `recovery.lessons_consulted` whenever
`query_relevant_lessons` returns non-empty so we can later audit how
often the failure-time loop is actually firing.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------- helpers

def _repo_root() -> Path:
    """Return repo root.

    Honor `VG_REPO_ROOT` env var (set by orchestrator + recovery scripts);
    otherwise fall back to current working directory. We never ascend the
    tree because callers are expected to invoke from the project root.
    """
    return Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()


def _accepted_md_path() -> Path:
    return _repo_root() / ".vg" / "bootstrap" / "ACCEPTED.md"


def _rules_dir() -> Path:
    return _repo_root() / ".vg" / "bootstrap" / "rules"


def _coerce(v: str) -> Any:
    """Coerce a YAML-ish scalar to int/float/bool/str."""
    s = v.strip().strip("'\"")
    if not s or s.lower() == "null":
        return None
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    # list literal `[a, b]` — minimal support
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    return s


def _parse_accepted(text: str) -> list[dict]:
    """Parse `.vg/bootstrap/ACCEPTED.md` block-by-block.

    Each entry starts with `- id: L-XXX`. Indented `key: value` lines are
    captured as flat fields; nested blocks like `target:` become a sub-dict
    with one level of children, which is enough for the fields used here
    (`target.file`, `hit_outcomes.success_count`, ...).

    Returns list of dicts. Empty on missing/empty input — never raises.
    """
    entries: list[dict] = []
    if not text:
        return entries

    # Locate every `- id:` block start. We split AT those anchors so each
    # chunk is one entry's worth of YAML-ish content.
    starts = [m.start() for m in re.finditer(r"^- id:\s*\S", text, re.MULTILINE)]
    if not starts:
        return entries
    starts.append(len(text))

    for i in range(len(starts) - 1):
        block = text[starts[i]:starts[i + 1]]
        e: dict[str, Any] = {}
        nested_key: str | None = None
        nested_indent: int = -1

        for raw in block.splitlines():
            if not raw.strip():
                nested_key = None
                continue
            stripped = raw.lstrip()
            indent = len(raw) - len(stripped)

            # First line: `- id: L-XXX`
            if stripped.startswith("- id:"):
                _, _, val = stripped.partition(":")
                e["id"] = val.strip()
                continue

            # Detect nested block opener: `key:` with no value, indented 2
            if stripped.endswith(":") and ":" in stripped:
                k = stripped.rstrip(":").strip()
                if k and indent <= 4:
                    nested_key = k
                    nested_indent = indent
                    e.setdefault(nested_key, {})
                    continue

            if ":" not in stripped:
                continue

            k, _, v = stripped.partition(":")
            k = k.strip()
            v = _coerce(v)
            if not k:
                continue

            # Inside nested block?
            if nested_key and indent > nested_indent:
                if isinstance(e.get(nested_key), dict):
                    e[nested_key][k] = v
                continue
            else:
                nested_key = None

            e[k] = v

        if e.get("id"):
            entries.append(e)

    return entries


def _read_rule_body(rule_target: Any) -> str:
    """Resolve rule body text via `target.file` or `target` field.

    Rules referenced from ACCEPTED.md may live as
    `.vg/bootstrap/rules/<file>.md`. We strip frontmatter so the body
    text is clean for keyword search.
    """
    if isinstance(rule_target, dict):
        rel = rule_target.get("file") or rule_target.get("path") or ""
    else:
        rel = str(rule_target or "")

    if not rel:
        return ""

    # Resolve relative to .vg/bootstrap/ if path looks like rules/...,
    # else as-is from repo root.
    p = (_repo_root() / ".vg" / "bootstrap" / rel) if not Path(rel).is_absolute() else Path(rel)
    if not p.exists():
        # Fall back: try rules dir directly
        alt = _rules_dir() / Path(rel).name
        if alt.exists():
            p = alt
        else:
            return ""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    # Strip frontmatter
    if text.startswith("---"):
        end = text.find("\n---", 4)
        if end != -1:
            text = text[end + 4:].lstrip("\n")
    return text


def _success_rate(entry: dict) -> float | None:
    """Return success rate (0..100) or None when no outcomes recorded."""
    outcomes = entry.get("hit_outcomes")
    if isinstance(outcomes, dict):
        s = int(outcomes.get("success_count") or 0)
        f = int(outcomes.get("fail_count") or 0)
    else:
        s = int(entry.get("success_count") or 0)
        f = int(entry.get("fail_count") or 0)
    total = s + f
    if total <= 0:
        return None
    return round(100.0 * s / total, 1)


def _normalize(s: str | None) -> str:
    return (s or "").lower()


def _haystack(entry: dict, body: str) -> str:
    """Concatenate searchable text fields from an ACCEPTED.md entry + body."""
    parts = [
        entry.get("id"),
        entry.get("title"),
        entry.get("reason"),
        entry.get("origin"),
        entry.get("target_step"),
        entry.get("scope"),
        entry.get("tags"),
        entry.get("applies_to"),
    ]
    target = entry.get("target")
    if isinstance(target, dict):
        parts.append(target.get("file"))
        parts.append(target.get("step"))
    elif target:
        parts.append(target)
    flat: list[str] = []
    for p in parts:
        if p is None:
            continue
        if isinstance(p, list):
            flat.extend(str(x) for x in p)
        else:
            flat.append(str(p))
    flat.append(body or "")
    return _normalize("  ".join(flat))


def _applies_to(entry: dict) -> list[str]:
    """Best-effort derivation of `applies_to` tags.

    Most ACCEPTED.md entries don't carry an explicit `applies_to`; we
    synthesize from the most directly comparable fields so the renderer
    has something useful to display.
    """
    raw = entry.get("applies_to")
    if isinstance(raw, list):
        out = [str(x) for x in raw if x]
    elif raw:
        out = [str(raw)]
    else:
        out = []

    target = entry.get("target")
    if isinstance(target, dict) and target.get("step"):
        out.append(str(target["step"]))
    if entry.get("target_step"):
        out.append(str(entry["target_step"]))
    if entry.get("scope"):
        out.append(str(entry["scope"]))
    tags = entry.get("tags")
    if isinstance(tags, list):
        out.extend(str(t) for t in tags)
    elif tags:
        out.append(str(tags))
    # Dedupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


# ---------------------------------------------------------------- public API

def query_relevant_lessons(
    violation_type: str | None = None,
    gate_id: str | None = None,
    error_signature: str | None = None,
    phase: str | None = None,
    limit: int = 5,
    *,
    accepted_path: Path | None = None,
) -> list[dict]:
    """Return ranked list of accepted lessons matching the failure context.

    Each result dict has keys:
      - lesson_id        : "L-001"
      - title            : human-readable title (best effort)
      - rule_text        : rule body, frontmatter stripped
      - applies_to       : list of gate_ids / target_steps / tags
      - hits             : int
      - success_rate     : float | None (None when no outcomes recorded)
      - rule_path        : "rules/<file>.md" or "" when not present
      - confidence       : "high" | "medium" | "low"
      - score            : numeric score used for ranking
    """
    path = accepted_path if accepted_path is not None else _accepted_md_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    except OSError:
        text = ""
    entries = _parse_accepted(text)

    vt = _normalize(violation_type)
    gid = _normalize(gate_id)
    sig = _normalize(error_signature)

    # Build alternate match forms for violation_type: a recovery violation is
    # often namespaced like `validator:runtime-map-crud-depth`, but the lesson
    # body / reason field may mention only the bare slug. Try both.
    vt_forms: list[str] = []
    if vt:
        vt_forms.append(vt)
        if ":" in vt:
            vt_forms.append(vt.split(":", 1)[1])
        # Also try with hyphens/underscores collapsed to spaces — bodies often
        # phrase the slug in prose rather than identifier form.
        vt_forms.append(vt_forms[-1].replace("-", " ").replace("_", " "))

    gid_forms: list[str] = []
    if gid:
        gid_forms.append(gid)
        if ":" in gid:
            gid_forms.append(gid.split(":", 1)[1])

    sig_terms: list[str] = []
    if sig:
        # Tokenize on non-word chars; keep tokens >=4 chars to avoid noise.
        sig_terms = [t for t in re.split(r"\W+", sig) if len(t) >= 4]

    ranked: list[dict] = []
    for entry in entries:
        # Skip retracted/inactive rules — they should not influence recovery.
        status = (entry.get("status") or "active")
        if isinstance(status, str) and status.lower() not in ("active", "experimental"):
            continue

        body = _read_rule_body(entry.get("target"))
        hay = _haystack(entry, body)

        score = 0
        confidence = ""

        if vt_forms and any(f and f in hay for f in vt_forms):
            score += 100
            confidence = "high"
        if gid_forms and any(f and f in hay for f in gid_forms):
            score += 40
            confidence = confidence or "medium"
        if sig_terms:
            hits = sum(1 for t in sig_terms if t in hay)
            if hits:
                score += 5 * hits
                confidence = confidence or "low"

        if score == 0:
            continue

        sr = _success_rate(entry)
        # Tie-breaker contribution from efficacy
        score += int((sr or 0) / 10)
        score += int(entry.get("hits") or 0)

        title = (
            entry.get("title")
            or entry.get("reason")
            or (entry.get("target", {}) or {}).get("file") if isinstance(entry.get("target"), dict)
            else entry.get("reason")
        ) or entry.get("id") or "(untitled)"

        target = entry.get("target")
        rule_rel = ""
        if isinstance(target, dict) and target.get("file"):
            rule_rel = str(target["file"])

        ranked.append({
            "lesson_id": entry.get("id"),
            "title": title,
            "rule_text": body or str(entry.get("reason") or ""),
            "applies_to": _applies_to(entry),
            "hits": int(entry.get("hits") or 0),
            "success_rate": sr,
            "rule_path": rule_rel,
            "confidence": confidence or "low",
            "score": score,
            "phase": phase,
        })

    ranked.sort(
        key=lambda r: (
            r["score"],
            r["success_rate"] if r["success_rate"] is not None else -1,
            r["hits"],
        ),
        reverse=True,
    )
    return ranked[: max(0, int(limit))]


def format_lessons_for_recovery(lessons: list[dict]) -> str:
    """Render a markdown block for injection into recovery prompts."""
    if not lessons:
        return "No relevant prior lessons found."

    lines: list[str] = [
        "## Relevant prior lessons (from .vg/bootstrap/ACCEPTED.md)",
        "",
    ]
    for l in lessons:
        lid = l.get("lesson_id") or "?"
        title = l.get("title") or "(untitled)"
        lines.append(f"### {lid} — {title}")
        applies = l.get("applies_to") or []
        if applies:
            lines.append(f"**Applies to:** {', '.join(applies)}")
        sr = l.get("success_rate")
        sr_str = f"{sr}%" if sr is not None else "n/a"
        lines.append(
            f"**Past efficacy:** {l.get('hits', 0)} hits, {sr_str} success "
            f"(confidence={l.get('confidence', '?')})"
        )
        if l.get("rule_path"):
            lines.append(f"**Rule:** `.vg/bootstrap/{l['rule_path']}`")
        lines.append("")
        body = (l.get("rule_text") or "(no rule body)").strip()
        lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- CLI shim

def _main(argv: list[str]) -> int:
    """Tiny CLI so /vg:debug + shell snippets can call us without importing.

    Usage:
        python lesson_lookup.py [--violation TYPE] [--gate ID]
                                [--error TEXT] [--phase N]
                                [--limit 5] [--json]
    """
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Failure-time lesson retrieval (R9-A)")
    ap.add_argument("--violation", default=None)
    ap.add_argument("--gate", default=None)
    ap.add_argument("--error", default=None, help="error_signature")
    ap.add_argument("--phase", default=None)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    lessons = query_relevant_lessons(
        violation_type=args.violation,
        gate_id=args.gate,
        error_signature=args.error,
        phase=args.phase,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(lessons, indent=2, ensure_ascii=False))
    else:
        print(format_lessons_for_recovery(lessons))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
