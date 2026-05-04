#!/usr/bin/env python3
"""
VG Bootstrap — Learn Tier Classifier (v2.5 Phase H + v2.6 Phase A adaptive)

Compute tier per candidate based on confidence + impact + reject history.

Tiers:
  A — high confidence + critical impact → auto-promote candidate after N confirms
  B — medium confidence or important impact → surface max 2 per phase at /vg:accept
  C — low confidence or nice impact → silent, only via --review --all
  RETIRED — rejected >= retire_after_rejects times → never surface again

v2.6 Phase A: when `--shadow-jsonl PATH` is supplied (output of
`bootstrap-shadow-evaluator.py`), the classifier OVERRIDES the
fixed-threshold path with the evaluator's adaptive `tier_proposed`.
Backward-compat: candidates without shadow telemetry fall back to the
v2.5 confidence+impact heuristic (grandfather behaviour).

Usage:
    python learn-tier-classify.py --all
    python learn-tier-classify.py --candidate L-042
    python learn-tier-classify.py --all --include-retired
    python learn-tier-classify.py --all --shadow-jsonl .vg/shadow.jsonl

Output:
  --all:          JSONL to stdout, one line per non-retired candidate
  --candidate:    single JSON object to stdout
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


# ─── Repo root resolution ────────────────────────────────────────────────────

def _repo_root() -> Path:
    env = os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env)
    # Walk up from script location looking for .claude/vg.config.md
    p = Path(__file__).resolve()
    for parent in [p.parent, p.parent.parent, p.parent.parent.parent]:
        if (parent / ".claude" / "vg.config.md").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _repo_root()
BOOTSTRAP_DIR = REPO_ROOT / ".vg" / "bootstrap"
CONFIG_PATH = REPO_ROOT / ".claude" / "vg.config.md"


# ─── Config loading ──────────────────────────────────────────────────────────

def _load_config() -> dict:
    """Load bootstrap config from vg.config.md YAML block.
    Falls back to defaults if file not found or section missing.
    """
    defaults = {
        "retire_after_rejects": 2,
        "tier_a_threshold_confidence": 0.85,
        "tier_b_threshold_confidence": 0.6,
        # v2.6 Phase A: kept for backward-compat fallback when no shadow telemetry
        "tier_a_auto_promote_after_confirms": 3,
        "tier_b_max_per_phase": 2,
        "auto_surface_at_accept": True,
        "stale_after_phases_without_action": 10,
        "dedupe_title_similarity": 0.8,
        # v2.6 Phase A — adaptive shadow evaluation
        "shadow_mode_default": True,
        "shadow_min_phases": 5,
        "shadow_correctness_critical": 0.95,
        "shadow_correctness_important": 0.80,
        "shadow_stale_phases": 10,
    }

    if not CONFIG_PATH.exists():
        return defaults

    text = CONFIG_PATH.read_text(encoding="utf-8", errors="replace")

    # Extract the bootstrap: section from the config (YAML-like, not full YAML)
    # Find `bootstrap:` header and collect indented lines below it
    in_bootstrap = False
    result = dict(defaults)

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("bootstrap:"):
            in_bootstrap = True
            continue
        if in_bootstrap:
            # Stop on new top-level key (not indented) or --- divider
            if stripped.startswith("---") or (line and not line[0].isspace() and ":" in line and not stripped.startswith("#")):
                break
            if stripped.startswith("#") or not stripped:
                continue
            # Parse key: value lines
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                k = k.strip()
                v = v.strip().split("#")[0].strip()  # strip inline comments
                if not k or not v:
                    continue
                # Coerce types
                if v.lower() == "true":
                    result[k] = True
                elif v.lower() == "false":
                    result[k] = False
                else:
                    try:
                        result[k] = int(v)
                    except ValueError:
                        try:
                            result[k] = float(v)
                        except ValueError:
                            result[k] = v

    return result


# ─── CANDIDATES.md parser ────────────────────────────────────────────────────

def _parse_yaml_block(block_text: str) -> dict:
    """Parse a fenced YAML block into a dict. Uses ruamel.yaml > yaml > regex fallback."""
    try:
        import ruamel.yaml
        y = ruamel.yaml.YAML()
        y.preserve_quotes = True
        import io
        data = y.load(io.StringIO(block_text))
        return dict(data) if data else {}
    except ImportError:
        pass

    try:
        import yaml
        data = yaml.safe_load(block_text)
        return dict(data) if data else {}
    except ImportError:
        pass

    # Regex fallback — handles flat key: value pairs (no nested structures)
    result: dict = {}
    for line in block_text.splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        k, _, v = line.partition(":")
        k = k.strip().lstrip("- ").strip()
        v = v.strip().strip("'\"")
        if k and v:
            if v.lower() == "true":
                result[k] = True
            elif v.lower() == "false":
                result[k] = False
            else:
                try:
                    result[k] = int(v)
                except ValueError:
                    try:
                        result[k] = float(v)
                    except ValueError:
                        result[k] = v
    return result


def _parse_candidates(candidates_path: Path) -> list[dict]:
    """Parse CANDIDATES.md — extract all fenced yaml blocks with id: L-XXX."""
    if not candidates_path.exists():
        return []

    text = candidates_path.read_text(encoding="utf-8", errors="replace")
    candidates = []

    # Find all fenced yaml blocks
    fenced_pattern = re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL)
    for m in fenced_pattern.finditer(text):
        block_text = m.group(1).strip()
        if not block_text:
            continue
        # Must contain id: L-
        if not re.search(r"^\s*id\s*:", block_text, re.MULTILINE):
            continue
        data = _parse_yaml_block(block_text)
        if data.get("id") and str(data["id"]).startswith("L-"):
            candidates.append(data)

    return candidates


# ─── REJECTED.md parser ──────────────────────────────────────────────────────

def _title_slug(title: str) -> str:
    """Normalize title to a slug for reject-count matching."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _count_rejected(candidates_by_title: dict[str, list[dict]], rejected_path: Path) -> dict[str, int]:
    """Return {candidate_id: reject_count} by counting rejection events in REJECTED.md.

    Each `- id: L-XXX` line in REJECTED.md is one rejection event.
    The same ID can appear multiple times (once per rejection round).
    We also match on original_trigger slug for candidates that were rejected
    before receiving an L-id.
    """
    reject_counts: dict[str, int] = {}

    if not rejected_path.exists():
        return reject_counts

    text = rejected_path.read_text(encoding="utf-8", errors="replace")

    # Count each occurrence of `- id: <ID>` — same ID can appear multiple times
    id_counter: dict[str, int] = {}
    id_pattern = re.compile(r"^- id:\s*([\w-]+)", re.MULTILINE)
    for m in id_pattern.finditer(text):
        rid = m.group(1)
        id_counter[rid] = id_counter.get(rid, 0) + 1

    # Also extract original_trigger slugs for slug-based matching
    rejected_title_slugs: list[str] = []
    trigger_pattern = re.compile(r"original_trigger:\s*['\"]?(.+?)['\"]?$", re.MULTILINE)
    for m in trigger_pattern.finditer(text):
        slug = _title_slug(m.group(1))
        if slug:
            rejected_title_slugs.append(slug)

    # Build reject count per candidate ID based on:
    # 1. Direct ID match count (L-XXX appearance count in REJECTED.md)
    # 2. Title slug match against original_trigger slugs
    for cid, candidate in candidates_by_title.items():
        cand_id = candidate.get("id", "")
        cand_title = str(candidate.get("title", ""))
        cand_slug = _title_slug(cand_title)

        # Direct ID count (handles same ID rejected multiple times)
        count = id_counter.get(cand_id, 0)

        # Slug-based count for trigger matches
        for slug in rejected_title_slugs:
            if slug and cand_slug and (slug == cand_slug or
                    (len(cand_slug) > 5 and cand_slug in slug) or
                    (len(slug) > 5 and slug in cand_slug)):
                count += 1

        if count > 0:
            reject_counts[cid] = count

    return reject_counts


