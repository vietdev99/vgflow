#!/usr/bin/env python3
"""Spawn Diagnostic L2 subagent (RFC v9 PR-D3 stub-3 fix).

When block-resolver L1 inline auto-fix candidates exhaust, spawn a
provider-native diagnostic subagent in an isolated context window to:
1. Receive gate evidence + nearby file snippets.
2. Return structured JSON with diagnosis + proposed_fix + confidence.

Runtime adapter:
- Claude/unknown runtime invokes `claude --model haiku -p` by default.
- Codex runtime invokes `codex exec --sandbox read-only` by default.
- `VG_DIAGNOSTIC_L2_CLI` still overrides both paths.

Output (stdout): single JSON line:
  {"proposal_id": "l2-{epoch}-{rand6}", "confidence": 0.85, "decision_pending": true}

Caller (block-resolver bash) reads proposal_id, invokes
block_resolve_l3_single_advisory with the confidence. The orchestrator then
uses a provider-native user prompt: AskUserQuestion on Claude, main-thread
prompt/closest Codex UI on Codex.

Usage:
  scripts/spawn-diagnostic-l2.py \\
    --gate-id missing-evidence \\
    --block-family provenance \\
    --phase-dir .vg/phases/03.2-... \\
    --evidence-json '{"goal":"G-10","step_idx":2}' \\
    --gate-context "Mutation step at G-10/step[2] missing evidence.source"

Exit codes:
  0 — proposal written; proposal_id on stdout
  1 — subagent failed (CLI error, parse error, auth, timeout)
  2 — arg error
"""
from __future__ import annotations

import argparse
import json
import re
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime.diagnostic_l2 import (  # noqa: E402
    L2Proposal,
    make_proposal,
    write_proposal,
)


PROMPT_TEMPLATE = """You are a Diagnostic L2 architect for a software workflow tool.

A gate failed in the workflow. Layer 1 (cheap auto-fix) couldn't resolve it.
Your job is to read the gate evidence and propose ONE concrete fix.

## Gate
ID: {gate_id}
Family: {block_family}

## Context
{gate_context}

## Evidence
{evidence_json}

## Output requirements

Respond with EXACTLY one JSON object on a single line, no other text:

{{"diagnosis": "<one sentence — what went wrong, in plain prose>", "proposed_fix": "<one specific actionable fix — a command, a code change, or a config edit>", "confidence": <float 0.0..1.0>}}

Rules:
- diagnosis must reference the gate evidence specifically (not generic).
- proposed_fix must be ONE thing the user/operator can execute, not a menu.
- confidence reflects how certain you are this fix resolves the gate:
  - 0.9+ if the fix is mechanical (e.g., add a missing field).
  - 0.7-0.9 if you've inferred the cause but not verified.
  - <0.7 if you're guessing — the orchestrator will fall through to
    multi-option L3 in that case so honesty matters.
- DO NOT wrap output in code fences. DO NOT add prose before/after the JSON.
"""


def _default_cli() -> list[str]:
    """Return CLI args for the default subagent invocation.

    Configurable via VG_DIAGNOSTIC_L2_CLI env var (e.g.,
    `claude --model haiku -p` or `codex exec --model gpt-5.5`).
    """
    raw = os.environ.get("VG_DIAGNOSTIC_L2_CLI")
    if raw:
        return shlex.split(raw)

    runtime = _detect_runtime()
    if runtime == "codex":
        cli = ["codex", "exec", "--sandbox", "read-only"]
        model = os.environ.get("VG_CODEX_MODEL_SCANNER", "").strip()
        if model:
            cli.extend(["--model", model])
        return cli

    return ["claude", "--model", "haiku", "-p"]


def _detect_runtime() -> str:
    raw = (os.environ.get("VG_RUNTIME") or os.environ.get("VG_PROVIDER") or "").lower()
    if raw.startswith("codex"):
        return "codex"
    if raw.startswith("claude"):
        return "claude"
    if any(os.environ.get(k) for k in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDE_PROJECT_DIR")):
        return "claude"
    if any(os.environ.get(k) for k in ("CODEX_SANDBOX", "CODEX_CLI_SANDBOX", "CODEX_HOME")):
        return "codex"
    return "claude"


# Codex-R4-HIGH-4: scrub env so spawned CLI does NOT inherit secrets.
# Allowlist + project-specific passthrough via VG_DIAGNOSTIC_L2_ENV_PASSTHROUGH.
_DEFAULT_ENV_ALLOWLIST = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "LANG", "LC_ALL",
    "TMPDIR", "PWD",
    # CLI-specific tokens that the spawned CLI itself needs (NOT the parent's
    # vendor secrets — claude/codex/gemini handle their own auth via OS keychain
    # or per-CLI config files, NOT env vars by default).
    "CLAUDE_HOME", "CODEX_HOME", "GEMINI_HOME",
)

