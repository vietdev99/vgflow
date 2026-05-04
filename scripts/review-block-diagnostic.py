#!/usr/bin/env python3
"""Render human-readable diagnostics for /vg:review BLOCK artifacts.

Validators should fail loudly, but a raw JSON blob is not enough for a user
who needs to decide the next action. This helper turns common review gate
payloads into a short diagnosis, concrete fix paths, and rerun commands.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _read_payload(path: Path) -> tuple[Any, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": f"input unreadable: {exc}"}, ""
    stripped = text.strip()
    if not stripped:
        return {"error": "input empty"}, text
    try:
        return json.loads(stripped.splitlines()[-1] if stripped.count("\n") else stripped), text
    except json.JSONDecodeError:
        try:
            return json.loads(stripped), text
        except json.JSONDecodeError:
            return {"raw": text}, text


def _evidence_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        ev = payload.get("evidence")
        if isinstance(ev, list):
            return [x for x in ev if isinstance(x, dict)]
        missing = payload.get("missing")
        if isinstance(missing, list):
            return [x for x in missing if isinstance(x, dict)]
    return []


def _types(items: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("type") or item.get("plugin") or item.get("reason") or "") for item in items}


def _phase_number(phase_dir: Path) -> str:
    name = phase_dir.name
    match = re.match(r"0*([0-9]+(?:\.[0-9A-Za-z]+)*)", name)
    return match.group(1) if match else name


def diagnose(gate_id: str, phase_dir: Path, payload: Any, raw_text: str) -> dict[str, Any]:
    items = _evidence_items(payload)
    kinds = _types(items)
    phase = _phase_number(phase_dir)
    actions: list[str] = []
    details: list[str] = []
    title = "Review block needs diagnosis"
    family = "unknown"

    if "lens_plan" in gate_id or any("evidence artifact missing" in str(i.get("reason")) for i in items):
        family = "lens_evidence_gap"
        title = "Required review checklist plugins did not produce evidence"
        grouped: dict[str, list[str]] = {}
        for item in items:
            plugin = str(item.get("plugin") or "unknown")
            expected_raw = item.get("expected") or item.get("expected_any") or ""
            if isinstance(expected_raw, list):
                expected = " or ".join(str(x) for x in expected_raw)
            else:
                expected = str(expected_raw)
            grouped.setdefault(plugin, []).append(expected)
        for plugin, expected in sorted(grouped.items())[:8]:
            seen: list[str] = []
            for item in expected:
                if item and item not in seen:
                    seen.append(item)
            details.append(f"{plugin}: missing {', '.join(seen)}")
        actions.extend([
            "Do not mark review complete. The missing plugin evidence means a checklist step was skipped, stale, or wrote artifacts to the wrong location.",
            "Run full forced review so API docs, browser inventory, URL-state/filter/paging, visual, CRUD/RCRURD, security, performance, and findings plugins execute in the current run.",
            f"Command: `/vg:review {phase} --mode=full --force`.",
        ])
    elif gate_id.endswith("api_docs_contract_coverage") or any(k.startswith("api_docs_") for k in kinds):
        family = "api_docs_contract_drift"
        title = "API-DOCS.md is stale or incomplete against API-CONTRACTS.md"
        missing = [i.get("expected") for i in items if i.get("type") == "api_docs_query_param_missing"]
        if missing:
            details.append("Missing query params: " + ", ".join(sorted({str(x) for x in missing if x})[:20]))
        actions.extend([
            f"Run `/vg:build {phase}` so API-DOCS.md is regenerated from API-CONTRACTS.md and implementation evidence.",
            "If build already ran, inspect API-CONTRACTS.md Zod schemas and ensure query/path/body schemas are exported near each endpoint section.",
            f"Then rerun `/vg:review {phase} --mode=full --force`.",
        ])
    elif "url_state_block_missing" in kinds or any(k.startswith("url_state_") for k in kinds):
        family = "url_state_declaration_gap"
        title = "TEST-GOALS.md interactive_controls are missing or incomplete"
        actual = [str(i.get("actual")) for i in items if i.get("actual")]
        if actual:
            details.append("Affected controls/goals: " + " | ".join(actual[:4]))
        actions.extend([
            "Add `interactive_controls` for every list/table/grid goal: filters, pagination, search, sort, `url_param`, and row/result assertions.",
            "Use `url_sync: false` only with a clear `url_sync_waive_reason` when share/refresh/back-forward state is intentionally unsupported.",
            f"Rerun `/vg:review {phase} --mode=full --force` after updating TEST-GOALS.md.",
        ])
    elif "url_runtime_probe_missing" in kinds or any(k.startswith("url_runtime_") for k in kinds):
        family = "url_runtime_probe_gap"
        title = "Runtime URL-state probe did not produce required evidence"
        actions.extend([
            "Make sure browser/device review discovery actually reaches the declared list route and writes `url-runtime-probe.json`.",
            "For filters, record `result_semantics={passed:true, rows_checked:int, violations:[]}`; URL-only success is not enough.",
            f"Rerun `/vg:review {phase} --mode=full --force`; if the route cannot load, fix ENV-CONTRACT/base_url/auth first.",
        ])
    elif "error_message" in gate_id or any(str(k).startswith("error_message_") for k in kinds):
        family = "api_error_message_gap"
        title = "API error message is not proven in the visible UI"
        actions.extend([
            "Run the error-message runtime lens: trigger validation/auth/domain error paths, capture the API error body, then capture the visible toast/form error.",
            "Write `error-message-probe.json` with `api_user_message` or `api_error_message` and `visible_message` for each checked path.",
            "Fix FE adapters so toast/form copy uses `error.user_message || error.message`, not `statusText`, HTTP code text, or raw AxiosError.message.",
            f"Rerun `/vg:review {phase} --mode=full --force` after the probe passes.",
        ])
    elif "interface" in gate_id or any(str(k).startswith("interface_") for k in kinds):
        family = "interface_standard_gap"
        title = "Interface standards are missing or not enforced"
        actions.extend([
            "Generate or update `INTERFACE-STANDARDS.md` and `INTERFACE-STANDARDS.json` for the phase.",
            "Regenerate API contracts/docs so Block 3 and API-DOCS error_handling cite the standard.",
            "Fix FE/CLI adapters that display transport errors instead of standard error envelopes.",
            f"Rerun `/vg:blueprint {phase} --from=2b` or `/vg:build {phase}` depending on which artifact is stale.",
        ])
    elif gate_id.endswith("env_contract") or "ENV-CONTRACT" in raw_text:
        family = "env_contract_gap"
        title = "Review environment contract is missing or failing"
        actions.extend([
            "Create or update `ENV-CONTRACT.md` with `target.base_url`, auth/bootstrap data, and preflight checks.",
            "If testing sandbox/staging/prod, run `/vg:deploy` first so DEPLOY-STATE evidence and health URL are fresh.",
            f"Rerun `/vg:review {phase} --mode=full --force` after env preflight passes.",
        ])
    elif "RUNTIME-MAP.json missing" in raw_text:
        family = "runtime_map_missing"
        title = "RUNTIME-MAP.json is missing from the phase root"
        actions.extend([
            "Browser/mobile discovery did not complete or wrote scan artifacts to a non-contract location.",
            "Ensure root `scan-*.json` and `RUNTIME-MAP.json` are written by the current review run.",
            f"Rerun `/vg:review {phase} --mode=full --force`; if discovery is intentionally skipped, do not expect full review PASS.",
        ])
    else:
        details.append(raw_text.strip()[:800] if raw_text.strip() else "No structured detail available.")
        actions.extend([
            "Open the referenced gate output and identify the missing artifact, failed validator, or stale evidence.",
            f"After fixing the cause, rerun `/vg:review {phase} --mode=full --force` unless the gate explicitly recommends another mode.",
        ])

    return {
        "gate_id": gate_id,
        "phase_dir": str(phase_dir),
        "block_family": family,
        "title": title,
        "details": details,
        "actions": actions,
    }


def render_md(diag: dict[str, Any]) -> str:
    lines = [
        "## Review Block Diagnostic",
        "",
        f"**Gate:** `{diag['gate_id']}`",
        f"**Family:** `{diag['block_family']}`",
        f"**Diagnosis:** {diag['title']}",
        "",
    ]
    details = diag.get("details") or []
    if details:
        lines.append("**Evidence:**")
        for item in details:
            lines.append(f"- {item}")
        lines.append("")
    lines.append("**Next actions:**")
    for idx, action in enumerate(diag.get("actions") or [], 1):
        lines.append(f"{idx}. {action}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate-id", required=True)
    ap.add_argument("--phase-dir", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-md")
    ap.add_argument("--out-json")
    args = ap.parse_args()

    payload, raw_text = _read_payload(Path(args.input))
    diag = diagnose(args.gate_id, Path(args.phase_dir), payload, raw_text)
    md = render_md(diag)
    if args.out_md:
        Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_md).write_text(md, encoding="utf-8")
    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(json.dumps(diag, indent=2, ensure_ascii=False), encoding="utf-8")
    if not args.out_md and not args.out_json:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
