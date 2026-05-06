# Task 06: Implement build-legacy orchestration parity in `crossai_loop.py`

**Goal:** Fill in `run_loop()` body by extracting the CURRENT build behavior into the library without semantic drift. That means parallel Codex+Gemini execution, current build events, current `crossai-build-verify` output path, current findings JSON shape, current parse/error semantics, and brief handling that still receives the same build context as before refactor.

**Files:**
- Modify: `scripts/lib/crossai_loop.py` (replace `NotImplementedError` body)
- Mirror: `.claude/scripts/lib/crossai_loop.py`
- Test: `scripts/tests/test_crossai_loop_library.py` (extend)

---

- [ ] **Step 1: Append failing tests**

Append to `scripts/tests/test_crossai_loop_library.py`:

```python


# ---- Task 06 tests ----


import json
from unittest.mock import patch
from crossai_config import CLISpec, StageConfig


def _stage_with_one_primary(tmp_path):
    return StageConfig(
        stage="build",
        primary_clis=[CLISpec(
            name="MockCLI",
            command="echo {prompt}",
            label="Mock",
            role="primary",
        )],
        verifier_cli=None,
    )


def test_run_loop_invokes_primary_clean_verdict(tmp_path, monkeypatch):
    """Brief packer returns text → CLI invocation produces PASS XML →
    parser returns CLEAN exit code."""
    from crossai_loop import run_loop, EXIT_CLEAN

    monkeypatch.chdir(tmp_path)
    phase_dir = tmp_path / ".vg" / "phases" / "test-4.2"
    phase_dir.mkdir(parents=True)

    def packer(pd, phase_num, it, max_it):
        return f"# Brief for {phase_num} iter {it}/{max_it}"

    cfg = _stage_with_one_primary(tmp_path)

    # Mock subprocess invocation
    with patch("crossai_loop._invoke_cli") as mock_invoke:
        mock_invoke.return_value = (
            0,
            "<crossai-verdict><verdict>PASS</verdict>"
            "<findings></findings></crossai-verdict>",
        )
        rc = run_loop(
            phase="4.2", iteration=1,
            brief_packer=packer, stage_config=cfg,
            out_dir=phase_dir / "build-crossai-verify",
        )

    assert rc == EXIT_CLEAN


def test_run_loop_writes_brief_and_raw_output(tmp_path, monkeypatch):
    """Brief + raw CLI output written to out_dir."""
    from crossai_loop import run_loop

    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    def packer(pd, phase_num, it, max_it):
        return "# brief content"

    cfg = _stage_with_one_primary(tmp_path)

    with patch("crossai_loop._invoke_cli") as mock_invoke:
        mock_invoke.return_value = (
            0,
            "<crossai-verdict><verdict>PASS</verdict>"
            "<findings></findings></crossai-verdict>",
        )
        run_loop(phase="4.2", iteration=1, brief_packer=packer,
                  stage_config=cfg, out_dir=out_dir)

    assert (out_dir / "BRIEF-iter1.md").read_text() == "# brief content"
    assert (out_dir / "MockCLI-iter1.md").exists()


def test_run_loop_blocks_found_returns_exit_1(tmp_path, monkeypatch):
    """CLI returns BLOCK findings → EXIT_BLOCKS_FOUND."""
    from crossai_loop import run_loop, EXIT_BLOCKS_FOUND

    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    def packer(pd, p, i, m):
        return "brief"

    cfg = _stage_with_one_primary(tmp_path)
    with patch("crossai_loop._invoke_cli") as mock_invoke:
        mock_invoke.return_value = (
            0,
            "<crossai-verdict><verdict>FAIL</verdict>"
            "<findings><finding severity=\"BLOCK\">"
            "<message>missing endpoint /foo</message>"
            "</finding></findings></crossai-verdict>",
        )
        rc = run_loop(phase="4.2", iteration=1, brief_packer=packer,
                      stage_config=cfg, out_dir=out_dir)

    assert rc == EXIT_BLOCKS_FOUND
    findings_path = out_dir / "findings-iter1.json"
    assert findings_path.exists()
    findings = json.loads(findings_path.read_text())
    assert isinstance(findings, dict) and "findings" in findings
    assert any(f.get("severity") == "BLOCK" for f in findings["findings"])


def test_run_loop_cli_subprocess_failure_returns_exit_2(tmp_path,
                                                        monkeypatch):
    """CLI returns non-zero rc → EXIT_INFRA_FAIL."""
    from crossai_loop import run_loop, EXIT_INFRA_FAIL

    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    def packer(pd, p, i, m):
        return "brief"

    cfg = _stage_with_one_primary(tmp_path)
    with patch("crossai_loop._invoke_cli") as mock_invoke:
        mock_invoke.return_value = (1, "stderr: network timeout")
        rc = run_loop(phase="4.2", iteration=1, brief_packer=packer,
                      stage_config=cfg, out_dir=out_dir)

    assert rc == EXIT_INFRA_FAIL


def test_run_loop_default_out_dir(tmp_path, monkeypatch):
    """When out_dir is None, default to
    <phase_dir>/<stage>-crossai-verify/."""
    from crossai_loop import run_loop

    monkeypatch.chdir(tmp_path)
    # Stage minimal phase dir layout
    (tmp_path / ".vg/phases/04.2-test").mkdir(parents=True)

    def packer(pd, p, i, m):
        return "brief"

    cfg = _stage_with_one_primary(tmp_path)

    with patch("crossai_loop._invoke_cli") as mock_invoke, \
         patch("crossai_loop._find_phase_dir") as mock_find:
        mock_find.return_value = tmp_path / ".vg/phases/04.2-test"
        mock_invoke.return_value = (
            0,
            "<crossai-verdict><verdict>PASS</verdict>"
            "<findings></findings></crossai-verdict>",
        )
        run_loop(phase="4.2", iteration=1, brief_packer=packer,
                  stage_config=cfg, out_dir=None)

    expected_out = tmp_path / ".vg/phases/04.2-test/build-crossai-verify"
    assert expected_out.exists()
    assert (expected_out / "BRIEF-iter1.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_loop_library.py -v
```

