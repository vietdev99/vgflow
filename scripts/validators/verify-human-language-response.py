#!/usr/bin/env python3
"""verify-human-language-response — enforce conversational, story-shaped
prose for user-facing AI output.

PROBLEM:
  User feedback (2026-04-25, repeated several times):
    "trả lời user bằng ngôn ngữ loài người, mô tả dạng có đầu đuôi câu
     chuyện ... hình như bạn mới chỉ để rule trong markdown"
  i.e. the rule lives only as prose inside SKILL.md files which the AI
  scrolls past. The AI then ships responses that are:
    - bullet-only (no narrative connective tissue)
    - schema/enum dumps ("status: pending|active|paused" with no context)
    - code-identifier-only sentences ("D-XX, R5, G-12 OK")
    - terse confirmations to questions that needed background

GATE:
  Validator scans a chunk of text (skill output, scope question file,
  review summary, accept report) and computes a HEURISTIC story-shape
  score. Below threshold → BLOCK with concrete rewrite-hint.

  This is INTENTIONALLY heuristic — full NLP would be over-engineering.
  We catch the obvious failure modes; the goal is to make AI re-read its
  own draft before sending.

CHECKS (each contributes 0–1 to the final score):
  1. has_full_sentence_ratio   — ≥30% of non-blank lines are full sentences
                                 (end with `.`/`!`/`?` and ≥6 words)
  2. has_examples              — at least one occurrence of `ví dụ`, `e.g.`,
                                 `for example`, or `như khi`
  3. has_preamble              — first 3 lines contain a sentence ≥10 words
                                 explaining context BEFORE asking/listing
  4. avoids_schema_dump        — fewer than 3 lines matching schema-like
                                 pattern `<word>: <type|enum>` consecutively
  5. avoids_terse_terminator   — last paragraph not just "OK", "Done.",
                                 "PASS", "✓", or single-word confirmation
  6. has_glossary_for_en_terms — for any line introducing an EN technical
                                 term not already explained, expects a
                                 trailing parenthetical VN gloss within
                                 the same paragraph (e.g. `BLOCK (chặn)`)
                                 — heuristic via known-term whitelist

INPUT:
  - --file PATH      read text from file
  - --stdin          read text from stdin
  - --threshold N    pass if score ≥ N (default 0.6)
  - --report-md PATH optional report

OUTPUT:
  VG-contract JSON. Exit 0 = PASS, 1 = BLOCK.

WIRING:
  Skills should pipe their user-facing prose buffer through this gate
  before emitting to AskUserQuestion / Stop hook. Recommended call sites:
    /vg:scope     each round's question text
    /vg:review    summary section of REVIEW-FEEDBACK.md
    /vg:accept    UAT report executive summary
    /vg:project   each round's question text
  On BLOCK the skill MUST regenerate the prose and re-validate — not pass
  the BLOCK back to the user.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

EN_TERMS_REQUIRING_GLOSS = {
    "BLOCK", "WARN", "FAIL", "PASS", "BLOCKED", "UNREACHABLE",
    "graphify", "CrossAI", "ORG dimension", "quota", "override-debt",
    "Foundation drift", "legacy-v1", "telemetry", "validator",
    "UNQUARANTINABLE", "essentials", "deprecation", "rate-limit",
    "Layer 4", "state machine",
}


def split_paragraphs(text: str) -> list[list[str]]:
    paras: list[list[str]] = []
    cur: list[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if cur:
                paras.append(cur)
                cur = []
        else:
            cur.append(line.rstrip())
    if cur:
        paras.append(cur)
    return paras


def is_full_sentence(line: str) -> bool:
    s = line.strip()
    if not s.endswith((".", "!", "?", "…")):
        return False
    word_count = len(re.findall(r"\b\w+\b", s))
    return word_count >= 6


SCHEMA_LINE = re.compile(
    r"^\s*[-*]?\s*[\w_]+\s*:\s*(string|number|int|float|bool|"
    r"date|enum|array|object|\w+\|\w+).*$",
    re.IGNORECASE,
)


def consecutive_schema_lines(lines: list[str]) -> int:
    """Max run-length of schema-shape lines."""
    best = run = 0
    for line in lines:
        if SCHEMA_LINE.match(line):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


TERSE_PHRASES = {"ok", "ok.", "done", "done.", "pass", "pass.",
                 "✓", "✗", "yes", "no", "yes.", "no."}


def is_terse(line: str) -> bool:
    return line.strip().lower() in TERSE_PHRASES


def score_text(text: str) -> dict:
    paras = split_paragraphs(text)
    all_lines = [ln for p in paras for ln in p]

    # 1. full-sentence ratio
    non_blank = [ln for ln in all_lines if ln.strip()]
    full_sent = sum(1 for ln in non_blank if is_full_sentence(ln))
    sentence_ratio = (full_sent / len(non_blank)) if non_blank else 0.0
    score_sent = min(1.0, sentence_ratio / 0.3)

    # 2. has_examples
    example_re = re.compile(
        r"\b(ví dụ|vd[:.]|e\.g\.|for example|như khi|cho ví dụ)\b",
        re.IGNORECASE,
    )
    has_examples = bool(example_re.search(text))
    score_examples = 1.0 if has_examples else 0.0

    # 3. has_preamble — first paragraph has ≥1 sentence with ≥10 words
    score_preamble = 0.0
    if paras:
        first_para_text = " ".join(paras[0])
        for sent in re.split(r"(?<=[.!?])\s+", first_para_text):
            if len(re.findall(r"\b\w+\b", sent)) >= 10:
                score_preamble = 1.0
                break

    # 4. avoids schema dump (≤2 consecutive schema lines)
    schema_run = consecutive_schema_lines(all_lines)
    score_no_schema = 1.0 if schema_run <= 2 else 0.0

    # 5. avoids terse terminator
    last_non_blank = next((ln for ln in reversed(all_lines) if ln.strip()), "")
    score_no_terse = 0.0 if is_terse(last_non_blank) else 1.0

    # 6. EN-term gloss — every EN term that appears at least once must have
    #    a trailing parenthetical somewhere in the same paragraph as its
    #    first occurrence. Skip if zero EN terms used.
    glossed = total = 0
    paragraph_for_term: dict[str, str] = {}
    for term in EN_TERMS_REQUIRING_GLOSS:
        for para in paras:
            joined = "\n".join(para)
            if re.search(rf"\b{re.escape(term)}\b", joined):
                paragraph_for_term[term] = joined
                break
    for term, para in paragraph_for_term.items():
        total += 1
        # Look for `term (Vietnamese-ish word)` pattern
        if re.search(
            rf"\b{re.escape(term)}\b\s*\([^)]+\)",
            para,
            re.IGNORECASE,
        ):
            glossed += 1
    score_gloss = (glossed / total) if total > 0 else 1.0

    weights = {
        "sentence_ratio": (score_sent, 0.25),
        "examples": (score_examples, 0.15),
        "preamble": (score_preamble, 0.20),
        "no_schema_dump": (score_no_schema, 0.15),
        "no_terse_terminator": (score_no_terse, 0.10),
        "en_term_gloss": (score_gloss, 0.15),
    }
    total_score = sum(v[0] * v[1] for v in weights.values())

    return {
        "score": round(total_score, 3),
        "components": {k: {"score": round(v[0], 3), "weight": v[1]}
                       for k, v in weights.items()},
        "stats": {
            "paragraphs": len(paras),
            "non_blank_lines": len(non_blank),
            "full_sentence_ratio": round(sentence_ratio, 3),
            "has_examples": has_examples,
            "max_schema_run": schema_run,
            "en_terms_used": total,
            "en_terms_glossed": glossed,
            "last_line_terse": is_terse(last_non_blank),
        },
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", default="")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--report-md", default="")
    args = ap.parse_args(argv)

    started = time.monotonic()

    if args.stdin:
        text = sys.stdin.read()
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="ignore")
    else:
        print(json.dumps({
            "validator": "human-language-response",
            "verdict": "BLOCK",
            "evidence": [{"type": "config-error",
                          "message": "Provide --file PATH or --stdin"}],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "cache_key": None,
        }))
        return 2

    if not text.strip():
        print(json.dumps({
            "validator": "human-language-response",
            "verdict": "PASS",
            "evidence": [{"type": "empty",
                          "message": "Empty input — nothing to validate."}],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "cache_key": None,
        }))
        return 0

    result = score_text(text)
    verdict = "PASS" if result["score"] >= args.threshold else "BLOCK"

    evidence: list[dict] = []
    if verdict == "BLOCK":
        for name, info in result["components"].items():
            if info["score"] < 0.5:
                evidence.append({
                    "type": "low-component",
                    "component": name,
                    "score": info["score"],
                    "fix_hint": _fix_hint_for(name),
                })

    output = {
        "validator": "human-language-response",
        "verdict": verdict,
        "score": result["score"],
        "threshold": args.threshold,
        "evidence": evidence or [{"type": "summary",
                                  "message": f"Score {result['score']} ≥ "
                                             f"threshold {args.threshold}."}],
        "duration_ms": int((time.monotonic() - started) * 1000),
        "cache_key": None,
        "stats": result["stats"],
    }
    print(json.dumps(output))

    if args.report_md:
        lines = [
            "# Human-Language Response Audit",
            "",
            f"- Score: **{result['score']}** (threshold {args.threshold}) "
            f"→ **{verdict}**",
            "",
            "## Components",
            "",
        ]
        for k, v in result["components"].items():
            lines.append(f"- `{k}`: {v['score']} (weight {v['weight']})")
        lines.append("")
        lines.append("## Fix hints")
        lines.append("")
        for ev in evidence:
            lines.append(f"- **{ev['component']}** (score {ev['score']}): "
                         f"{ev['fix_hint']}")
        Path(args.report_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_md).write_text("\n".join(lines), encoding="utf-8")

    return 0 if verdict == "PASS" else 1


def _fix_hint_for(component: str) -> str:
    return {
        "sentence_ratio": (
            "Ít nhất 30% dòng phải là câu đầy đủ (≥6 từ + dấu chấm). "
            "Hiện tại trả lời như bullet-dump. Viết lại dạng câu chuyện "
            "có đầu/giữa/cuối — đoạn mở giải thích bối cảnh, đoạn giữa "
            "trình bày chi tiết bằng câu hoàn chỉnh, đoạn cuối kết luận."
        ),
        "examples": (
            "Thêm ít nhất một ví dụ cụ thể (`ví dụ`, `vd:`, `như khi`, "
            "`for example`). Ví dụ giúp user neo concept vào trải nghiệm "
            "thực tế thay vì abstract."
        ),
        "preamble": (
            "Mở đầu bằng 1 câu ≥10 từ giải thích context TRƯỚC khi liệt "
            "kê hoặc đặt câu hỏi. Đừng nhảy thẳng vào bullet hay enum."
        ),
        "no_schema_dump": (
            "Tránh ≥3 dòng liên tiếp dạng `field: type|enum`. "
            "Nếu cần liệt kê schema, gói trong code block ```yaml ``` "
            "và viết 1 câu prose phía trên giải thích nhóm."
        ),
        "no_terse_terminator": (
            "Câu cuối không được là 'OK', 'Done', 'PASS' đơn lẻ. "
            "Kết bằng câu đầy đủ thông tin về what-next hoặc tóm tắt impact."
        ),
        "en_term_gloss": (
            "EN terms như BLOCK/CrossAI/Foundation/telemetry phải có gloss "
            "VN trong ngoặc tại lần đầu xuất hiện trong cùng paragraph. "
            "Vd: `BLOCK (chặn cứng)`, `Foundation drift (lệch hướng nền tảng)`."
        ),
    }.get(component, "")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
