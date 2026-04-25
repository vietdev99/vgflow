#!/usr/bin/env python3
"""
VG Bootstrap — Shadow Evaluator (v2.6 Phase A)

Replaces the fixed-threshold auto-promote logic
(`tier_a_auto_promote_after_confirms=3`) with adaptive correctness-rate
evaluation.

For each pending candidate L-XXX:
  1. Read .vg/events.jsonl, group events by `payload.candidate_id == L-XXX`.
  2. For each event, look up the phase commit log (git log --grep=phase
     subject pattern) and check whether the commit citation pattern is
     CONSISTENT with the rule prediction (decision_id / contract / goal).
  3. Compute shadow_correct / shadow_total → correctness rate.
  4. Apply tier decision:
       correctness ≥ shadow_correctness_critical AND n_samples ≥ shadow_min_phases
         → tier_proposed = "A"
       correctness ≥ shadow_correctness_important AND n_samples ≥ shadow_min_phases
         → tier_proposed = "B"
       n_samples < shadow_min_phases  → tier_proposed = "C" (insufficient data)
       otherwise (low correctness) → tier_proposed = "C"
  5. Stale-Tier-A demotion: if candidate.status == "promoted" AND
     active for > shadow_stale_phases AND correctness drops below
     shadow_correctness_important → emit demote signal (tier_proposed="C",
     demote=true).
  6. With --critic flag: spawn Haiku LLM with rule prose + 3 sample commits
     and parse advisory verdict (supports/contradicts/insufficient).
     Degrade gracefully if model unreachable or no API key.

Output: JSONL on stdout (or --output-jsonl path). Schema:
  {
    "id": "L-042",
    "tier_proposed": "A" | "B" | "C",
    "correctness": 0.83,
    "n_samples": 18,
    "shadow_since_phase": "7.16",
    "demote": false,
    "critic_verdict": "supports" | "contradicts" | "insufficient",  # optional
    "critic_reason": "..."  # optional
  }

CLI:
  bootstrap-shadow-evaluator.py [--critic] [--candidate L-XXX]
                                [--output-jsonl path] [--config path]

Stdlib only. Idempotent (no state writes; pure function over events.jsonl
and CANDIDATES.md).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


# ─── Repo root + paths ───────────────────────────────────────────────────────

def _repo_root() -> Path:
    env = os.environ.get("VG_REPO_ROOT")
    if env:
        return Path(env)
    p = Path(__file__).resolve()
    for parent in [p.parent, p.parent.parent, p.parent.parent.parent]:
        if (parent / ".claude" / "vg.config.md").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _repo_root()
EVENTS_JSONL = REPO_ROOT / ".vg" / "events.jsonl"
CANDIDATES_MD = REPO_ROOT / ".vg" / "bootstrap" / "CANDIDATES.md"
CONFIG_MD = REPO_ROOT / ".claude" / "vg.config.md"

# Critic prompt template — sub-file under _shared/prompts/
CRITIC_PROMPT_PATH = (
    REPO_ROOT
    / ".claude"
    / "commands"
    / "vg"
    / "_shared"
    / "prompts"
    / "bootstrap-critic-prompt.md"
)


# ─── Citation patterns (mirror of commit-attribution.py) ─────────────────────

CITATION_PATTERNS = [
    re.compile(r"Per\s+API-CONTRACTS\.md", re.IGNORECASE),
    re.compile(r"Per\s+CONTEXT\.md\s+D-\d+", re.IGNORECASE),
    re.compile(r"Covers?\s+goal:?\s+G-\d+", re.IGNORECASE),
    re.compile(r"\bno-goal-impact\b", re.IGNORECASE),
    re.compile(r"\bno-impact\b", re.IGNORECASE),
]
DECISION_RE = re.compile(r"Per\s+CONTEXT\.md\s+(?:P[\d.]+\.)?D-(\d+)", re.IGNORECASE)
GOAL_RE = re.compile(r"Covers?\s+goal:?\s+G-(\d+)", re.IGNORECASE)


# ─── Config loading ──────────────────────────────────────────────────────────

DEFAULTS = {
    "shadow_mode_default": True,
    "shadow_min_phases": 5,
    "shadow_correctness_critical": 0.95,
    "shadow_correctness_important": 0.80,
    "shadow_stale_phases": 10,
    "critic_enabled": False,
    "critic_model": "claude-haiku-4-5-20251001",
}


def load_config(config_path: Path | None = None) -> dict:
    cfg_path = config_path or CONFIG_MD
    result = dict(DEFAULTS)
    if not cfg_path.exists():
        return result

    text = cfg_path.read_text(encoding="utf-8", errors="replace")
    in_bootstrap = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("bootstrap:"):
            in_bootstrap = True
            continue
        if in_bootstrap:
            if stripped.startswith("---") or (
                line and not line[0].isspace() and ":" in line and not stripped.startswith("#")
            ):
                break
            if not stripped or stripped.startswith("#"):
                continue
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                k = k.strip()
                v = v.strip().split("#")[0].strip().strip("'\"")
                if not k or not v:
                    continue
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


# ─── Events.jsonl reader ─────────────────────────────────────────────────────

def read_events(events_path: Path | None = None) -> list[dict]:
    p = events_path or EVENTS_JSONL
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def group_events_by_candidate(events: list[dict]) -> dict[str, list[dict]]:
    """Group events with payload.candidate_id == L-XXX."""
    by_cand: dict[str, list[dict]] = {}
    for e in events:
        payload = e.get("payload") or {}
        cid = payload.get("candidate_id")
        if isinstance(cid, str) and cid.startswith("L-"):
            by_cand.setdefault(cid, []).append(e)
    return by_cand


# ─── Candidates parser (lightweight; reuse YAML logic) ───────────────────────

def parse_candidates(path: Path | None = None) -> list[dict]:
    p = path or CANDIDATES_MD
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8", errors="replace")
    out: list[dict] = []
    for m in re.finditer(r"```yaml\s*\n(.*?)```", text, re.DOTALL):
        block = m.group(1).strip()
        if not block:
            continue
        if not re.search(r"^\s*id\s*:\s*L-", block, re.MULTILINE):
            continue
        out.append(_parse_yaml_lite(block))
    return out


def _parse_yaml_lite(block_text: str) -> dict:
    """Minimal YAML-like parser for flat key:value blocks (stdlib only)."""
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(block_text)
        return dict(data) if data else {}
    except Exception:
        pass
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


# ─── Commit citation lookup ──────────────────────────────────────────────────

def commit_message(sha: str) -> str:
    if not sha or not re.match(r"^[0-9a-f]{4,40}$", sha):
        return ""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%B", sha],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def citation_matches_prediction(commit_body: str, predicted: dict) -> bool:
    """Return True if commit body cites the SAME decision/goal/contract that
    the candidate rule predicted as relevant.

    `predicted` may carry: `decision_id` (int), `goal_id` (int),
    `contract` (bool). When events.jsonl lacks predicted refs, fall back to
    "any citation present" (consistent rule application).
    """
    if not commit_body:
        return False

    if predicted.get("contract"):
        if re.search(r"Per\s+API-CONTRACTS\.md", commit_body, re.IGNORECASE):
            return True

    if "decision_id" in predicted and predicted["decision_id"] is not None:
        n = int(predicted["decision_id"])
        for m in DECISION_RE.finditer(commit_body):
            if int(m.group(1)) == n:
                return True

    if "goal_id" in predicted and predicted["goal_id"] is not None:
        n = int(predicted["goal_id"])
        for m in GOAL_RE.finditer(commit_body):
            if int(m.group(1)) == n:
                return True

    if not any(k in predicted for k in ("decision_id", "goal_id", "contract")):
        for pat in CITATION_PATTERNS:
            if pat.search(commit_body):
                return True

    return False


# ─── Correctness compute ─────────────────────────────────────────────────────

def evaluate_candidate(
    candidate_id: str,
    events: list[dict],
    candidate: dict,
) -> dict:
    """Return raw stats dict for one candidate (no tier decision yet)."""
    correct = 0
    total = 0
    earliest_phase: str | None = None

    for e in events:
        payload = e.get("payload") or {}
        sha = payload.get("commit_sha") or payload.get("git_sha")
        predicted = payload.get("predicted") or {}
        phase = e.get("phase")

        if phase and (earliest_phase is None or str(phase) < str(earliest_phase)):
            earliest_phase = str(phase)

        body = commit_message(sha) if sha else ""
        if citation_matches_prediction(body, predicted):
            correct += 1
        total += 1

    return {
        "id": candidate_id,
        "shadow_correct": correct,
        "shadow_total": total,
        "correctness": (correct / total) if total > 0 else 0.0,
        "n_samples": total,
        "shadow_since_phase": earliest_phase,
        "impact": candidate.get("impact", "important"),
        "status": candidate.get("status", "pending"),
    }


# ─── Tier decision ──────────────────────────────────────────────────────────

def decide_tier(stats: dict, config: dict) -> dict:
    """Apply correctness + n_samples gates → tier_proposed + demote signal."""
    n = stats["n_samples"]
    rate = stats["correctness"]
    impact = stats.get("impact", "important")
    status = stats.get("status", "pending")

    min_n = int(config.get("shadow_min_phases", 5))
    crit_thr = float(config.get("shadow_correctness_critical", 0.95))
    imp_thr = float(config.get("shadow_correctness_important", 0.80))
    stale_phases = int(config.get("shadow_stale_phases", 10))

    demote = False
    threshold_used = imp_thr

    if status == "promoted" and n >= stale_phases and rate < imp_thr:
        demote = True
        tier = "C"
        threshold_used = imp_thr
    elif n < min_n:
        tier = "C"
    elif impact == "critical" and rate >= crit_thr:
        tier = "A"
        threshold_used = crit_thr
    elif rate >= imp_thr:
        tier = "B"
        threshold_used = imp_thr
    else:
        tier = "C"

    return {
        **stats,
        "tier_proposed": tier,
        "demote": demote,
        "adaptive_threshold": threshold_used,
    }


# ─── Critic mode (Haiku LLM advisory) ────────────────────────────────────────

def render_critic_prompt(candidate: dict, sample_commits: list[str]) -> str:
    """Render the prompt template with rule prose + samples filled in."""
    if CRITIC_PROMPT_PATH.exists():
        tpl = CRITIC_PROMPT_PATH.read_text(encoding="utf-8", errors="replace")
    else:
        tpl = (
            "Evaluate whether the rule below is consistent with the cited "
            "commit references.\n\nRULE: {prose}\n\nCOMMITS:\n{commits}\n\n"
            'Respond JSON: {{"verdict": "supports|contradicts|insufficient", '
            '"reason": "<=200 chars"}}'
        )
    prose = str(candidate.get("prose") or candidate.get("title") or "")
    commits_block = "\n---\n".join(sample_commits[:3]) or "(none)"
    return tpl.replace("{prose}", prose).replace("{commits}", commits_block)


def call_critic(prompt: str, model: str) -> dict | None:
    """Invoke Anthropic SDK if available + key set; degrade gracefully."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts = [
            getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text"
        ]
        text = "\n".join(text_parts).strip()
    except Exception:
        return None

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    verdict = parsed.get("verdict")
    if verdict not in ("supports", "contradicts", "insufficient"):
        return None
    return {
        "critic_verdict": verdict,
        "critic_reason": str(parsed.get("reason", ""))[:200],
    }


