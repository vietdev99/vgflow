#!/usr/bin/env python3
"""enrich-env-question.py — emit decorated env options for AskUserQuestion.

Reads ${PHASE_DIR}/DEPLOY-STATE.json (if present) + applies 3-signal recommendation
to produce per-env labels + descriptions that the skill body merges into the env
question of step 0a (review / test / roam).

Constraint: SUGGESTION ONLY. The user still picks. Helper just decorates the
options so the user sees evidence-backed recommendations.

Signals (descending weight):
  1. Per-phase preference (`preferred_env_for.{command}` in DEPLOY-STATE.json)
  2. Deploy freshness (`deployed.{env}.deployed_at` within `recent_window_min`)
  3. Profile heuristic (feature/bugfix → sandbox; security-critical → staging)

Output: JSON to stdout. Schema:
  {
    "phase": "3.4a",
    "command": "review",
    "deploy_state_present": bool,
    "preferred_env": "sandbox" | null,
    "envs": {
      "local|sandbox|staging|prod": {
        "decorated_label": "...",
        "decorated_description": "...",
        "is_recommended": bool,
        "evidence": [...]  # list of strings — why this env was/wasn't recommended
      }
    }
  }

Skill body usage (in step 0a bash before AskUserQuestion):
  python3 .claude/scripts/enrich-env-question.py \\
    --phase-dir "${PHASE_DIR}" \\
    --command review \\
    > "${PHASE_DIR}/.tmp/env-options.json"

  # Then AI reads the JSON and builds AskUserQuestion options with the
  # decorated_label + decorated_description fields.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


# Default base options (when no DEPLOY-STATE) — match what review/test/roam skills
# already prompt. Helper decorates these on top.
BASE_OPTIONS = {
    "local": {
        "label": "local — máy của bạn",
        "description": "Browser MCP local, port 3001-3010. Fastest, không cần SSH.",
    },
    "sandbox": {
        "label": "sandbox — VPS Hetzner (printway.work)",
        "description": "Production-like, ssh deploy. Phù hợp khi muốn soi env gần production.",
    },
    "staging": {
        "label": "staging — staging server",
        "description": "Chỉ chọn nếu config có. Hiện chưa cấu hình ở project này.",
    },
    "prod": {
        "label": "prod — production",
        "description": "CẢNH BÁO read-only. Workflow block mọi mutation lens.",
    },
}

# Profile heuristic — fallback when no per-phase preference + no recent deploy.
PROFILE_DEFAULT = {
    "review":   {"feature": "sandbox", "bugfix": "sandbox", "hotfix": "sandbox", "infra": "sandbox", "migration": "sandbox", "docs": "local"},
    "test":     {"feature": "sandbox", "bugfix": "sandbox", "hotfix": "sandbox", "infra": "sandbox", "migration": "sandbox", "docs": "local"},
    "roam":     {"feature": "sandbox", "bugfix": "sandbox", "hotfix": "staging", "infra": "sandbox", "migration": "staging", "docs": "local"},
    "accept":   {"feature": "prod", "bugfix": "prod", "hotfix": "prod", "infra": "sandbox", "migration": "staging", "docs": "local"},
}


def parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        # Tolerate both "Z" suffix and explicit offset
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def minutes_since(ts: str) -> int | None:
    dt = parse_iso(ts)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return int(delta.total_seconds() // 60)


def detect_phase_profile(phase_dir: Path) -> str:
    """Mirror of phase-profile.sh detect_phase_profile, lite version.

    Used as a fallback recommendation signal. Reads SPECS.md for rough markers.
    """
    specs = phase_dir / "SPECS.md"
    if not specs.exists():
        return "feature"
    try:
        text = specs.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "feature"

    lower = text.lower()
    if "**parent phase:**" in lower or "\nparent_phase:" in text:
        return "hotfix"
    if "**issue_id**:" in lower or "\nissue_id:" in text or "**fixes bug**:" in lower:
        return "bugfix"
    if "migration" in lower and any(seg in lower for seg in ("/migrations", ".sql", "schema change")):
        return "migration"
    if "## success criteria" in lower and any(cmd in lower for cmd in ("ssh ", "ansible", "pm2", "systemctl", "kubectl")):
        return "infra"
    return "feature"


def build_envs(deploy_state: dict, command: str, phase_profile: str, recent_window_min: int) -> dict:
    """Compute per-env decoration."""
    deployed = deploy_state.get("deployed", {}) or {}
    preferred = (deploy_state.get("preferred_env_for", {}) or {}).get(command)

    # Profile fallback recommendation (when no preferred_env_for + no recent deploy)
    profile_pick = PROFILE_DEFAULT.get(command, {}).get(phase_profile, "local")

    # Determine THE recommendation env (single best pick)
    recommended_env = None
    if preferred:
        recommended_env = preferred
    else:
        # Check freshest deploy ≤ recent_window_min
        freshest_env = None
        freshest_min = None
        for env_name, info in deployed.items():
            if info.get("health") != "ok":
                continue
            mins = minutes_since(info.get("deployed_at", ""))
            if mins is not None and mins <= recent_window_min:
                if freshest_min is None or mins < freshest_min:
                    freshest_min = mins
                    freshest_env = env_name
        if freshest_env:
            recommended_env = freshest_env
        else:
            recommended_env = profile_pick

    envs = {}
    for env_name, base in BASE_OPTIONS.items():
        evidence = []
        # Deploy state evidence
        d_info = deployed.get(env_name)
        if d_info and d_info.get("health") == "ok":
            mins = minutes_since(d_info.get("deployed_at", ""))
            sha = (d_info.get("sha", "") or "")[:7]
            if mins is not None:
                if mins <= 5:
                    evidence.append(f"deployed {mins}min ago" + (f", sha {sha}" if sha else ""))
                elif mins <= recent_window_min:
                    evidence.append(f"deployed {mins}min ago (still fresh)" + (f", sha {sha}" if sha else ""))
                else:
                    hours = mins // 60
                    if hours >= 24:
                        days = hours // 24
                        evidence.append(f"deployed {days}d ago, may be stale (sha {sha})")
                    else:
                        evidence.append(f"deployed {hours}h ago (sha {sha})")
            else:
                evidence.append(f"deployed (sha {sha})" if sha else "deployed")
        elif d_info and d_info.get("health") and d_info.get("health") != "ok":
            evidence.append(f"deploy unhealthy: {d_info.get('health')}")
        elif env_name != "local":
            # Non-local without deploy entry → flag
            evidence.append("chưa deploy phase này")

        # Per-phase preference evidence
        if preferred == env_name:
            evidence.append("phase prefers this env")

        # Profile fallback evidence
        if recommended_env == env_name and not preferred and not (d_info and d_info.get("health") == "ok"):
            evidence.append(f"profile={phase_profile} default")

        is_recommended = (env_name == recommended_env)

        # Build decorated label + description
        label = base["label"]
        if is_recommended:
            label = f"{base['label']} (Recommended)"

        # Description: base + evidence
        desc_parts = [base["description"]]
        if evidence:
            desc_parts.append(" ".join([f"[{e}]" for e in evidence]))
        decorated_description = " ".join(desc_parts)

        envs[env_name] = {
            "decorated_label": label,
            "decorated_description": decorated_description,
            "is_recommended": is_recommended,
            "evidence": evidence,
        }

    return envs, recommended_env, preferred


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--command", required=True, choices=["review", "test", "roam", "accept"])
    ap.add_argument("--recent-window-min", type=int, default=30,
                    help="Minutes — deploys fresher than this count toward recommendation (default 30)")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir)
    if not phase_dir.is_dir():
        print(json.dumps({
            "error": f"phase_dir does not exist: {phase_dir}",
            "deploy_state_present": False,
            "envs": {n: {"decorated_label": b["label"], "decorated_description": b["description"],
                         "is_recommended": False, "evidence": []} for n, b in BASE_OPTIONS.items()},
        }, indent=2))
        return 1

    deploy_state_path = phase_dir / "DEPLOY-STATE.json"
    deploy_state = {}
    deploy_state_present = False
    if deploy_state_path.exists():
        try:
            deploy_state = json.loads(deploy_state_path.read_text(encoding="utf-8"))
            deploy_state_present = True
        except Exception as e:
            print(f"[enrich-env] WARN: bad DEPLOY-STATE.json: {e}", file=sys.stderr)

    phase_profile = detect_phase_profile(phase_dir)
    envs, recommended_env, preferred = build_envs(
        deploy_state, args.command, phase_profile, args.recent_window_min
    )

    out = {
        "phase": phase_dir.name,
        "command": args.command,
        "phase_profile": phase_profile,
        "deploy_state_present": deploy_state_present,
        "preferred_env": preferred,
        "recommended_env": recommended_env,
        "envs": envs,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