Expected: failures because the build-parity helpers do not exist yet.

- [ ] **Step 3: Implement body in `scripts/lib/crossai_loop.py`**

Replace the `NotImplementedError` body by extracting the CURRENT build loop logic into the library. Do not invent a simplified single-primary path for M1.

Implementation constraints:

- Preserve parallel Codex+Gemini execution from the current script.
- Preserve current output directory naming (`crossai-build-verify`).
- Preserve current event emission (`build.crossai_iteration_started`, `build.crossai_iteration_complete`, `build.crossai_loop_complete`).
- Preserve current findings JSON structure and `<crossai-build-verdict>` parsing contract.
- Preserve current parse-failure and infra-failure exit-2 behavior.
- Preserve `--max-iterations` threading; do not hardcode a new internal default path that changes runtime semantics.

If the extracted API becomes awkward, prefer a build-specific helper such as
`run_build_legacy_iteration(...)` internally. Generic multi-stage cleanup can
wait for M3.

```python
"""CrossAI orchestration library — shared by scope/blueprint/build wrappers.

Public API:
    run_loop(phase, iteration, brief_packer, stage_config, out_dir=None) -> int

Exit codes:
    EXIT_CLEAN          = 0
    EXIT_BLOCKS_FOUND   = 1
    EXIT_INFRA_FAIL     = 2

M1: single-primary passthrough (mirrors existing vg-build-crossai-loop.py).
M3: extends to parallel multi-primary + Sonnet adjudicator.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from crossai_config import StageConfig, CLISpec

EXIT_CLEAN = 0
EXIT_BLOCKS_FOUND = 1
EXIT_INFRA_FAIL = 2

BriefPacker = Callable[[Path, str, int, int], str]

_DEFAULT_MAX_ITER = 5


def run_loop(
    phase: str,
    iteration: int,
    brief_packer: BriefPacker,
    stage_config: StageConfig,
    out_dir: Path | None = None,
) -> int:
    """See module docstring. M1 single-primary passthrough."""
    if not stage_config.primary_clis:
        return EXIT_INFRA_FAIL  # No CLI configured → cannot run
    primary = stage_config.primary_clis[0]

    if out_dir is None:
        phase_dir = _find_phase_dir(phase)
        if phase_dir is None:
            return EXIT_INFRA_FAIL
        out_dir = phase_dir / f"{stage_config.stage}-crossai-verify"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Pack + write brief
    phase_dir_for_packer = (
        _find_phase_dir(phase) or out_dir.parent
    )
    brief = brief_packer(
        phase_dir_for_packer, phase, iteration, _DEFAULT_MAX_ITER,
    )
    brief_path = out_dir / f"BRIEF-iter{iteration}.md"
    brief_path.write_text(brief, encoding="utf-8")

    # 2. Invoke CLI
    raw_path = out_dir / f"{primary.name}-iter{iteration}.md"
    rc, raw = _invoke_cli(primary, brief)
    raw_path.write_text(raw, encoding="utf-8")
    if rc != 0:
        return EXIT_INFRA_FAIL

    # 3. Parse verdict + findings
    verdict, findings = _parse_verdict_xml(raw)
    findings_path = out_dir / f"findings-iter{iteration}.json"
    findings_path.write_text(
        json.dumps(
            {
                "stage": stage_config.stage,
                "iteration": iteration,
                "verdict": verdict,
                "findings": findings,
                "source_cli": primary.name,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if any(f.get("severity") == "BLOCK" for f in findings):
        return EXIT_BLOCKS_FOUND
    return EXIT_CLEAN


def _invoke_cli(spec: CLISpec, brief_text: str) -> tuple[int, str]:
    """Invoke a CLI by piping brief into stdin via the spec.command template.

    Returns (returncode, combined stdout+stderr).
    """
    # Render command template with empty {context} (brief is piped via stdin)
    rendered = spec.command.replace("{context}", "/dev/stdin").replace(
        "{prompt}", "review the brief above",
    )
    # Strip wrapping `cat {context} | ` if present — we pipe via stdin directly
    rendered = re.sub(r"^cat\s+/dev/stdin\s*\|\s*", "", rendered)
    binary = rendered.split()[0]
    if shutil.which(binary) is None:
        return 127, f"{binary}: command not found"
    try:
        proc = subprocess.run(
            ["/bin/sh", "-c", rendered],
            input=brief_text,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as exc:
        return 1, f"invocation error: {exc}"


def _parse_verdict_xml(text: str) -> tuple[str, list[dict]]:
    """Lenient parse of <crossai-verdict> XML. Returns (verdict, findings).

    findings: list of {severity, message, ...} dicts. Empty list when none.
    """
    verdict = "UNKNOWN"
    findings: list[dict] = []
    m = re.search(r"<verdict>([^<]+)</verdict>", text, re.I)
    if m:
        verdict = m.group(1).strip().upper()
    for m in re.finditer(
        r'<finding\s+severity="([^"]+)"[^>]*>(.*?)</finding>',
        text, re.I | re.DOTALL,
    ):
        sev = m.group(1).strip().upper()
        body = m.group(2)
        msg_m = re.search(r"<message>(.*?)</message>", body, re.DOTALL)
        msg = msg_m.group(1).strip() if msg_m else body.strip()
        findings.append({"severity": sev, "message": msg})
    return verdict, findings


def _find_phase_dir(phase: str) -> Path | None:
    """Find .vg/phases/<NN-name> directory matching `phase`.

    Pattern matches "04.2-anything" or "4.2-anything".
    """
    root = Path.cwd() / ".vg" / "phases"
    if not root.is_dir():
        return None
    pad = f"{int(float(phase) * 10):04d}"  # 4.2 → "0042"
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith(f"{phase}-") or name.startswith(
            f"{phase.lstrip('0')}-",
        ) or name.startswith(f"{pad[:2]}.{pad[2:]}-"):
            return child
    return None
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest scripts/tests/test_crossai_loop_library.py -v
```

Expected: tests from Tasks 05-06 pass, including build-parity assertions.

- [ ] **Step 5: Sync mirror + commit**

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
cp scripts/lib/crossai_loop.py .claude/scripts/lib/crossai_loop.py
git add scripts/lib/crossai_loop.py \
        .claude/scripts/lib/crossai_loop.py \
        scripts/tests/test_crossai_loop_library.py
git commit -m "refactor(crossai-loop): extract build-legacy runtime with parity

M1 Task 06 — moves the current build CrossAI runtime into the shared
library without changing semantics: parallel Codex+Gemini execution,
current build event names, current findings JSON shape, current
crossai-build-verify path, current parse/infra-fail handling.

This is an extraction seam, not a behavior redesign. M3 can generalize
later from a frozen baseline.

Tests: build-parity focused (dual invocation, current output paths,
BLOCK handling, infra-fail handling, default output dir parity).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