def sample_commits_for_candidate(events: list[dict], k: int = 3) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for e in events:
        sha = (e.get("payload") or {}).get("commit_sha") or (e.get("payload") or {}).get("git_sha")
        if not sha or sha in seen:
            continue
        body = commit_message(sha)
        if body:
            out.append(body.strip())
            seen.add(sha)
        if len(out) >= k:
            break
    return out


# ─── Main ────────────────────────────────────────────────────────────────────

def evaluate_all(
    candidates: list[dict],
    events: list[dict],
    config: dict,
    critic: bool = False,
    critic_disabled_reason: str | None = None,
) -> list[dict]:
    by_cand = group_events_by_candidate(events)
    results: list[dict] = []
    for c in candidates:
        cid = str(c.get("id") or "").strip()
        if not cid.startswith("L-"):
            continue
        evs = by_cand.get(cid, [])
        stats = evaluate_candidate(cid, evs, c)
        decision = decide_tier(stats, config)

        if critic and decision["tier_proposed"] == "B":
            if critic_disabled_reason:
                decision["critic_verdict"] = "skipped"
                decision["critic_reason"] = critic_disabled_reason
            else:
                samples = sample_commits_for_candidate(evs)
                prompt = render_critic_prompt(c, samples)
                verdict = call_critic(prompt, str(config.get("critic_model", "")))
                if verdict is not None:
                    decision.update(verdict)
                # else: graceful degrade — omit critic_* fields

        results.append(decision)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="VG Bootstrap — Shadow Evaluator (v2.6 Phase A)"
    )
    ap.add_argument("--critic", action="store_true",
                    help="Emit Haiku LLM advisory verdict per Tier-B candidate")
    ap.add_argument("--candidate", metavar="L-XXX", help="Evaluate single candidate")
    ap.add_argument("--output-jsonl", metavar="PATH", help="Write JSONL output to file (default stdout)")
    ap.add_argument("--config", metavar="PATH", help="Override vg.config.md path")
    ap.add_argument("--candidates-path", metavar="PATH", help="Override CANDIDATES.md path")
    ap.add_argument("--events-path", metavar="PATH", help="Override events.jsonl path")
    args = ap.parse_args(argv)

    config = load_config(Path(args.config) if args.config else None)
    candidates = parse_candidates(Path(args.candidates_path) if args.candidates_path else None)
    events = read_events(Path(args.events_path) if args.events_path else None)

    if args.candidate:
        candidates = [c for c in candidates if c.get("id") == args.candidate]

    critic_disabled_reason = None
    if args.critic and not config.get("critic_enabled", False):
        critic_disabled_reason = "critic_enabled=false in config"

    results = evaluate_all(
        candidates, events, config,
        critic=args.critic,
        critic_disabled_reason=critic_disabled_reason,
    )

    out_lines = [json.dumps(r, sort_keys=True) for r in results]
    if args.output_jsonl:
        Path(args.output_jsonl).write_text(
            "\n".join(out_lines) + ("\n" if out_lines else ""),
            encoding="utf-8",
        )
    else:
        for line in out_lines:
            print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
