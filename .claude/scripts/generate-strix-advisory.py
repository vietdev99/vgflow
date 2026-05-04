#!/usr/bin/env python3
"""
generate-strix-advisory.py — v2.32.0 Step 6 of /vg:security-audit-milestone.

Generates a STRIX-ADVISORY.md recommending users run usestrix/strix
(autonomous AI pentest agent) against the milestone's accumulated attack
surface. VG does NOT run Strix itself — Strix needs Docker + separate LLM
API key + target URL, all of which are user-side concerns.

This advisor:
  1. Walks every phase in the milestone (or --phases range).
  2. Aggregates `adversarial_scope` declarations from each phase's
     TEST-GOALS.md (v2.21.0 declarative threat schema).
  3. Aggregates HTTP endpoints from API-CONTRACTS.md by auth model.
  4. Emits STRIX-ADVISORY.md (markdown for human) + strix-scope.json
     (machine-readable for Strix's --scope-file flag).
  5. Provides ready-to-copy Strix invocation command tailored to the
     declared threats + target URL from vg.config.md.

Strix integration is opt-in (config: `security.strix_advisor.enabled`).
Disable to skip this step entirely.

Usage:
  generate-strix-advisory.py --milestone M1
  generate-strix-advisory.py --phases 3-7              # explicit phase range
  generate-strix-advisory.py --milestone M1 --target-url http://localhost:3001
  generate-strix-advisory.py --milestone M1 --json     # machine-readable output

Exit codes:
  0 — advisory written (or skipped because nothing to advise)
  1 — config error (missing milestone + no phases discovered)
  2 — write error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()
PLANNING_DIR = Path(os.environ.get("VG_PLANNING_DIR") or REPO_ROOT / ".vg")

ADVERSARIAL_BLOCK_RE = re.compile(
    r"adversarial_scope\s*:\s*\n((?:[ \t]+.+\n)+)", re.MULTILINE
)
THREAT_LIST_RE = re.compile(r"threats\s*:\s*\[([^\]]*)\]")
HTTP_LINE_RE = re.compile(
    r"^\s*-?\s*(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(?P<path>/\S+)",
    re.MULTILINE,
)


def discover_phases(milestone: str | None, phase_range: str | None) -> list[Path]:
    """Resolve which phase dirs are in scope for this advisory."""
    phases_root = PLANNING_DIR / "phases"
    if not phases_root.is_dir():
        return []

    all_phases = sorted(
        (p for p in phases_root.iterdir() if p.is_dir() and p.name.split("-", 1)[0].isdigit()),
        key=lambda p: int(p.name.split("-", 1)[0]),
    )

    if phase_range:
        if "-" in phase_range:
            lo, hi = phase_range.split("-", 1)
            lo_i, hi_i = int(lo), int(hi)
        else:
            lo_i = hi_i = int(phase_range)
        return [p for p in all_phases if lo_i <= int(p.name.split("-", 1)[0]) <= hi_i]

    if milestone:
        state_file = PLANNING_DIR / "STATE.md"
        if state_file.is_file():
            txt = state_file.read_text(encoding="utf-8", errors="replace")
            m = re.search(rf"milestone[_-]?{re.escape(milestone)}.*?phases:\s*([0-9,\s-]+)", txt, re.I | re.S)
            if m:
                spec = m.group(1)
                return _resolve_phases_from_spec(all_phases, spec)
        roadmap = PLANNING_DIR / "ROADMAP.md"
        if roadmap.is_file():
            txt = roadmap.read_text(encoding="utf-8", errors="replace")
            section = re.search(rf"##\s*{re.escape(milestone)}\b(.+?)(?=\n##\s|\Z)", txt, re.S)
            if section:
                phase_nums = set(re.findall(r"Phase\s*(\d+)", section.group(1)))
                return [p for p in all_phases if p.name.split("-", 1)[0] in phase_nums]

    return all_phases


def _resolve_phases_from_spec(all_phases: list[Path], spec: str) -> list[Path]:
    nums: set[int] = set()
    for tok in re.split(r"[,\s]+", spec.strip()):
        if not tok:
            continue
        if "-" in tok:
            lo, hi = tok.split("-", 1)
            nums.update(range(int(lo), int(hi) + 1))
        else:
            nums.add(int(tok))
    return [p for p in all_phases if int(p.name.split("-", 1)[0]) in nums]


def parse_adversarial_scope(test_goals_path: Path) -> dict[str, list[str]]:
    """Return {goal_id: [threats]} from a TEST-GOALS.md file.

    Handles both YAML-frontmatter style (preferred) and the looser inline
    `adversarial_scope:` block. Falls back to regex if PyYAML missing.
    """
    if not test_goals_path.is_file():
        return {}

    text = test_goals_path.read_text(encoding="utf-8", errors="replace")

    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None  # type: ignore

    out: dict[str, list[str]] = {}

    if yaml is not None:
        blocks: list[str] = []
        cur: list[str] = []
        in_block = False
        for line in text.splitlines():
            if line.strip() == "---":
                if in_block:
                    blocks.append("\n".join(cur))
                    cur = []
                    in_block = False
                else:
                    in_block = True
                continue
            if in_block:
                cur.append(line)
        for blob in blocks:
            try:
                data = yaml.safe_load(blob)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            gid = data.get("id")
            if not gid or not str(gid).startswith("G-"):
                continue
            adv = data.get("adversarial_scope") or {}
            threats = adv.get("threats") if isinstance(adv, dict) else None
            if isinstance(threats, list) and threats:
                out[str(gid)] = [str(t) for t in threats]

    if not out:
        for m in ADVERSARIAL_BLOCK_RE.finditer(text):
            block = m.group(1)
            tm = THREAT_LIST_RE.search(block)
            if tm:
                threats = [t.strip().strip('"').strip("'") for t in tm.group(1).split(",") if t.strip()]
                out[f"G-unknown-{m.start()}"] = threats

    return out


def parse_endpoints(api_contracts_path: Path) -> list[dict]:
    """Extract HTTP endpoints from API-CONTRACTS.md. Returns list of
    {method, path, auth_hint} dicts. auth_hint is best-effort; users
    refine inside Strix scope.
    """
    if not api_contracts_path.is_file():
        return []
    text = api_contracts_path.read_text(encoding="utf-8", errors="replace")
    out: list[dict] = []
    for m in HTTP_LINE_RE.finditer(text):
        method = m.group("method")
        path = m.group("path").rstrip(".,;:")
        line_end = text.find("\n", m.end())
        if line_end < 0:
            line_end = len(text)
        line_tail = text[m.end():line_end]
        auth = "unknown"
        if re.search(r"\b(admin|role:\s*admin)\b", line_tail, re.I):
            auth = "admin"
        elif re.search(r"\b(authenticated|session|jwt|bearer)\b", line_tail, re.I):
            auth = "authenticated"
        elif re.search(r"\b(public|no\s*auth)\b", line_tail, re.I):
            auth = "public"
        out.append({"method": method, "path": path, "auth_hint": auth})
    seen = set()
    deduped = []
    for ep in out:
        key = (ep["method"], ep["path"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ep)
    return deduped


def aggregate(phases: list[Path]) -> dict:
    """Walk each phase, aggregate threats + endpoints + goal counts."""
    threat_to_goals: dict[str, list[dict]] = {}
    endpoints_by_phase: dict[str, list[dict]] = {}
    phase_summaries: list[dict] = []

    for phase_dir in phases:
        phase_name = phase_dir.name
        tg_path = phase_dir / "TEST-GOALS.md"
        ac_path = phase_dir / "API-CONTRACTS.md"

        scopes = parse_adversarial_scope(tg_path)
        endpoints = parse_endpoints(ac_path)

        for gid, threats in scopes.items():
            for t in threats:
                threat_to_goals.setdefault(t, []).append({"phase": phase_name, "goal": gid})
        if endpoints:
            endpoints_by_phase[phase_name] = endpoints

        phase_summaries.append({
            "phase": phase_name,
            "goals_with_adversarial": len(scopes),
            "threats": sorted({t for ts in scopes.values() for t in ts}),
            "endpoints": len(endpoints),
        })

    return {
        "threat_to_goals": threat_to_goals,
        "endpoints_by_phase": endpoints_by_phase,
        "phase_summaries": phase_summaries,
    }


def write_scope_json(out_path: Path, agg: dict, target_url: str | None) -> None:
    """Machine-readable scope for Strix's --scope-file flag (or future
    `vg-strix-runner` if user opts into VG-managed runs later)."""
    payload = {
        "schema_version": "1",
        "generated": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_url": target_url or "<set in vg.config.md security.strix_advisor.target_url>",
        "threats": sorted(agg["threat_to_goals"].keys()),
        "threat_goals": {t: goals for t, goals in agg["threat_to_goals"].items()},
        "endpoints_by_phase": agg["endpoints_by_phase"],
        "phase_summaries": agg["phase_summaries"],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def render_advisory(agg: dict, milestone: str, target_url: str | None,
                    advisory_path: Path, scope_path: Path) -> str:
    threats = sorted(agg["threat_to_goals"].keys())
    total_goals = sum(len(g) for g in agg["threat_to_goals"].values())
    total_endpoints = sum(len(eps) for eps in agg["endpoints_by_phase"].values())
    target = target_url or "<set in vg.config.md → security.strix_advisor.target_url>"
    threats_csv = ",".join(threats) if threats else "all"

    lines: list[str] = []
    lines.append(f"# Strix Scan Advisory — Milestone {milestone}")
    lines.append("")
    lines.append(f"Generated: {_dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append("")
    lines.append("> **VG does NOT run Strix.** This advisory aggregates the milestone's adversarial surface so an external Strix invocation can validate exploitability. Strix needs Docker + a separate LLM API key + a reachable target URL — all user-side resources.")
    lines.append("")

    if not threats and not total_endpoints:
        lines.append("## Nothing to advise")
        lines.append("")
        lines.append("No `adversarial_scope` declarations or HTTP endpoints found in this milestone. Either (a) phases declare no abuse model (low-risk surfaces), or (b) the milestone scope resolution found no phases. Skipping advisory.")
        return "\n".join(lines)

    lines.append("## Why run Strix on this milestone")
    lines.append("")
    lines.append(f"- **{total_goals}** goal(s) across **{len(agg['phase_summaries'])}** phase(s) declared adversarial threats requiring exploit validation.")
    lines.append(f"- **{len(threats)}** unique threat categor{'y' if len(threats) == 1 else 'ies'}: `{', '.join(threats) or '(none)'}`")
    lines.append(f"- **{total_endpoints}** HTTP endpoint(s) extracted from API-CONTRACTS.md across the milestone.")
    lines.append("")
    lines.append("VG generated `.adversarial.*.spec.ts` codegen files (v2.21.0+), but those execute *declared payloads* against a test runner — they do not autonomously discover novel attack chains. Strix's ReAct loop + multi-agent coordination + actual exploit execution covers that gap.")
    lines.append("")

    lines.append("## Recommended Strix invocation")
    lines.append("")
    lines.append("```bash")
    lines.append("# 1. Pull/update Strix")
    lines.append("docker pull ghcr.io/usestrix/strix:latest")
    lines.append("")
    lines.append("# 2. Run scan with milestone-scoped threat list")
    lines.append("docker run --rm \\")
    lines.append("  -e ANTHROPIC_API_KEY=\"$ANTHROPIC_API_KEY\" \\")
    lines.append(f"  -v \"$(pwd)/{scope_path.resolve().relative_to(REPO_ROOT).as_posix()}:/scope.json:ro\" \\")
    lines.append("  -v \"$(pwd)/.vg/milestones:/output\" \\")
    lines.append("  ghcr.io/usestrix/strix:latest \\")
    lines.append(f"  --target {target}  \\")
    lines.append(f"  --threats {threats_csv} \\")
    lines.append("  --scope-file /scope.json \\")
    lines.append(f"  --output /output/{milestone}/strix-output.json")
    lines.append("```")
    lines.append("")
    lines.append("Replace `ANTHROPIC_API_KEY` with your provider of choice (Strix supports OpenAI, Anthropic, Gemini, Bedrock, OpenRouter — see https://github.com/usestrix/strix#llm-providers).")
    lines.append("")

    lines.append("## Threat → goal traceability")
    lines.append("")
    lines.append("| Threat | Goals declaring it | Phases |")
    lines.append("|---|---|---|")
    for t in threats:
        goals = agg["threat_to_goals"][t]
        goal_ids = sorted({g["goal"] for g in goals})
        phases = sorted({g["phase"] for g in goals})
        lines.append(f"| `{t}` | {len(goal_ids)} ({', '.join(goal_ids[:5])}{'…' if len(goal_ids) > 5 else ''}) | {', '.join(phases)} |")
    lines.append("")

    lines.append("## Endpoint surface (per phase)")
    lines.append("")
    if agg["endpoints_by_phase"]:
        for phase_name, eps in agg["endpoints_by_phase"].items():
            lines.append(f"### {phase_name} ({len(eps)} endpoints)")
            lines.append("")
            buckets: dict[str, list[dict]] = {}
            for ep in eps:
                buckets.setdefault(ep["auth_hint"], []).append(ep)
            for auth, items in sorted(buckets.items()):
                lines.append(f"- **{auth}** ({len(items)})")
                for ep in items[:8]:
                    lines.append(f"  - `{ep['method']} {ep['path']}`")
                if len(items) > 8:
                    lines.append(f"  - … +{len(items) - 8} more (see API-CONTRACTS.md)")
            lines.append("")
    else:
        lines.append("_No HTTP endpoints found in API-CONTRACTS.md across this milestone._")
        lines.append("")

    lines.append("## After the scan")
    lines.append("")
    lines.append("Strix's `strix-output.json` lists confirmed-exploitable findings with PoC payloads. Triage as you would any pentest report:")
    lines.append("")
    lines.append("1. Add critical/high findings to `.vg/SECURITY-REGISTER.md` as `OPEN` threats with the originating goal IDs from this advisory.")
    lines.append("2. Open phases via `/vg:add-phase` for remediation if findings span new attack vectors.")
    lines.append("3. Re-run `/vg:security-audit-milestone` after remediation to confirm the register reflects the post-scan state.")
    lines.append("")
    lines.append("VG provides no auto-import of Strix output by design — findings need human triage to decide phase scope, owner, and severity in the project context.")
    lines.append("")

    lines.append("## Resources required (user-side)")
    lines.append("")
    lines.append("| Resource | Purpose | VG dependency? |")
    lines.append("|---|---|---|")
    lines.append("| Docker | Strix sandbox container | No |")
    lines.append("| LLM API key | Strix's reasoning loop | No (separate from VG's) |")
    lines.append("| Reachable target URL | Strix exploit execution | No |")
    lines.append("| Estimated cost | $5–50 in LLM tokens depending on attack surface | — |")
    lines.append("")

    lines.append("## Disable this advisory")
    lines.append("")
    lines.append("Set `security.strix_advisor.enabled: false` in `vg.config.md` to skip Step 6.")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"Machine-readable scope: `{scope_path.resolve().relative_to(REPO_ROOT)}`")
    lines.append(f"Strix repository: https://github.com/usestrix/strix")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--milestone", help="Milestone ID (e.g. M1) — resolved via STATE.md or ROADMAP.md")
    ap.add_argument("--phases", help="Explicit phase range (e.g. 3-7 or 5)")
    ap.add_argument("--target-url", help="Override target URL (else reads vg.config.md)")
    ap.add_argument("--out", help="Output path (default: .vg/milestones/{M}/STRIX-ADVISORY.md)")
    ap.add_argument("--json", action="store_true", help="Print scope payload to stdout instead of writing files")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.milestone and not args.phases:
        if not args.quiet:
            print("ERROR: provide --milestone <ID> or --phases <range>", file=sys.stderr)
        return 1

    phases = discover_phases(args.milestone, args.phases)
    if not phases:
        if not args.quiet:
            print(f"No phases resolved for milestone={args.milestone!r} phases={args.phases!r} — nothing to advise.")
        return 0

    agg = aggregate(phases)

    target_url = args.target_url
    if not target_url:
        cfg = REPO_ROOT / ".claude" / "vg.config.md"
        if cfg.is_file():
            txt = cfg.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"strix_advisor\s*:[^#]*?target_url\s*:\s*[\"']?([^\"'\s]+)", txt, re.S)
            if m:
                target_url = m.group(1).strip()

    milestone_id = args.milestone or "phases-{}".format(args.phases or "all")
    milestone_dir = PLANNING_DIR / "milestones" / milestone_id

    advisory_path = Path(args.out) if args.out else (milestone_dir / "STRIX-ADVISORY.md")
    scope_path = milestone_dir / "strix-scope.json"

    write_scope_json(scope_path, agg, target_url)
    body = render_advisory(agg, milestone_id, target_url, advisory_path, scope_path)
    advisory_path.parent.mkdir(parents=True, exist_ok=True)
    advisory_path.write_text(body, encoding="utf-8")

    if args.json:
        print(json.dumps({
            "advisory_path": str(advisory_path.resolve().relative_to(REPO_ROOT)),
            "scope_path": str(scope_path.resolve().relative_to(REPO_ROOT)),
            "phases_in_scope": [p.name for p in phases],
            "threats": sorted(agg["threat_to_goals"].keys()),
            "endpoint_count": sum(len(v) for v in agg["endpoints_by_phase"].values()),
        }, indent=2))
    elif not args.quiet:
        print(f"✓ Strix advisory written: {advisory_path.resolve().relative_to(REPO_ROOT)}")
        print(f"  Scope JSON: {scope_path.resolve().relative_to(REPO_ROOT)}")
        print(f"  Phases: {', '.join(p.name for p in phases)}")
        print(f"  Threats: {', '.join(sorted(agg['threat_to_goals'].keys())) or '(none declared)'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