# ─── Tier classification ──────────────────────────────────────────────────────

def _classify_tier(candidate: dict, reject_count: int, config: dict) -> tuple[str, str]:
    """Return (tier, reason) for a candidate."""
    retire_threshold = int(config.get("retire_after_rejects", 2))
    tier_a_conf = float(config.get("tier_a_threshold_confidence", 0.85))
    tier_b_conf = float(config.get("tier_b_threshold_confidence", 0.6))

    # Retirement gate (runs first)
    if reject_count >= retire_threshold:
        return "RETIRED", f"rejected {reject_count}x >= threshold {retire_threshold}"

    # Read confidence — default 0.5 if missing/invalid
    raw_conf = candidate.get("confidence")
    try:
        confidence = float(raw_conf) if raw_conf is not None else 0.5
    except (ValueError, TypeError):
        confidence = 0.5

    # Read impact — default "important" if missing/invalid
    raw_impact = candidate.get("impact")
    if raw_impact not in ("critical", "important", "nice"):
        raw_impact = "important"
    impact = raw_impact

    # Tier A: high confidence AND critical impact
    if confidence >= tier_a_conf and impact == "critical":
        return "A", f"confidence={confidence} >= {tier_a_conf} and impact=critical"

    # Tier B: medium+ confidence AND critical or important impact
    if confidence >= tier_b_conf and impact in ("critical", "important"):
        return "B", f"confidence={confidence} >= {tier_b_conf} and impact={impact}"

    # Tier C: everything else
    if impact == "nice":
        return "C", f"impact=nice caps tier to C (confidence={confidence})"
    return "C", f"confidence={confidence} < {tier_b_conf} threshold"


