#!/usr/bin/env python3
"""
extract-rule-cards.py — extract compressed rule cards from skill files.

Harness v2.6 (2026-04-25): Tầng 1 of memory-vs-enforce strategy.

Problem: skill files are 1500-3000 lines of prose. AI skims, misses 60-70%
of rules. Adding more validators is diminishing returns past ~510 enforced
rules. Solution: extract rules into per-skill compressed CARDS that AI
reads at step start (~50-100 lines per skill).

What it extracts:

  1. Top-level <rules> block — numbered rules R1..RN that apply to all
     steps in the skill.

  2. <step name="X"> blocks — per-step rules:
     - Imperative sentences (MUST/PHẢI/BẮT BUỘC/NEVER/KHÔNG BAO GIỜ)
     - Numbered sub-rules (1./2./3. lines starting with **)
     - Bash conditionals with explicit error messages (these are
       already enforced; extracted as audit trail)

  3. Anti-pattern markers — sentences with NEVER/DO NOT/anti-pattern/❌/⛔

Each rule is auto-classified:
  enforce  — has validator gate (cross-ref dispatch-manifest.json)
  remind   — has imperative marker, no validator
  advisory — soft language (should/nên/recommended)

Output: .codex/skills/vg-{name}/RULES-CARDS.md per skill.
Format: compact 2-3 lines per rule, max 5-7 rules per step section.

Usage:
  extract-rule-cards.py                    # all skills
  extract-rule-cards.py --skill vg-build   # one skill
  extract-rule-cards.py --dry-run          # print, don't write
  extract-rule-cards.py --json             # JSON output

Exit codes:
  0  success
  1  one or more skills had parse errors
  2  config error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Patterns
RULES_BLOCK_RE = re.compile(r"<rules>(.*?)</rules>", re.DOTALL)
# Strict step name pattern — alphanumeric + underscore + hyphen + dot only.
# Excludes the prose-level "<step>" tags that may appear in code-fence
# documentation (e.g., "<step>...</step>" as an example).
STEP_BLOCK_RE = re.compile(
    # Require name to start with alphanumeric (rejects "...", "_", "-" only)
    r'<step\s+name=["\']([a-zA-Z0-9][\w.-]*)["\'](?:\s+profile=["\']([^"\']*)["\'])?\s*>(.*?)</step>',
    re.DOTALL,
)

# Imperative markers (Vietnamese + English) — extracts strong rules
IMPERATIVE_RE = re.compile(
    r"\b(MUST|PHẢI|BẮT\s+BUỘC|NEVER|KHÔNG\s+BAO\s+GIỜ|REQUIRED|MANDATORY|"
    r"ALWAYS|LUÔN|LUÔN\s+LUÔN|HARD\s+RULE|HARD\s+REQUIREMENT)\b"
    r"\s*[:.]?\s*([^.!?\n]{15,250}[.!?\n])",
    re.IGNORECASE,
)

# Anti-pattern markers
ANTI_RE = re.compile(
    r"(?:NEVER|DO\s+NOT|don't|đừng|không\s+(?:dùng|được|nên|bao\s+giờ)|"
    r"cấm\b|tránh\b|stop\s+(?:doing|using)|"
    r"forbidden|banned|anti[-\s]?pattern|⛔|❌|🚫|"
    r"BAD\s*[:.]|WRONG\s*[:.]|don'?t\s+do)\s*[:.]?\s*([^.!?\n]{10,200}[.!?\n])",
    re.IGNORECASE,
)

# v2.6.1 (2026-04-25): NEW pattern types

# Bash conditional → exit 1 — these are CODE-ENFORCED rules embedded
# in skill bodies. Extract the error message as the rule.
# Pattern: `if [ ... ]; then echo "..."; exit 1; fi` (multi-line)
BASH_BLOCK_RULE_RE = re.compile(
    r"echo\s+[\"']([⛔❌🚫][^\"']{15,200})[\"'].*?exit\s+1",
    re.DOTALL,
)

# Convention/format markers — rules that define expected shape
# without imperative language but functionally enforced.
# v2.6.2: relaxed to also catch "Convention: X" inside list items / paragraphs,
# not only at line start. Also expanded labels.
CONVENTION_RE = re.compile(
    r"(?:^|\n|[*-]\s+|\*\*)\s*(?:Convention|Format|Output\s+shape|"
    r"Output\s+format|Schema|Pattern|Naming|"
    r"Required\s+env|Required\s+config|Required\s+headers?|"
    r"Quy\s+ước|Quy\s+tắc|Định\s+dạng)\s*:?\*?\*?\s*:?\s*"
    r"([^\n]{15,250})",
    re.IGNORECASE,
)

# Vietnamese soft prohibition — "không được X" / "không nên X" / "tránh X"
VN_PROHIBITION_RE = re.compile(
    r"\bkhông\s+(?:được|nên)\s+([^.!?\n]{10,200}[.!?\n])",
    re.IGNORECASE,
)

# "Always X" / "Luôn X" — soft positive imperatives
ALWAYS_RE = re.compile(
    r"\b(?:always|luôn(?:\s+luôn)?)\s+([a-zA-ZÀ-ỹ][^.!?\n]{15,200}[.!?\n])",
    re.IGNORECASE,
)

# Budget/limit constraints — quantitative rules
# v2.6.2: allow up to 2 intermediate words between number and unit
# (catches "max 2 debugger retries", "max 5 wave-level subprocess").
BUDGET_RE = re.compile(
    r"(?:max|maximum|tối\s+đa|≤|<=|at\s+most|up\s+to|cap\s+at|giới\s+hạn)\s+"
    r"(\d+(?:[.,]\d+)?(?:\s+[a-zA-Z][\w-]+){0,2}\s*"
    r"(?:lines?|seconds?|sec|s\b|ms|minutes?|min\b|hours?|hr\b|"
    r"days?|d\b|files?|tasks?|retries?|chars?|kb|mb|MB|KB|requests?|"
    r"phases?|waves?|commits?|attempts?|iterations?|steps?))",
    re.IGNORECASE,
)

# v2.6.2 (2026-04-25): 5 MORE pattern types

# Silent bash gates — exit without echo'd ⛔ message. Common patterns:
#   `[ -z "$X" ] && exit 1`
#   `|| { echo "...message..."; exit 1; }`
#   `|| exit 1`
# These are still gates but the message extraction differs from BASH-GATE.
# Capture surrounding context (the test condition) instead of error message.
SILENT_GATE_RE = re.compile(
    r"(?:^|[\n;])\s*"
    r"(?:if\s+!\s*[^\n;]{5,80}|"
    r"\[\s*[!\-z][^]]{3,80}\]|"
    r"[a-zA-Z_]\w*\s*[|&]{2}\s*\{?[^}\n;]{0,80})"
    r"\s*[&|]{2}\s*(?:exit\s+\d+|return\s+\d+|continue|break)",
    re.MULTILINE,
)

# "Skip when/if X" — applicability/precondition rules. Tell AI when the
# step or rule applies vs doesn't.
SKIP_WHEN_RE = re.compile(
    r"\b(?:Skip\s+(?:when|if|silently|cleanly)|"
    r"bỏ\s+qua\s+(?:khi|nếu)|"
    r"only\s+(?:when|if|applies\s+to)|"
    r"chỉ\s+(?:khi|áp\s+dụng))\s*[:.]?\s*([^.!?\n]{15,200}[.!?\n])",
    re.IGNORECASE,
)

# File I/O directives — what step reads/writes
FILE_IO_RE = re.compile(
    r"\b(?:Read|Write|Output|Input|Reads?|Writes?|Outputs?|Inputs?|"
    r"Đọc|Ghi|Output\s+to|Save\s+to|Load\s+from)\s*[:.]?\s*"
    r"`?([./\w][\w./*-]*\.(?:md|json|yaml|yml|sh|py|ts|tsx|js|jsx|sql|html|csv|log))`?"
    r"|"
    r"(?:Output\s+shape|Output\s+format|Output)\s*:\s*[\"`']?([./\w][\w./*-]+)[\"`']?",
    re.IGNORECASE,
)

# Cross-references to other rule sources.
# v2.6.2: matches the reference markers themselves (no preceding verb required).
# AI should know about these references regardless of phrasing.
CROSS_REF_RE = re.compile(
    r"(?:^|\W)("
    r"CLAUDE\.md|"
    r"VG\s+executor\s+rule\s*R?\d+|"
    r"FOUNDATION\.md(?:\s*[§]?\d+(?:\.\d+)*)?|"
    r"CONTEXT\.md(?:\s+D-\d+)?|"
    r"OWASP\s+(?:Top\s+10|A\d+)|"
    r"ASVS\s+V?\d+(?:\.\d+)*|"
    r"Phase\s+\d+(?:\.\d+)*\s+(?:incident|fix|retro|hotfix)|"
    r"\.codex/skills/[\w-]+/SKILL\.md|"
    r"\.claude/commands/vg/[\w-]+\.md|"
    r"verify-[a-z][\w-]+|"
    r"\bRFC\s*\d{3,5}|"
    r"GDPR(?:\s+(?:Art\.?|Article)\s+\d+)?"
    r")",
    re.IGNORECASE,
)

# Timeout / wait constraints — explicit time bounds for operations
TIMEOUT_RE = re.compile(
    r"\b(?:timeout|wait|sleep|delay|retry\s+after|TTL|expires?\s+(?:in|after))\s*"
    r"[:=]?\s*(\d+(?:[.,]\d+)?\s*"
    r"(?:ms|s\b|sec(?:ond)?s?|min(?:ute)?s?|hours?|hr|days?|d\b))",
    re.IGNORECASE,
)

# Numbered top-level rules (R1, R2 / 1., 2.)
NUMBERED_RULE_RE = re.compile(
    r"^(\d+)\.\s+\*\*([^*]+?)\*\*\s*[—\-:]\s*(.+?)(?=^\d+\.\s|\Z)",
    re.MULTILINE | re.DOTALL,
)

# v2.6 Phase D — phase_pattern attribute extraction.
# Source SKILL.md may declare a per-rule phase_pattern in three forms:
#   1. Inline marker in body: `phase_pattern: "^7\."` or `phase_pattern: ^7\.`
#   2. XML-style attr on <rule>: `<rule phase_pattern="^7\.">` (future-proof)
#   3. Frontmatter line in rule body: starts with `phase_pattern:`
# Default ".*" if absent (grandfather all 783+ existing rules).
PHASE_PATTERN_RE = re.compile(
    r'phase_pattern\s*[:=]\s*"([^"]+)"|phase_pattern\s*[:=]\s*([^\s,]+)',
    re.IGNORECASE,
)


def _extract_phase_pattern(text: str) -> str:
    """Extract phase_pattern from rule body. Returns ".*" when absent."""
    m = PHASE_PATTERN_RE.search(text)
    if not m:
        return ".*"
    return (m.group(1) or m.group(2) or ".*").strip()


def _strip_phase_pattern_marker(text: str) -> str:
    """Remove phase_pattern marker from body text so it isn't rendered twice
    (once in body, once as explicit continuation line). Idempotent."""
    return PHASE_PATTERN_RE.sub("", text).rstrip(" ,;.").strip()


def _load_validator_manifest() -> dict:
    """Load dispatch-manifest.json to know which rules have validator gates."""
    manifest_path = REPO_ROOT / ".claude" / "scripts" / "validators" / "dispatch-manifest.json"
    if not manifest_path.exists():
        return {"validators": {}}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _validator_name_tokens(v_name: str) -> set[str]:
    """Tokenize validator name into searchable keywords.
    Example: 'verify-contract-runtime' → {'contract', 'runtime'} (drops 'verify')."""
    tokens = set(re.split(r"[-_]+", v_name.lower()))
    # Drop generic action/qualifier words that produce false matches.
    # Keep distinctive domain terms (contract, idempotency, jwt, csrf, etc.).
    # v2.6.3 (2026-04-26): expanded to drop more "filler" qualifiers that
    # cause weak matches to outscore semantic ones (e.g. "build" + "required"
    # in build-crossai-required outscoring "blueprint" in
    # verify-blueprint-completeness for a Blueprint-themed rule).
    GENERIC = {
        # Action verbs (what the validator does, not what it's about)
        "verify", "scan", "check", "validate", "audit",
        # Qualifier suffixes (how complete/strict)
        "enforcement", "coverage", "evidence", "policy",
        "complete", "completeness", "required", "mandatory",
        "fresh", "freshness", "drift", "presence", "missing",
        # Mode/context (most validators have these in some form)
        "runtime", "static", "live",
        # Generic infra terms
        "gate", "test", "report", "status",
        "build", "ship", "deploy",  # too common — most validators relate to these
        # Stop words
        "the", "and", "for", "with",
    }
    tokens -= GENERIC
    return {t for t in tokens if len(t) >= 4}


def _build_validator_index(validator_descriptions: dict) -> tuple[list[tuple[str, set[str], set[str]]], dict[str, int]]:
    """Pre-compute (name, name_tokens, desc_tokens) tuples + token frequency map.

    Returns:
      index: list of (validator_name, name_tokens, desc_tokens)
      token_freq: maps each token → count of validators it appears in
                  (used for TF-IDF-like rare-token weighting — rare tokens
                  are more distinctive, score higher when matched).
    """
    index: list[tuple[str, set[str], set[str]]] = []
    token_freq: dict[str, int] = {}

    for v_name, v_spec in validator_descriptions.items():
        name_tokens = _validator_name_tokens(v_name)
        # Description tokens — extract noun-like words ≥4 chars
        desc = v_spec.get("description", "").lower()
        desc_tokens = set(re.findall(r"[a-z][a-z0-9-]{3,}", desc))
        # Drop generic words from description tokens too
        GENERIC_DESC = {
            "must", "phải", "rule", "rules", "check", "validate", "verify",
            "auto", "manual", "manually", "default", "live", "static",
            "with", "from", "into", "when", "where", "this", "that",
            "phase", "skill", "step", "command", "validator", "block",
            "warn", "error", "fail", "pass", "hits", "found", "missing",
            "before", "after", "during", "while", "until",
            "code", "file", "files", "line", "lines", "list",
        }
        desc_tokens -= GENERIC_DESC
        index.append((v_name, name_tokens, desc_tokens))

        # Build frequency: each token → number of validators using it
        for tok in name_tokens | desc_tokens:
            token_freq[tok] = token_freq.get(tok, 0) + 1

    return index, token_freq


def _classify_rule(
    text: str,
    validator_index: list[tuple[str, set[str], set[str]]],
    token_freq: dict[str, int] | None = None,
) -> tuple[str, str | None]:
    """Classify rule as enforce|remind|advisory. Return (class, validator_name).

    v2.6.3 (2026-04-26) — improved priority chain:

    1. DIRECT NAME MATCH (highest): if rule text mentions validator name
       literally (e.g. "verify-contract-runtime"), tag that validator.
       No false positives because validator names are unique.

    2. NAME-TOKEN MATCH with TF-IDF weighting: rare tokens (appear in
       only 1-2 validators) score higher than common tokens (appear
       in many). Picks distinctive validator over generic match.

    3. DESCRIPTION-TOKEN MATCH: if name tokens didn't match, try
       validator description tokens — rule may use different vocabulary
       than validator name.

    4. LANGUAGE-STRENGTH FALLBACK: classify [remind] vs [advisory]
       based on imperative vs soft language.
    """
    text_lower = text.lower()

    # Strategy 1 — direct validator name occurrence
    # Sort by name length desc so longer names match first
    # (avoid partial-match where "verify-X" contains "X" of another validator)
    for v_name, _name_tokens, _desc_tokens in sorted(
        validator_index, key=lambda v: -len(v[0])
    ):
        if v_name in text_lower:
            return "enforce", v_name
        # Also try sans-verify-prefix form (e.g., "contract-runtime" sub-string
        # of "verify-contract-runtime") — only if remaining is ≥10 chars (avoid
        # generic substrings like "perf" inside "performance")
        bare = v_name.replace("verify-", "")
        if len(bare) >= 10 and bare in text_lower:
            return "enforce", v_name

    # Strategy 2/3 — token-overlap with rare-token weighting (TF-IDF-like)
    text_words = set(re.findall(r"[a-z][a-z0-9-]+", text_lower))
    token_freq = token_freq or {}
    # Total validators (denominator for IDF-like score)
    total_validators = len(validator_index)

    def _token_weight(tok: str) -> float:
        """Higher weight for rare tokens. token appearing in 1 validator → 3.0,
        in 5 validators → 0.6, in all → 0.1. Length bonus for long tokens."""
        freq = token_freq.get(tok, 1)
        idf = max(0.1, 3.0 / freq)
        length_bonus = 0.5 if len(tok) >= 8 else 0.0
        return idf + length_bonus

    best_match: tuple[str, float] | None = None  # (name, score)

    for v_name, name_tokens, desc_tokens in validator_index:
        # Score 2: weighted name-token overlap
        name_overlap = name_tokens & text_words
        name_score = sum(_token_weight(t) for t in name_overlap)

        # Score 3: description-token overlap (lower weight since less precise)
        desc_overlap = desc_tokens & text_words
        desc_score = sum(_token_weight(t) for t in desc_overlap) * 0.4

        total_score = name_score + desc_score

        # v2.6.3 (2026-04-26) — tighter threshold to prevent single-token
        # spurious matches (e.g. "step" alone shouldn't tag verify-step-markers
        # if rule text doesn't actually discuss step markers).
        # Threshold met when:
        #   (a) ≥2 name tokens overlap (strong evidence — multiple matches)
        #   OR (b) 1 name token overlap AND that token is ≥9 chars
        #         (highly distinctive like "idempotency", "blueprint")
        #   OR (c) ≥1 name token + ≥3 desc tokens overlap (broad context match)
        long_name_overlap = any(len(t) >= 9 for t in name_overlap)
        threshold_met = (
            len(name_overlap) >= 2
            or (len(name_overlap) >= 1 and long_name_overlap)
            or (len(name_overlap) >= 1 and len(desc_overlap) >= 3)
        )
        if threshold_met:
            if best_match is None or total_score > best_match[1]:
                best_match = (v_name, total_score)

    if best_match:
        return "enforce", best_match[0]

    # Strategy 4 — language-strength fallback
    if any(m in text_lower for m in ("must ", "phải ", "bắt buộc", "never ",
                                     "không bao giờ", "required", "mandatory",
                                     "always ", "luôn ")):
        return "remind", None
    if any(m in text_lower for m in ("should ", "nên ", "recommend", "advisory",
                                     "consider", "prefer", "may ", "có thể ")):
        return "advisory", None
    return "remind", None  # default


def _shorten(text: str, max_chars: int = 140) -> str:
    """Compress to one line, max chars. Strip leading punctuation that
    captures from sentence-fragment matches (e.g. 'MUST, as FINAL action')."""
    text = re.sub(r"\s+", " ", text).strip()
    # Trim leading punctuation common in sentence fragments
    text = text.lstrip(",;:- ").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."


def _extract_top_rules(text: str) -> list[dict]:
    rules: list[dict] = []
    rules_block = RULES_BLOCK_RE.search(text)
    if not rules_block:
        return rules
    block_text = rules_block.group(1)
    for m in NUMBERED_RULE_RE.finditer(block_text):
        # Capture full rule text BEFORE shortening so phase_pattern survives
        full_body = m.group(3)
        phase_pattern = _extract_phase_pattern(m.group(2) + " " + full_body)
        # Strip the phase_pattern marker from rendered body so it isn't shown twice
        clean_body = _strip_phase_pattern_marker(full_body) if phase_pattern != ".*" else full_body
        rules.append({
            "num": m.group(1),
            "title": _shorten(m.group(2), 80),
            "body": _shorten(clean_body, 200),
            "phase_pattern": phase_pattern,
        })
    return rules


def _extract_step_rules(step_body: str) -> list[dict]:
    """Extract per-step rules from multiple pattern types.

    Pattern priority (highest signal first):
      1. Bash conditional → exit 1 (code-enforced, always [enforce])
      2. Imperative markers (MUST/PHẢI/ALWAYS/...) — strong [remind/enforce]
      3. Convention/format declarations — [advisory/remind]
      4. Vietnamese soft prohibition (không được/không nên) — [remind]
      5. Always/Luôn positive — [remind]
      6. Budget constraints (≤ N lines, max N sec) — [enforce-likely]
    """
    rules: list[dict] = []
    seen = set()  # dedupe by first 80 chars normalized

    def _add_rule(kind: str, marker: str, text: str, severity_hint: str = "") -> bool:
        """Try to add rule; return True if added (not duplicate)."""
        normalized = re.sub(r"\s+", " ", text.lower())[:80]
        if normalized in seen:
            return False
        seen.add(normalized)
        # v2.6 Phase D — extract phase_pattern from rule text if declared inline
        phase_pattern = _extract_phase_pattern(text)
        # Strip the marker from rendered text so it isn't shown twice
        clean_text = _strip_phase_pattern_marker(text) if phase_pattern != ".*" else text
        entry = {
            "kind": kind,
            "marker": marker,
            "text": clean_text,
            "phase_pattern": phase_pattern,
        }
        if severity_hint:
            entry["severity_hint"] = severity_hint
        rules.append(entry)
        return True

    # 1. Bash conditional rules (highest signal — these are LIVE gates)
    for m in BASH_BLOCK_RULE_RE.finditer(step_body):
        body = _shorten(m.group(1), 180)
        if _add_rule("bash_gate", "BASH-GATE", body, "enforce"):
            if len(rules) >= 8:
                return rules

    # 2. Imperative markers (MUST/PHẢI/ALWAYS/...)
    for m in IMPERATIVE_RE.finditer(step_body):
        marker = m.group(1).upper().strip()
        body = _shorten(m.group(2), 180)
        if _add_rule("imperative", marker, body):
            if len(rules) >= 8:
                return rules

    # 3. Convention/format declarations
    for m in CONVENTION_RE.finditer(step_body):
        body = _shorten(m.group(1), 180)
        # Pull the convention type from line start
        line_start = step_body.rfind("\n", 0, m.start()) + 1
        line = step_body[line_start:m.end()]
        marker_match = re.match(r"\s*(\w+)", line)
        marker = marker_match.group(1).upper() if marker_match else "CONVENTION"
        if _add_rule("convention", marker, body, "advisory"):
            if len(rules) >= 8:
                break

    # 4. Vietnamese soft prohibition
    for m in VN_PROHIBITION_RE.finditer(step_body):
        body = _shorten(f"không được/nên: {m.group(1)}", 180)
        if _add_rule("vn_prohibition", "KHÔNG", body):
            if len(rules) >= 9:
                break

    # 5. Always/Luôn positive
    for m in ALWAYS_RE.finditer(step_body):
        body = _shorten(f"always/luôn: {m.group(1)}", 180)
        if _add_rule("always", "ALWAYS", body):
            if len(rules) >= 10:
                break

    # 6. Budget constraints — useful even as standalone (capture context)
    budget_hits: list[str] = []
    for m in BUDGET_RE.finditer(step_body):
        # Capture surrounding 60 chars for context
        ctx_start = max(0, m.start() - 30)
        ctx_end = min(len(step_body), m.end() + 30)
        ctx = step_body[ctx_start:ctx_end].replace("\n", " ").strip()
        budget_hits.append(_shorten(ctx, 150))

    if budget_hits:
        # Combine all budget mentions into one rule (compact)
        combined = " | ".join(budget_hits[:3])
        _add_rule("budget", "BUDGET", _shorten(combined, 200), "enforce")

    # 7. Silent bash gates (exit/return without echo'd ⛔ message)
    silent_gate_hits: list[str] = []
    for m in SILENT_GATE_RE.finditer(step_body):
        body = _shorten(m.group(0).strip(), 120)
        if not body or len(body) < 10:
            continue
        # Skip if this gate already matched BASH_BLOCK_RULE_RE (echo ⛔)
        # — heuristic: if context contains ⛔ within ±200 chars, skip.
        ctx_start = max(0, m.start() - 200)
        ctx_end = min(len(step_body), m.end() + 200)
        if "" in step_body[ctx_start:ctx_end]:
            continue
        silent_gate_hits.append(body)

    if silent_gate_hits:
        # Group as single rule
        combined = " | ".join(silent_gate_hits[:3])
        _add_rule("silent_gate", "SILENT-GATE", _shorten(combined, 200), "enforce")

    # 8. Skip preconditions
    for m in SKIP_WHEN_RE.finditer(step_body):
        body = _shorten(f"skip when: {m.group(1)}", 180)
        if _add_rule("skip_when", "SKIP-WHEN", body, "advisory"):
            if len(rules) >= 12:
                break

    # 9. File I/O directives — what files step reads/writes
    file_io_hits: set[str] = set()
    for m in FILE_IO_RE.finditer(step_body):
        path = m.group(1) or m.group(2) or ""
        path = path.strip()
        if path and len(path) <= 100 and "/" in path or "." in path:
            file_io_hits.add(path)

    if file_io_hits:
        combined = ", ".join(sorted(file_io_hits)[:5])
        _add_rule("file_io", "FILES", _shorten(f"read/write: {combined}", 200), "advisory")

    # 10. Cross-references to other rule sources
    cross_refs: set[str] = set()
    for m in CROSS_REF_RE.finditer(step_body):
        ref = m.group(1).strip()
        if ref:
            cross_refs.add(ref[:60])

    if cross_refs:
        combined = ", ".join(sorted(cross_refs)[:5])
        _add_rule("cross_ref", "REF", _shorten(f"see also: {combined}", 200), "advisory")

    # 11. Timeout / wait constraints
    timeout_hits: set[str] = set()
    for m in TIMEOUT_RE.finditer(step_body):
        # Capture short context (preceding word for label)
        ctx_start = max(0, m.start() - 20)
        ctx = step_body[ctx_start:m.end()].replace("\n", " ").strip()
        timeout_hits.add(_shorten(ctx, 80))

    if timeout_hits:
        combined = " | ".join(sorted(timeout_hits)[:3])
        _add_rule("timeout", "TIMEOUT", _shorten(combined, 200), "enforce")

    return rules


def _extract_anti_patterns(step_body: str) -> list[str]:
    """Extract anti-patterns. v2.6.1 also handles Vietnamese cấm/tránh markers."""
    antis: list[str] = []
    seen = set()
    for m in ANTI_RE.finditer(step_body):
        body = _shorten(m.group(1), 150)
        key = re.sub(r"\s+", " ", body.lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        antis.append(body)
        if len(antis) >= 5:
            break
    return antis


def extract_skill(skill_path: Path, validator_descriptions: dict) -> dict:
    text = skill_path.read_text(encoding="utf-8", errors="replace")

    validator_index, token_freq = _build_validator_index(validator_descriptions)

    top_rules = _extract_top_rules(text)
    # Classify top rules
    for r in top_rules:
        cls, validator = _classify_rule(
            f"{r['title']} {r['body']}", validator_index, token_freq)
        r["class"] = cls
        if validator:
            r["validator"] = validator

    # Per-step rules
    steps: list[dict] = []
    for m in STEP_BLOCK_RE.finditer(text):
        step_name = m.group(1)
        step_profile = m.group(2) or "*"
        step_body = m.group(3)
        rules = _extract_step_rules(step_body)
        antis = _extract_anti_patterns(step_body)

        # Classify each step rule
        for r in rules:
            # Honor severity_hint when present (bash_gate/budget already
            # know they're enforce-class). Otherwise classify by text.
            cls, validator = _classify_rule(r["text"], validator_index, token_freq)
            if r.get("severity_hint") == "enforce":
                # Code-enforced (bash gate / budget) — keep as enforce even
                # if no validator name match
                r["class"] = "enforce"
                if validator:
                    r["validator"] = validator
            elif r.get("severity_hint") == "advisory":
                r["class"] = "advisory"
                if validator:
                    r["validator"] = validator
            else:
                r["class"] = cls
                if validator:
                    r["validator"] = validator

        if rules or antis:
            steps.append({
                "name": step_name,
                "profile": step_profile,
                "rules": rules,
                "anti_patterns": antis,
                "body_chars": len(step_body),
            })

    return {
        "skill": skill_path.parent.name if skill_path.parent.name.startswith("vg-") else skill_path.stem,
        "skill_path": str(skill_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "top_rules": top_rules,
        "steps": steps,
        "total_rules": len(top_rules) + sum(len(s["rules"]) for s in steps),
        "total_antis": sum(len(s["anti_patterns"]) for s in steps),
    }


def render_markdown(card_data: dict) -> str:
    """Render rule card as compact Markdown."""
    skill = card_data["skill"]
    lines = [
        f"# RULES-CARDS — {skill}",
        "",
        f"> Auto-generated from `{card_data['skill_path']}`. Compressed rule digest",
        f"> for AI consumption at step start. {card_data['total_rules']} rules,",
        f"> {card_data['total_antis']} anti-patterns extracted from {len(card_data['steps'])} steps.",
        "",
        "**Tags:**",
        "- `[enforce]` — has validator gate (auto-blocked at runtime)",
        "- `[remind]` — imperative rule, no auto-gate (rely on AI recall)",
        "- `[advisory]` — soft guidance",
        "",
        "---",
        "",
    ]

    if card_data["top_rules"]:
        lines.append("## Top-level rules (apply to ALL steps)")
        lines.append("")
        for r in card_data["top_rules"]:
            tag = f"[{r['class']}]"
            validator_ref = f" → `{r['validator']}`" if r.get("validator") else ""
            lines.append(f"- **R{r['num']} — {r['title']}** {tag}{validator_ref}")
            lines.append(f"  {r['body']}")
            # v2.6 Phase D — emit phase_pattern explicitly (default ".*")
            # so inject-rule-cards.sh + verify-rule-phase-scope.py can read it.
            phase_pattern = r.get("phase_pattern", ".*")
            lines.append(f'  phase_pattern: "{phase_pattern}"')
            lines.append("")

    if card_data["steps"]:
        lines.append("## Per-step rules")
        lines.append("")
        for s in card_data["steps"]:
            profile_note = f" *(profile: {s['profile']})*" if s["profile"] != "*" else ""
            lines.append(f"### Step: `{s['name']}`{profile_note}")
            lines.append("")
            if s["rules"]:
                for r in s["rules"]:
                    tag = f"[{r['class']}]"
                    validator_ref = f" → `{r['validator']}`" if r.get("validator") else ""
                    lines.append(f"- {tag} **{r['marker']}**: {r['text']}{validator_ref}")
                    # v2.6 Phase D — emit phase_pattern as continuation line
                    phase_pattern = r.get("phase_pattern", ".*")
                    lines.append(f'  phase_pattern: "{phase_pattern}"')
            if s["anti_patterns"]:
                lines.append("")
                lines.append("**Anti-patterns:**")
                for a in s["anti_patterns"]:
                    lines.append(f"- ❌ {a}")
            lines.append("")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"_Generated by `extract-rule-cards.py`. Re-run after skill body changes._")
    return "\n".join(lines)


def find_skill_files() -> list[Path]:
    """Find all skill files: .codex/skills/vg-*/SKILL.md + .claude/commands/vg/*.md."""
    files: list[Path] = []
    codex_skills = REPO_ROOT / ".codex" / "skills"
    if codex_skills.exists():
        for skill_dir in codex_skills.iterdir():
            if not skill_dir.is_dir() or not skill_dir.name.startswith("vg-"):
                continue
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                files.append(skill_md)
    return sorted(files)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skill", default=None,
                    help="Filter to one skill name (e.g. vg-build)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print to stdout instead of writing")
    ap.add_argument("--json", action="store_true",
                    help="Emit JSON instead of Markdown (machine consumption)")
    ap.add_argument("--phase", help="(orchestrator-injected; ignored)")
    args = ap.parse_args()

    manifest = _load_validator_manifest()
    validator_descriptions = manifest.get("validators", {})

    skill_files = find_skill_files()
    if args.skill:
        skill_files = [f for f in skill_files if args.skill in str(f)]

    if not skill_files:
        print("\033[38;5;208mno skill files found\033[0m", file=sys.stderr)
        return 2

    summary = {"skills": [], "total_rules": 0, "total_antis": 0}
    errors = 0

    for skill_path in skill_files:
        try:
            data = extract_skill(skill_path, validator_descriptions)
        except Exception as exc:
            print(f"\033[38;5;208m{skill_path.name}: parse error: {exc}\033[0m", file=sys.stderr)
            errors += 1
            continue

        summary["skills"].append({
            "skill": data["skill"],
            "rules": data["total_rules"],
            "antis": data["total_antis"],
            "steps": len(data["steps"]),
        })
        summary["total_rules"] += data["total_rules"]
        summary["total_antis"] += data["total_antis"]

        if args.json:
            output = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            output = render_markdown(data)

        if args.dry_run:
            print(output)
            print()
        else:
            out_path = skill_path.parent / "RULES-CARDS.md"
            if args.json:
                out_path = skill_path.parent / "RULES-CARDS.json"
            out_path.write_text(output, encoding="utf-8")
            print(f"  ✓ {data['skill']}: {data['total_rules']} rules, "
                  f"{data['total_antis']} anti-patterns → {out_path.relative_to(REPO_ROOT)}")

    print()
    print(f"Total: {len(skill_files) - errors}/{len(skill_files)} skills, "
          f"{summary['total_rules']} rules, {summary['total_antis']} anti-patterns extracted.")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
