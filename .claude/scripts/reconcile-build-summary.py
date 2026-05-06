#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


START_MARKER = "<!-- VG:POST-BUILD-RECONCILE:START -->"
END_MARKER = "<!-- VG:POST-BUILD-RECONCILE:END -->"


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _iter_fix_results(evidence_dir: Path) -> list[dict]:
    classified = evidence_dir / "classified"
    if not classified.exists():
        return []

    results: list[dict] = []
    for path in sorted(classified.glob("in-scope.*.fixed.json")):
        data = _load_json(path)
        if not data:
            continue
        warning_id = path.name
        if warning_id.startswith("in-scope."):
            warning_id = warning_id[len("in-scope."):]
        if warning_id.endswith(".fixed.json"):
            warning_id = warning_id[: -len(".fixed.json")]
        status = str(data.get("status") or "UNKNOWN").upper()
        results.append({
            "warning_id": warning_id,
            "status": status,
            "summary": str(data.get("summary") or "").strip(),
            "iterations": data.get("iterations"),
            "repair_packet": data.get("repair_packet"),
            "path": str(path),
        })
    return results


def _render_result_lines(results: list[dict], statuses: set[str], empty_line: str) -> list[str]:
    lines: list[str] = []
    for result in results:
        if result["status"] not in statuses:
            continue
        detail = result["summary"] or "no summary"
        iterations = result.get("iterations")
        suffix = ""
        if isinstance(iterations, int):
            suffix = f" (attempts={iterations})"
        lines.append(
            f"- `{result['warning_id']}` - {result['status']}{suffix}: {detail}"
        )
    if not lines:
        lines.append(empty_line)
    return lines


def _replace_or_insert_section(text: str, heading: str, body_lines: list[str]) -> str:
    block = f"## {heading}\n\n" + "\n".join(body_lines).rstrip() + "\n\n"
    marker = f"## {heading}\n"
    start = text.find(marker)
    if start >= 0:
        next_heading = text.find("\n## ", start + len(marker))
        next_reconcile = text.find("\n" + START_MARKER, start + len(marker))
        candidates = [idx for idx in (next_heading, next_reconcile) if idx >= 0]
        if not candidates:
            return text[:start] + block
        boundary = min(candidates)
        return text[:start] + block + text[boundary + 1 :]

    next_steps = text.find("\n## Next steps")
    if next_steps >= 0:
        return text[: next_steps + 1] + block + text[next_steps + 1 :]
    return text.rstrip() + "\n\n" + block


def _replace_reconcile_block(text: str, block: str) -> str:
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start >= 0 and end >= 0 and end > start:
        end += len(END_MARKER)
        replacement = block.rstrip() + "\n"
        if end < len(text) and text[end] == "\n":
            end += 1
        return text[:start] + replacement + text[end:]

    next_steps = text.find("\n## Next steps")
    if next_steps >= 0:
        return text[: next_steps + 1] + block.rstrip() + "\n\n" + text[next_steps + 1 :]
    return text.rstrip() + "\n\n" + block.rstrip() + "\n"


def _build_reconcile_block(
    *,
    results: list[dict],
    pre_test_report: Path | None,
    now_iso: str,
    summary_path: Path,
) -> str:
    fixed = [r for r in results if r["status"] == "FIXED"]
    unresolved = [r for r in results if r["status"] != "FIXED"]

    lines = [
        START_MARKER,
        "## Post-build reconciliation",
        "",
        f"- Reconciled at: {now_iso}",
        "- Current build truth in this section supersedes stale gate notes above when the same warning id appears below.",
        f"- Summary file: `{summary_path.name}`",
    ]
    if pre_test_report and pre_test_report.exists():
        lines.append(f"- Pre-test artifact: `{pre_test_report.name}` present")
    else:
        lines.append("- Pre-test artifact: not present")
    lines.append("")
    lines.append("### Fix-loop results")
    if fixed:
        for line in _render_result_lines(results, {"FIXED"}, "None."):
            lines.append(line)
    else:
        lines.append("- No FIXED in-scope warning result manifests detected.")
    lines.append("")
    lines.append("### Remaining warnings")
    if unresolved:
        for line in _render_result_lines(results, {"UNRESOLVED", "OUT_OF_SCOPE", "UNKNOWN"}, "None."):
            lines.append(line)
    else:
        lines.append("- None after step 5.5 reconciliation.")
    lines.append(END_MARKER)
    return "\n".join(lines)


def reconcile_summary(
    *,
    summary_path: Path,
    evidence_dir: Path,
    pre_test_report: Path | None,
    now_iso: str,
) -> tuple[bool, str]:
    if not summary_path.exists():
        return False, f"summary missing: {summary_path}"

    text = summary_path.read_text(encoding="utf-8")
    results = _iter_fix_results(evidence_dir)

    updated = text
    if results and "## Gates failed" in updated:
        updated = _replace_or_insert_section(
            updated,
            "Gates failed",
            _render_result_lines(
                results,
                {"UNRESOLVED", "OUT_OF_SCOPE", "UNKNOWN"},
                "None after step 5.5 reconciliation.",
            ),
        )
    if results and "## Gaps closed" in updated:
        updated = _replace_or_insert_section(
            updated,
            "Gaps closed",
            _render_result_lines(
                results,
                {"FIXED"},
                "None after step 5.5 reconciliation.",
            ),
        )

    if results or (pre_test_report and pre_test_report.exists()):
        block = _build_reconcile_block(
            results=results,
            pre_test_report=pre_test_report,
            now_iso=now_iso,
            summary_path=summary_path,
        )
        updated = _replace_reconcile_block(updated, block)

    if updated == text:
        return False, "unchanged"

    summary_path.write_text(updated, encoding="utf-8")
    return True, "updated"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-dir", required=True)
    parser.add_argument("--summary", default=None)
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--pre-test-report", default=None)
    parser.add_argument("--now-iso", default=None)
    args = parser.parse_args()

    phase_dir = Path(args.phase_dir)
    summary_path = Path(args.summary) if args.summary else (phase_dir / "SUMMARY.md")
    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else (phase_dir / ".evidence")
    pre_test_report = Path(args.pre_test_report) if args.pre_test_report else (phase_dir / "PRE-TEST-REPORT.md")
    now_iso = args.now_iso or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    changed, message = reconcile_summary(
        summary_path=summary_path,
        evidence_dir=evidence_dir,
        pre_test_report=pre_test_report,
        now_iso=now_iso,
    )
    print(message)
    return 0 if changed or message == "unchanged" else 1


if __name__ == "__main__":
    raise SystemExit(main())
