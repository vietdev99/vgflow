#!/usr/bin/env python3
"""
Validator: mutation-layers.py

B12.1 (v2.4 hardening, 2026-04-23): extend Rule R7 (mutation 3-layer
verify) to ALL mutation specs — generated + hand-written — not just
generated ones.

Previously R7 only checked console assertion on codegen output. Hand-
written `*.spec.ts` files with mutation test names (`create X`,
`update Y`, `submit Z`) could skip layer verification entirely and
still PASS the test pipeline — regression holes invisible until real
users saw ghost-save / phantom-failure bugs.

The 3 layers per mutation spec:
  1. Toast/status assertion  — user sees confirmation
  2. Network settle          — wait for request to complete
  3. Persist verify          — reload/revisit page, data still there

Any missing layer → BLOCK with specific hint per missing layer.

Override: `--allow-missing-mutation-verify` in test command args
→ logged to override-debt, non-blocking.

Usage:
  mutation-layers.py --phase <N>

Exit codes:
  0 PASS or WARN
  1 BLOCK (one or more mutation specs missing layer)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import Evidence, Output, timer, emit_and_exit, find_phase_dir  # noqa: E402
from _i18n import t  # noqa: E402

REPO_ROOT = Path(os.environ.get("VG_REPO_ROOT") or os.getcwd()).resolve()

# Mutation keyword detection — match test/it('create X', async ...)
# Also matches Vietnamese mutation verbs for mixed-locale projects
MUTATION_NAME_RE = re.compile(
    r"""(?:test|it)\s*\(\s*['"`]
        ([^'"`]*(?:
            create|update|delete|submit|save|send|upload|insert|patch|remove|
            post|put|edit|add\s|tạo|sửa|xoá|xóa|gửi|upload|cập\s*nhật
        )[^'"`]*)
    ['"`]""",
    re.IGNORECASE | re.VERBOSE,
)

# Layer 1: Toast/status/success feedback
TOAST_PATTERNS = [
    r"getByRole\s*\(\s*['\"`](?:status|alert)['\"`]",
    r"getByText\s*\(\s*/(?:success|saved|created|updated|deleted|submitted|gửi\s*thành|lưu\s*thành|thành\s*công)",
    r"waitForSelector\s*\(\s*['\"`][^'\"`]*(?:toast|notification|snackbar|alert)",
    r"toHaveText\s*\(\s*/(?:success|saved|created)",
    # Config-agnostic role/variant fallback
    r"role\s*=\s*['\"]status['\"]",
    # page.locator('[role=status], [data-testid*=success], .success-banner')
    # form (PrintwayV3 dogfound 2026-07-16) — codegen emits CSS-attr locators
    # not getByRole for the toast/success assertion.
    r"locator\s*\(\s*['\"`][^'\"`]*(?:role=[\"']?status|data-testid\*?=[\"']?success|success-banner|toast-success)",
]

# Layer 2: Network settle — request fully completed before asserting
NETWORK_PATTERNS = [
    r"waitForLoadState\s*\(\s*['\"`]networkidle['\"`]",
    r"waitForResponse\s*\(",
    r"waitForRequest\s*\(",
    # Explicit wait on fetch/xhr spy
    r"await\s+apiCall",
    # Some projects export helpers (keep flexible)
    r"waitForApiSettle\s*\(",
    # API-contract specs assert the response status directly.
    r"\.status\(\)\s*\)?\.?(?:toBeLessThan|toBe)\s*\(\s*(?:400|2\d\d)",
    r"expect\s*\([^)]*\.status\(\)",
]

# Layer 3: Persist verify — reload or navigate back, value still present
PERSIST_PATTERNS = [
    r"\breload\s*\(",
    r"\bgoto\s*\(",
    r"page\.goto\s*\(",
    r"navigate\s*\(",
    # Or explicit second query after initial save:
    # if spec does initial getByText(X) then clicks edit, the persist
    # layer is the SECOND getByText(X) reading from server-refreshed data
    r"persistVerify\s*\(",
    # API-contract specs (no rendered UI — discovery-only phases) verify
    # persistence by RE-READING the server: request.get/fetch after the
    # mutation. PrintwayV3 dogfound 2026-07-16 (P6.1 API-level lifecycle
    # specs). Recognize a follow-up GET as the persist layer.
    r"request\.get\s*\(",
    r"\.get\s*\(\s*apiUrl",
]


# ─────────────────────────────────────────────────────────────────────────

_ARROW_BODY_RE = re.compile(r"=>\s*\{")


def _test_body(content: str, match: re.Match) -> str:
    """Extract test body. Skip past arrow fn signature + destructuring
    `async ({ page }) => {` — start counting only at the arrow body `{`."""
    start = match.end()
    # Find the arrow-body opening `{` — skip destructured params noise
    arrow = _ARROW_BODY_RE.search(content, pos=start)
    if arrow:
        body_start = arrow.end()  # position AFTER the `{`
    else:
        # Non-arrow: direct function(...) { body } — find first `{` after params
        paren_end = content.find(")", start)
        if paren_end < 0:
            return content[start:start + 2000]
        brace = content.find("{", paren_end)
        if brace < 0:
            return content[start:start + 2000]
        body_start = brace + 1

    depth = 1  # we're already inside the body's opening brace
    i = body_start
    in_string: str | None = None
    while i < len(content):
        ch = content[i]
        prev = content[i-1] if i > 0 else ""
        if in_string:
            if ch == in_string and prev != "\\":
                in_string = None
        elif ch in "\"'`":
            in_string = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return content[body_start:i]
        i += 1
    # Fallback — truncate at next test or 2000 chars
    next_test = MUTATION_NAME_RE.search(content, pos=body_start)
    end = next_test.start() if next_test else min(len(content), body_start + 2000)
    return content[body_start:end]


def _scan_spec(path: Path) -> list[dict]:
    """Return violations: {spec_file, test_name, missing_layers[], line}."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    violations: list[dict] = []

    for m in MUTATION_NAME_RE.finditer(text):
        test_name = m.group(1).strip()
        line_num = text.count("\n", 0, m.start()) + 1
        body = _test_body(text, m)

        has_toast = any(re.search(p, body, re.IGNORECASE) for p in TOAST_PATTERNS)
        has_network = any(re.search(p, body, re.IGNORECASE) for p in NETWORK_PATTERNS)
        has_persist = any(re.search(p, body, re.IGNORECASE) for p in PERSIST_PATTERNS)

        # API-contract vs DOM-mutation classification (PrintwayV3 dogfound
        # 2026-07-16). A test that drives the mutation via Playwright's
        # request context (request.post/put/patch/delete or an apiUrl() call)
        # and NEVER touches page.click/fill/getByRole is an API-level spec:
        # there is NO rendered UI, so a DOM "toast" is impossible and MUST NOT
        # be required. For those, the success feedback layer = asserting the
        # response status/body, which is already covered by the network layer.
        # DOM specs keep the full toast+network+persist requirement.
        # Negative/edge mutation tests (PrintwayV3 dogfound 2026-07-16): a test
        # that EXPECTS the mutation to be REJECTED (asserts 4xx, an error-code
        # envelope, or is test.skip) has NO saved state — persist/toast/network
        # success-layers are semantically N/A. Detect and exempt.
        is_negative = bool(
            re.search(r"toBe(?:GreaterThanOrEqual)?\s*\(\s*4\d\d\s*\)", body)
            or re.search(r"status\(\)\s*\)?\.?toBe\s*\(\s*4\d\d", body)
            or re.search(r"\b(?:FORBIDDEN|TEAM_DEACTIVATED|STALE_ASSIGNMENT_STATE|STORE_ALREADY_ASSIGNED|MEMBER_INVITED|VALIDATION_FAILED|CONFLICT|_DENIED|NOT_FOUND|UNAUTHORIZED)\b", body)
            or re.search(r"toBeGreaterThanOrEqual\s*\(\s*400", body)
            or re.search(r"test\.skip\s*\(\s*true", body)
        )

        is_api_level = bool(
            re.search(r"request\.(?:post|put|patch|delete)\s*\(", body, re.IGNORECASE)
            or re.search(r"\.(?:post|put|patch|delete)\s*\(\s*apiUrl", body, re.IGNORECASE)
        ) and not re.search(r"page\.(?:click|fill|getByRole|getByText|goto)\s*\(", body, re.IGNORECASE)

        missing: list[str] = []
        if not is_negative:
            if not has_toast and not is_api_level:
                missing.append("toast")
            if not has_network:
                missing.append("network")
            if not has_persist:
                missing.append("persist")

        if missing:
            violations.append({
                "spec": path.as_posix(),
                "test": test_name[:80],
                "line": line_num,
                "missing": missing,
            })
    return violations


def _collect_specs(
    phase_dir: Path | None,
    cli_override: bool,
    phase: str | None = None,
) -> list[Path]:
    """Look at the phase generated tests dir + e2e dir.

    PHASE-SCOPING (PrintwayV3 dogfound 2026-07-16): previously globbed the
    ENTIRE apps/*/e2e + tests/e2e tree regardless of --phase, so a phase with
    clean specs was BLOCKed by pre-existing shallow specs from OTHER phases
    (6.1 blocked by apps/web/e2e/generated/{3.2,6,4.7}). When `phase` is known,
    restrict e2e candidates to files whose path has a segment == phase, or a
    `<phase>-`/`<phase>.` filename prefix. Full-tree only when phase is None.
    """
    candidates: list[Path] = []
    if phase_dir:
        gen = phase_dir / "generated-tests"
        if gen.is_dir():
            candidates += list(gen.rglob("*.spec.ts"))
        candidates += list(phase_dir.rglob("*.spec.ts"))

    def _matches_phase(p: Path) -> bool:
        if not phase:
            return True
        pl = phase.lower()
        if pl in {s.lower() for s in p.parts}:
            return True
        name = p.name.lower()
        return name.startswith(pl + "-") or name.startswith(pl + ".")

    for pat in ("apps/web/e2e", "apps/*/e2e", "tests/e2e"):
        for d in REPO_ROOT.glob(pat):
            if d.is_dir():
                for f in d.rglob("*.spec.ts"):
                    if _matches_phase(f):
                        candidates.append(f)
    seen: set[Path] = set()
    uniq: list[Path] = []
    for c in candidates:
        rp = c.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq.append(c)
    return uniq


# ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument(
        "--allow-missing",
        action="store_true",
        help="log violations as debt instead of blocking (maps to --allow-missing-mutation-verify)",
    )
    args = ap.parse_args()

    out = Output(validator="mutation-layers")
    with timer(out):
        phase_dir = find_phase_dir(args.phase)
        specs = _collect_specs(phase_dir, args.allow_missing, args.phase)
        if not specs:
            emit_and_exit(out)

        all_violations: list[dict] = []
        for spec in specs:
            all_violations.extend(_scan_spec(spec))

        if all_violations:
            # Build specific hint mentioning missing layers per spec
            sample_parts = []
            for v in all_violations[:10]:
                sample_parts.append(
                    f"{v['spec']}:{v['line']} [{v['test'][:40]}...] "
                    f"missing: {', '.join(v['missing'])}"
                )
            if args.allow_missing:
                out.warn(Evidence(
                    type="mutation_layers_missing",
                    message=t(
                        "mutation_layers.missing.message",
                        count=len(all_violations),
                    ),
                    actual="; ".join(sample_parts),
                    fix_hint=t("mutation_layers.missing.fix_hint"),
                ))
            else:
                out.add(Evidence(
                    type="mutation_layers_missing",
                    message=t(
                        "mutation_layers.missing.message",
                        count=len(all_violations),
                    ),
                    actual="; ".join(sample_parts),
                    fix_hint=t("mutation_layers.missing.fix_hint"),
                ))

    emit_and_exit(out)


if __name__ == "__main__":
    main()
