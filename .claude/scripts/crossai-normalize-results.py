#!/usr/bin/env python3
"""Normalize CrossAI CLI outputs into valid XML artifacts.

External CLIs can fail before writing XML (auth, quota, TLS, unsupported
project hook config). This helper preserves those failures as structured
`verdict=inconclusive` XML so the pipeline can block or require override
without treating empty/malformed output as pass.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import mean
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

VALID_VERDICTS = {"pass", "flag", "block", "inconclusive"}

# v2.66.0 (#151): tls_self_signed MUST come before auth_missing because the
# Gemini cert error text contains "Error authenticating:" as a prefix and the
# auth_missing pattern would otherwise win, hiding the real CA-cert remedy.
# Pattern widened to match real-world strings: `self-signed certificate`,
# `certificate chain`, `SELF_SIGNED_CERT_IN_CHAIN`, `unable to verify the
# first certificate`, `SSL certificate problem`.
INFRA_PATTERNS: list[tuple[str, str]] = [
    (
        "tls_self_signed",
        r"self[_ -]?signed[_ -]?cert|SELF_SIGNED_CERT_IN_CHAIN|certificate chain"
        r"|unable to verify the first certificate|SSL certificate problem",
    ),
    ("auth_missing", r"no active credentials|error authenticating|authentication"),
    ("quota_or_limit", r"hit your limit|quota|rate limit|usage limit"),
    ("unsupported_hook_config", r"invalid hook event name|unsupported additionalContext"),
    ("timeout", r"timed out|timeout"),
    ("cli_missing", r"command not found|not found in PATH|no such file"),
]

# v2.66.0 (#151): Operator-actionable remedies. Surfaced inside the inconclusive
# verdict's <finding> text so a human running `/vg:scope` etc. immediately sees
# how to unblock the CLI without spelunking through stderr.
FAILURE_HINTS: dict[str, str] = {
    "tls_self_signed": (
        "TLS handshake failed (self-signed CA chain). On corp networks, "
        "set NODE_EXTRA_CA_CERTS=/path/to/corp-ca.pem before invoking the CLI, "
        "OR pass --insecure-skip-tls-verify if your CLI build supports it."
    ),
    "auth_missing": "Run the CLI's auth-login command (e.g. `gemini auth login`, `codex login`) to refresh credentials.",
    "quota_or_limit": "Provider quota exhausted. Wait for the rate-limit window OR switch to a different account/provider in vg.config.md.",
    "unsupported_hook_config": "CLI rejected a project hook config. Run from an isolated cwd OR remove the offending hook (see crossai-runner cwd isolation).",
    "timeout": "CLI did not return within the timeout window. Increase the per-CLI timeout in vg.config.md OR retry with a smaller context.",
    "cli_missing": "CLI binary not on PATH. Install it OR set the binary path explicitly in vg.config.md.",
}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _extract_xml(text: str) -> ET.Element | None:
    match = re.search(r"<crossai_review>.*?</crossai_review>", text, re.DOTALL)
    if not match:
        return None
    try:
        return ET.fromstring(match.group(0))
    except ET.ParseError:
        return None


def _field(root: ET.Element | None, name: str) -> str:
    if root is None:
        return ""
    child = root.find(name)
    return (child.text or "").strip() if child is not None else ""


def _score(root: ET.Element | None) -> float | None:
    text = _field(root, "score")
    match = re.match(r"^\s*(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    value = float(match.group(1))
    return value if 0 <= value <= 10 else None


def _classify_failure(text: str, exit_code: str) -> str:
    haystack = text.lower()
    for reason, pattern in INFRA_PATTERNS:
        if re.search(pattern.lower(), haystack, re.IGNORECASE):
            return reason
    if exit_code and exit_code not in {"0", ""}:
        return f"cli_exit_{exit_code}"
    return "malformed_output"


def _xml_doc(reviewer: str, verdict: str, score: float, findings: list[tuple[str, str]]) -> str:
    lines = [
        "<crossai_review>",
        f"  <reviewer>{escape(reviewer)}</reviewer>",
        f"  <verdict>{escape(verdict)}</verdict>",
        f"  <score>{score:g}</score>",
        "  <findings>",
    ]
    for severity, text in findings:
        lines.append(f'    <finding severity="{escape(severity)}">{escape(text)}</finding>')
    lines.extend(["  </findings>", "</crossai_review>", ""])
    return "\n".join(lines)


def _cli_names(output_dir: Path) -> list[str]:
    names = {p.name[len("result-"):-len(".exit")] for p in output_dir.glob("result-*.exit")}
    if not names:
        for p in output_dir.glob("result-*.xml"):
            name = p.name[len("result-"):-len(".xml")]
            if name.startswith("iteration-"):
                continue
            names.add(name)
    return sorted(names, key=str.lower)


def normalize(output_dir: Path, label: str, phase: str = "unknown") -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for name in _cli_names(output_dir):
        xml_path = output_dir / f"result-{name}.xml"
        err_path = output_dir / f"result-{name}.err"
        exit_path = output_dir / f"result-{name}.exit"
        xml_text = _read(xml_path)
        err_text = _read(err_path)
        exit_code = _read(exit_path).strip()
        root = _extract_xml(xml_text)
        verdict = _field(root, "verdict").lower()
        score = _score(root)
        reviewer = _field(root, "reviewer") or name

        valid = verdict in VALID_VERDICTS and score is not None and bool(reviewer.strip())
        if valid and verdict != "inconclusive":
            results.append(
                {
                    "name": name,
                    "status": "ok",
                    "verdict": verdict,
                    "score": score,
                    "reviewer": reviewer,
                    "exit_code": exit_code or "0",
                }
            )
            continue

        reason = verdict if verdict == "inconclusive" else _classify_failure(
            "\n".join([xml_text, err_text]), exit_code
        )
        if xml_text.strip() and root is None:
            raw_path = xml_path.with_suffix(xml_path.suffix + ".raw")
            if not raw_path.exists():
                raw_path.write_text(xml_text, encoding="utf-8")
        finding = f"{name} CrossAI CLI inconclusive: {reason}"
        # v2.66.0 (#151): prepend operator-actionable hint when reason is known.
        hint = FAILURE_HINTS.get(reason, "")
        if hint:
            finding = f"{finding}. HINT: {hint}"
        if err_text.strip():
            tail = " ".join(err_text.strip().splitlines()[-3:])[:500]
            finding = f"{finding}. stderr: {tail}"
        xml_path.write_text(
            _xml_doc(name, "inconclusive", 0, [("major", finding)]),
            encoding="utf-8",
        )
        results.append(
            {
                "name": name,
                "status": "inconclusive",
                "verdict": "inconclusive",
                "score": 0,
                "reviewer": name,
                "exit_code": exit_code or "missing",
                "reason": reason,
                "failure_hint": hint,
            }
        )

    ok = [r for r in results if r["status"] == "ok"]
    verdicts = [r["verdict"] for r in ok]
    if not results:
        aggregate_verdict = "inconclusive"
    elif not ok:
        aggregate_verdict = "inconclusive"
    elif verdicts.count("block") >= 2:
        aggregate_verdict = "block"
    elif "block" in verdicts or verdicts.count("flag") >= 2:
        aggregate_verdict = "flag"
    elif verdicts and all(v == "pass" for v in verdicts):
        aggregate_verdict = "pass"
    else:
        aggregate_verdict = "flag"

    aggregate_findings = []
    for r in results:
        if r["status"] == "inconclusive":
            aggregate_findings.append(
                ("major", f"{r['name']} did not produce a usable verdict ({r.get('reason', 'inconclusive')}).")
            )
    aggregate_score = mean([float(r["score"]) for r in ok]) if ok else 0
    aggregate_xml = _xml_doc(
        "VGFlow CrossAI Aggregator",
        aggregate_verdict,
        aggregate_score,
        aggregate_findings,
    )
    aggregate_xml = aggregate_xml.replace(
        "</findings>",
        f"</findings>\n  <ok_count>{len(ok)}</ok_count>\n  <total_clis>{len(results)}</total_clis>\n  <phase>{escape(phase)}</phase>",
    )
    (output_dir / f"{label}.xml").write_text(aggregate_xml, encoding="utf-8")

    return {
        "label": label,
        "phase": phase,
        "verdict": aggregate_verdict,
        "ok_count": len(ok),
        "total_clis": len(results),
        "results": results,
        "aggregate": str(output_dir / f"{label}.xml"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--phase", default="unknown")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = normalize(Path(args.output_dir), args.label, args.phase)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"CrossAI normalized: verdict={report['verdict']} "
            f"ok={report['ok_count']}/{report['total_clis']} "
            f"aggregate={report['aggregate']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
