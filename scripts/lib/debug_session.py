"""debug_session — B116 v4.73.0 — cleaner handling for /vg:debug.

Helpers for:

  rank_resume_candidates(sessions_dir, current_symptom)
      Score active debug sessions by:
        recency (newer = higher score)
        × open_iter_count (more progress = stickier)
        × symptom_similarity (overlap with current prompt)
      Return ordered list — picker can show top 5 sorted.

  symptom_hash(description)
      Stable hash of normalized symptom — used to detect "same bug
      different session" so we can auto-suggest resume vs new.

  detect_duplicate_session(symptom_hash, sessions_dir, similarity_threshold)
      Return existing session ID if symptom hash matches OR ≥80% token
      overlap. Empty if none.

  should_silent_continue(confidence, verify_passed, iteration_count)
      Return True iff /vg:debug Step 3 can skip AskUserQuestion this
      iteration. Triggered when:
        - confidence >= 90 AND
        - verify_passed is True AND
        - iteration_count <= 2 (don't run away on long sessions)

  batch_checkpoints(pending_checkpoints, window_sec=60)
      Merge multiple checkpoint dicts whose timestamps fall within a 60s
      window into a single combined checkpoint (de-noise).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

_STOP_WORDS = frozenset({
    "the", "a", "an", "of", "to", "in", "on", "at", "is", "are",
    "was", "were", "be", "been", "this", "that", "these", "those",
    "with", "from", "for", "and", "or", "but", "not", "no",
    "khong", "không", "có", "là", "thì", "mà",
})

_SILENT_CONFIDENCE_THRESHOLD = 90
_SILENT_MAX_ITER = 2
_CHECKPOINT_BATCH_WINDOW_SEC = 60
_DUPLICATE_SIMILARITY_THRESHOLD = 0.80


def _normalize(text: str) -> list[str]:
    tokens = re.findall(r"\b[a-zA-Z0-9_-]{2,}\b", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS]


def symptom_hash(description: str) -> str:
    """Stable hash of normalized symptom tokens."""
    tokens = sorted(set(_normalize(description)))
    if not tokens:
        return "empty"
    digest = hashlib.sha256("|".join(tokens).encode("utf-8")).hexdigest()
    return digest[:16]


def _jaccard(a: list[str], b: list[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _read_session_meta(debug_log_path: Path) -> dict:
    """Parse minimal metadata from DEBUG-LOG.md."""
    try:
        text = debug_log_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    meta = {}
    for label, key in (
        ("Description", "description"),
        ("Classification", "classification"),
        ("Status", "status"),
        ("Started", "started"),
    ):
        m = re.search(rf"^\*\*{label}:\*\* *(.+)$", text, re.MULTILINE)
        if m:
            meta[key] = m.group(1).strip()
    meta["iter_count"] = len(re.findall(r"^### Iteration ", text, re.MULTILINE))
    return meta


def rank_resume_candidates(
    sessions_dir: Path,
    current_symptom: str,
    *,
    max_age_days: int = 7,
    top_n: int = 5,
) -> list[dict]:
    """Return ranked list of resumable sessions.

    Each entry: {debug_id, description, iter_count, status, score, hash}
    """
    if not sessions_dir.is_dir():
        return []

    current_tokens = _normalize(current_symptom)
    current_hash = symptom_hash(current_symptom)
    cutoff = time.time() - (max_age_days * 86400)

    candidates: list[dict] = []
    for sess_dir in sessions_dir.iterdir():
        if not sess_dir.is_dir():
            continue
        log_path = sess_dir / "DEBUG-LOG.md"
        if not log_path.is_file():
            continue
        mtime = log_path.stat().st_mtime
        if mtime < cutoff:
            continue
        meta = _read_session_meta(log_path)
        status = (meta.get("status") or "").upper()
        if "RESOLVED" in status or "ABANDONED" in status or "SPEC_GAP" in status:
            continue
        desc_tokens = _normalize(meta.get("description", ""))
        sim = _jaccard(current_tokens, desc_tokens) if current_tokens else 0.0
        sess_hash = symptom_hash(meta.get("description", ""))
        is_dup = sess_hash == current_hash and current_hash != "empty"

        recency_score = min(1.0, (mtime - cutoff) / (max_age_days * 86400))
        iter_score = min(1.0, meta.get("iter_count", 0) / 5.0)
        # Weighted blend
        score = (
            recency_score * 0.4
            + iter_score * 0.3
            + sim * 0.3
        )
        if is_dup:
            score += 0.5  # duplicate detection boost

        candidates.append({
            "debug_id": sess_dir.name,
            "description": meta.get("description", "")[:80],
            "iter_count": meta.get("iter_count", 0),
            "status": meta.get("status", "OPEN"),
            "score": round(score, 3),
            "hash": sess_hash,
            "is_duplicate_of_current": is_dup,
            "symptom_similarity": round(sim, 3),
            "age_days": round((time.time() - mtime) / 86400, 2),
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:top_n]


def detect_duplicate_session(
    description: str,
    sessions_dir: Path,
    *,
    similarity_threshold: float = _DUPLICATE_SIMILARITY_THRESHOLD,
    max_age_days: int = 7,
) -> Optional[str]:
    """Return debug_id of duplicate session if found, else None."""
    if not sessions_dir.is_dir():
        return None
    ranked = rank_resume_candidates(
        sessions_dir, description,
        max_age_days=max_age_days,
        top_n=10,
    )
    for c in ranked:
        if c["is_duplicate_of_current"]:
            return c["debug_id"]
        if c["symptom_similarity"] >= similarity_threshold:
            return c["debug_id"]
    return None


def should_silent_continue(
    confidence: int,
    verify_passed: bool,
    iteration_count: int,
    *,
    threshold: int = _SILENT_CONFIDENCE_THRESHOLD,
    max_iter: int = _SILENT_MAX_ITER,
) -> bool:
    """Decide if Step 3 AskUserQuestion can be skipped for this iteration."""
    return (
        confidence >= threshold
        and verify_passed
        and iteration_count <= max_iter
    )


def batch_checkpoints(
    pending: list[dict],
    *,
    window_sec: int = _CHECKPOINT_BATCH_WINDOW_SEC,
) -> list[dict]:
    """Merge checkpoints with same reason landing within window_sec.

    Each input: {timestamp, reason, instructions, iter}
    Returns: list of batched checkpoints (each may have iters: [N, N+1, ...]).
    """
    if not pending:
        return []

    sorted_cps = sorted(pending, key=lambda c: c.get("timestamp", 0))
    batches: list[dict] = []
    current_batch: dict = {}

    for cp in sorted_cps:
        ts = cp.get("timestamp", 0)
        reason = cp.get("reason", "")
        if (
            current_batch
            and current_batch["reason"] == reason
            and (ts - current_batch["last_ts"]) <= window_sec
        ):
            current_batch["iters"].append(cp.get("iter"))
            current_batch["last_ts"] = ts
            # Append instructions if distinct
            new_instr = cp.get("instructions", "")
            if new_instr and new_instr not in current_batch["instructions_list"]:
                current_batch["instructions_list"].append(new_instr)
        else:
            if current_batch:
                batches.append(current_batch)
            current_batch = {
                "first_ts": ts,
                "last_ts": ts,
                "reason": reason,
                "iters": [cp.get("iter")],
                "instructions_list": [cp.get("instructions", "")] if cp.get("instructions") else [],
            }

    if current_batch:
        batches.append(current_batch)

    # Flatten instructions_list
    for b in batches:
        b["combined_instructions"] = "\n---\n".join(b["instructions_list"])
        del b["instructions_list"]
    return batches


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_rank = sub.add_parser("rank", help="rank resume candidates")
    p_rank.add_argument("--sessions-dir", default=".vg/debug")
    p_rank.add_argument("--symptom", default="")
    p_rank.add_argument("--top-n", type=int, default=5)

    p_hash = sub.add_parser("hash", help="compute symptom hash")
    p_hash.add_argument("description")

    p_dup = sub.add_parser("dup", help="detect duplicate session")
    p_dup.add_argument("--sessions-dir", default=".vg/debug")
    p_dup.add_argument("--description", required=True)

    p_silent = sub.add_parser("silent", help="check should_silent_continue")
    p_silent.add_argument("--confidence", type=int, required=True)
    p_silent.add_argument("--verify-passed", action="store_true")
    p_silent.add_argument("--iter", type=int, required=True)

    args = ap.parse_args(argv)

    if args.cmd == "rank":
        result = rank_resume_candidates(
            Path(args.sessions_dir), args.symptom, top_n=args.top_n,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "hash":
        print(symptom_hash(args.description))
        return 0

    if args.cmd == "dup":
        dup_id = detect_duplicate_session(
            args.description, Path(args.sessions_dir),
        )
        if dup_id:
            print(dup_id)
            return 0
        return 1

    if args.cmd == "silent":
        ok = should_silent_continue(
            args.confidence, args.verify_passed, args.iter,
        )
        print("true" if ok else "false")
        return 0 if ok else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