# NB: no word boundaries — "auth_token", "api_key" must match too.
_REDACT_KEYS_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|authorization|"
    r"bearer|access[_-]?key|private[_-]?key|cookie|credential)"
)


def _scrubbed_env() -> dict[str, str]:
    """Return env dict with allowlist + opt-in passthrough."""
    allow = set(_DEFAULT_ENV_ALLOWLIST)
    passthrough = os.environ.get("VG_DIAGNOSTIC_L2_ENV_PASSTHROUGH", "")
    for k in passthrough.split(","):
        k = k.strip()
        if k:
            allow.add(k)
    return {k: v for k, v in os.environ.items() if k in allow}


def _is_secret_name_string(value: object) -> bool:
    """True if `value` is a string that looks like a secret-bearing field name.

    Catches the {name: "Authorization", value: "Bearer …"} shape — the
    name field's VALUE itself is a secret-related label, signaling that
    sibling `value` is the actual secret.
    """
    if not isinstance(value, str):
        return False
    return bool(_REDACT_KEYS_RE.search(value))


def _redact_secrets(value):
    """Recursively redact values whose KEY name matches secret patterns.

    Codex-R5-HIGH-1 fix: also handle adjacent-key shape. When a dict has
    a `name` (or `key`/`field`) whose VALUE matches a secret pattern,
    AND a sibling `value` (or `data`/`val`) field, redact the sibling.
    Common scanner shape: {name: "Authorization", value: "Bearer …"}.
    """
    if isinstance(value, dict):
        # Detect adjacent-key shape first
        name_field_secret = False
        value_fields: set = set()
        for k in value:
            kl = str(k).lower()
            if kl in {"name", "key", "field", "header"}:
                if _is_secret_name_string(value[k]):
                    name_field_secret = True
            if kl in {"value", "val", "data", "content"}:
                value_fields.add(k)
        out = {}
        for k, v in value.items():
            if _REDACT_KEYS_RE.search(str(k)):
                out[k] = "[REDACTED]"
            elif name_field_secret and k in value_fields:
                # Codex-R6-HIGH-1 fix: redact ALL value-like siblings,
                # not just the first one. Previous code only caught the
                # first match — `{name: Authorization, content: public,
                # value: Bearer SECRET}` would leak `value`.
                out[k] = "[REDACTED]"
            else:
                out[k] = _redact_secrets(v)
        return out
    if isinstance(value, list):
        return [_redact_secrets(v) for v in value]
    return value