# ─── Shadow evaluator output loader (v2.6 Phase A) ───────────────────────────

def _load_shadow_output(path: Path | None) -> dict[str, dict]:
    """Read JSONL emitted by bootstrap-shadow-evaluator.py, return {id: record}.

    Records carry: tier_proposed, correctness, n_samples, demote,
    adaptive_threshold, optional critic_verdict/critic_reason.
    Returns {} if file absent or unreadable — classifier then falls back
    to the v2.5 fixed-threshold heuristic.
    """
    if not path or not path.exists():
        return {}
    out: dict[str, dict] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = rec.get("id")
            if isinstance(cid, str) and cid.startswith("L-"):
                out[cid] = rec
    except OSError:
        return {}
    return out


# ─── Main functions ───────────────────────────────────────────────────────────

def classify_all(candidates: list[dict], config: dict,
                 reject_counts: dict[str, int],
                 include_retired: bool = False,
                 shadow_records: dict[str, dict] | None = None) -> list[dict]:
    """Classify all candidates, return list of result dicts.

    v2.6 Phase A: when `shadow_records` is supplied (one record per candidate
    from bootstrap-shadow-evaluator.py), the adaptive `tier_proposed` from
    the evaluator OVERRIDES the v2.5 confidence+impact heuristic.
    Candidates without a shadow record fall back to v2.5 logic (grandfather).
    """
    shadow_records = shadow_records or {}
    results = []
    for c in candidates:
        cid = c.get("id", "unknown")
        rc = reject_counts.get(cid, 0)
        tier, reason = _classify_tier(c, rc, config)

        if tier == "RETIRED" and not include_retired:
            continue

        raw_conf = c.get("confidence")
        try:
            confidence = float(raw_conf) if raw_conf is not None else 0.5
        except (ValueError, TypeError):
            confidence = 0.5

        impact = c.get("impact", "important")
        if impact not in ("critical", "important", "nice"):
            impact = "important"

        # v2.6 Phase A: adaptive override from shadow evaluator output
        shadow = shadow_records.get(cid)
        adaptive_meta: dict = {}
        if shadow and tier != "RETIRED":
            proposed = shadow.get("tier_proposed")
            if proposed in ("A", "B", "C"):
                tier = proposed
                reason = (
                    f"shadow correctness={shadow.get('correctness'):.2f} "
                    f"n_samples={shadow.get('n_samples')} "
                    f"threshold={shadow.get('adaptive_threshold')}"
                )
            adaptive_meta = {
                "shadow_correctness": shadow.get("correctness"),
                "shadow_n_samples": shadow.get("n_samples"),
                "adaptive_threshold": shadow.get("adaptive_threshold"),
                "demote": bool(shadow.get("demote", False)),
            }
            if "critic_verdict" in shadow:
                adaptive_meta["critic_verdict"] = shadow["critic_verdict"]
            if "critic_reason" in shadow:
                adaptive_meta["critic_reason"] = shadow["critic_reason"]

        record = {
            "id": cid,
            "tier": tier,
            "confidence": confidence,
            "impact": impact,
            "reject_count": rc,
            "reason": reason,
            "title": c.get("title", ""),
        }
        record.update(adaptive_meta)
        results.append(record)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(
        description="VG Bootstrap Learn — Tier Classifier (v2.5 Phase H)"
    )
    ap.add_argument("--all", action="store_true", help="Classify all candidates, emit JSONL")
    ap.add_argument("--candidate", metavar="L-XXX", help="Classify single candidate, emit JSON")
    ap.add_argument("--include-retired", action="store_true", help="Include RETIRED in --all output")
    ap.add_argument("--candidates-path", help="Path to CANDIDATES.md (default: .vg/bootstrap/CANDIDATES.md)")
    ap.add_argument("--rejected-path", help="Path to REJECTED.md (default: .vg/bootstrap/REJECTED.md)")
    ap.add_argument("--shadow-jsonl", metavar="PATH",
                    help="(v2.6 Phase A) JSONL output from bootstrap-shadow-evaluator.py — "
                         "adaptive tier_proposed overrides fixed-threshold heuristic when present")
    args = ap.parse_args()

    if not args.all and not args.candidate:
        ap.print_help()
        return 1

    candidates_path = Path(args.candidates_path) if args.candidates_path else BOOTSTRAP_DIR / "CANDIDATES.md"
    rejected_path = Path(args.rejected_path) if args.rejected_path else BOOTSTRAP_DIR / "REJECTED.md"

    config = _load_config()
    candidates = _parse_candidates(candidates_path)

    # Build candidates_by_title map for reject counting
    candidates_by_title = {c.get("id", ""): c for c in candidates}
    reject_counts = _count_rejected(candidates_by_title, rejected_path)

    # v2.6 Phase A: load shadow evaluator output if supplied
    shadow_records = _load_shadow_output(
        Path(args.shadow_jsonl) if args.shadow_jsonl else None
    )

    if args.candidate:
        # Single candidate mode
        target_id = args.candidate.strip()
        match = next((c for c in candidates if c.get("id") == target_id), None)
        if not match:
            print(json.dumps({"error": f"Candidate {target_id} not found in {candidates_path}"}))
            return 1

        # Reuse classify_all path so adaptive override applies uniformly
        single = classify_all(
            [match], config, reject_counts,
            include_retired=True,
            shadow_records=shadow_records,
        )
        if not single:
            print(json.dumps({"error": f"Candidate {target_id} retired/filtered"}))
            return 1
        print(json.dumps(single[0]))
        return 0

    # --all mode: emit JSONL
    results = classify_all(
        candidates, config, reject_counts,
        args.include_retired,
        shadow_records=shadow_records,
    )
    for item in results:
        print(json.dumps(item))

    return 0


if __name__ == "__main__":
    sys.exit(main())