def invoke_subagent(
    prompt: str,
    *,
    cli_args: list[str] | None = None,
    timeout_s: int = 60,
) -> dict:
    """Spawn the subagent CLI; return parsed structured JSON.

    Raises RuntimeError on subprocess failure or parse error.
    """
    cli = cli_args if cli_args is not None else _default_cli()
    try:
        proc = subprocess.run(
            cli + [prompt],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=_scrubbed_env(),  # Codex-R4-HIGH-4: scrubbed env
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"subagent timed out after {timeout_s}s") from e
    except FileNotFoundError as e:
        raise RuntimeError(
            f"subagent CLI '{cli[0]}' not in PATH — set VG_DIAGNOSTIC_L2_CLI "
            f"to override (e.g., 'codex exec -m gpt-5.5')"
        ) from e
    if proc.returncode != 0:
        raise RuntimeError(
            f"subagent exited {proc.returncode}: {proc.stderr[:300]}"
        )

    # Parse JSON line from stdout — model may emit prose around it; be tolerant.
    out = proc.stdout.strip()
    if not out:
        raise RuntimeError("subagent emitted empty stdout")

    # Try whole-string JSON first
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        pass

    # Fall back: find JSON object substring
    start = out.find("{")
    end = out.rfind("}")
    if start >= 0 and end > start:
        candidate = out[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    raise RuntimeError(f"subagent stdout not valid JSON: {out[:300]!r}")


def validate_subagent_response(data: dict) -> dict:
    """Coerce + validate the subagent's structured response."""
    required = {"diagnosis", "proposed_fix", "confidence"}
    missing = required - set(data)
    if missing:
        raise RuntimeError(f"subagent response missing fields: {sorted(missing)}")
    diag = str(data["diagnosis"]).strip()
    if len(diag) < 10:
        raise RuntimeError(f"diagnosis too short ({len(diag)} chars)")
    fix = str(data["proposed_fix"]).strip()
    if len(fix) < 10:
        raise RuntimeError(f"proposed_fix too short ({len(fix)} chars)")
    try:
        conf = float(data["confidence"])
    except (TypeError, ValueError) as e:
        raise RuntimeError(f"confidence not numeric: {data['confidence']!r}") from e
    if not (0.0 <= conf <= 1.0):
        raise RuntimeError(f"confidence out of range [0,1]: {conf}")
    return {"diagnosis": diag, "proposed_fix": fix, "confidence": conf}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate-id", required=True)
    ap.add_argument("--block-family", required=True)
    ap.add_argument("--phase-dir", required=True,
                    help="Absolute path to phase dir (where .l2-proposals lives)")
    ap.add_argument("--gate-context", default="",
                    help="One-paragraph human description of the gate failure")
    ap.add_argument("--evidence-json", default="{}",
                    help="JSON-encoded evidence dict")
    ap.add_argument("--cli", default=None,
                    help="Override CLI args (defaults to VG_DIAGNOSTIC_L2_CLI or 'claude --model haiku -p')")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true",
                    help="Skip subagent spawn; emit a stub proposal for testing")
    args = ap.parse_args()

    phase_dir = Path(args.phase_dir).resolve()
    if not phase_dir.exists():
        print(json.dumps({"error": f"phase_dir not found: {phase_dir}"}))
        return 2

    try:
        evidence = json.loads(args.evidence_json)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"--evidence-json parse: {e}"}))
        return 2
    if not isinstance(evidence, dict):
        print(json.dumps({"error": "--evidence-json must encode an object"}))
        return 2

    if args.dry_run:
        # Emit a stub proposal without invoking subagent — useful for tests
        # and for human-in-the-loop fallbacks where the CLI is unavailable.
        proposal = make_proposal(
            gate_id=args.gate_id,
            block_family=args.block_family,
            evidence_in=evidence,
            diagnosis=f"[dry-run] would diagnose: {args.gate_context[:120]}",
            proposed_fix="[dry-run] would propose a fix; re-run without --dry-run for live diagnosis",
            confidence=0.0,
        )
        write_proposal(phase_dir, proposal)
        print(json.dumps({
            "proposal_id": proposal.proposal_id,
            "confidence": proposal.confidence,
            "decision_pending": True,
            "dry_run": True,
        }))
        return 0

    # Codex-R4-HIGH-4: redact secret-keyed evidence fields before sending
    # to the subagent. Keeps the diagnostic context useful but blocks
    # accidental token leaks.
    redacted_evidence = _redact_secrets(evidence)
    prompt = PROMPT_TEMPLATE.format(
        gate_id=args.gate_id,
        block_family=args.block_family,
        gate_context=args.gate_context or "(no context provided)",
        evidence_json=json.dumps(redacted_evidence, indent=2, ensure_ascii=False),
    )

    cli_args = shlex.split(args.cli) if args.cli else None
    try:
        raw = invoke_subagent(prompt, cli_args=cli_args, timeout_s=args.timeout)
        validated = validate_subagent_response(raw)
    except RuntimeError as e:
        print(json.dumps({"error": str(e)}))
        return 1

    proposal = make_proposal(
        gate_id=args.gate_id,
        block_family=args.block_family,
        evidence_in=evidence,
        diagnosis=validated["diagnosis"],
        proposed_fix=validated["proposed_fix"],
        confidence=validated["confidence"],
    )
    write_proposal(phase_dir, proposal)

    print(json.dumps({
        "proposal_id": proposal.proposal_id,
        "confidence": proposal.confidence,
        "decision_pending": True,
        "diagnosis": proposal.diagnosis,
        "proposed_fix": proposal.proposed_fix,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
