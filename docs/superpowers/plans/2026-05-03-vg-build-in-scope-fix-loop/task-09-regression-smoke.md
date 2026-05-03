<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 9: B7 — Post-fix regression smoke runner

**Files:**
- Create: `scripts/lib/regression_smoke.py`

- [ ] **Step 1: Write the module**

Create `scripts/lib/regression_smoke.py`:

```python
"""regression_smoke — Codex blind-spot #7.

After auto-fix subagent commits a fix, run TARGETED smoke tests touching
the affected route/view + a small phase-wide smoke pass. If smoke fails,
revert the fix and re-classify the warning as NEEDS_TRIAGE.

Smoke selection rules:
  - For evidence_refs[].task_id, run tests in the same path as task file
    (e.g. task-39 edits apps/api/src/billing/invoices.ts → run
    apps/api/src/billing/invoices.test.ts if exists)
  - For evidence_refs[].endpoint, run any test naming the endpoint string
    (grep test files containing the path_template)
  - Plus: vitest run --testPathPattern '<phase-touched>' AND first 5
    e2e specs (smoke stub)

Test runner detection:
  - vitest if package.json has "vitest"
  - jest if package.json has "jest"
  - pytest if .py tests exist
  - cargo test if Cargo.toml present
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


def detect_runner(repo_root: Path) -> str | None:
    pj = repo_root / "package.json"
    if pj.exists():
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if "vitest" in deps:
                return "vitest"
            if "jest" in deps:
                return "jest"
        except (OSError, json.JSONDecodeError):
            pass
    if (repo_root / "Cargo.toml").exists():
        return "cargo"
    if list(repo_root.glob("**/*.py")):
        return "pytest"
    return None


def select_smoke_tests(repo_root: Path, evidence_refs: Iterable[dict]) -> list[str]:
    """Return list of test path patterns / specs to run."""
    patterns: set[str] = set()
    for r in evidence_refs:
        f = r.get("file")
        if f:
            stem = Path(f).stem
            # Look for adjacent .test.<ext>
            for ext in (".test.ts", ".test.tsx", ".test.js", ".spec.ts"):
                candidate = (Path(f).parent / f"{stem}{ext}").as_posix()
                if (repo_root / candidate).exists():
                    patterns.add(candidate)
        ep = r.get("endpoint")
        if ep:
            patterns.add(ep.replace("/", "_").replace(":", "").strip())
    return sorted(patterns)


def run_smoke(repo_root: Path, runner: str, patterns: list[str]) -> tuple[bool, str]:
    """Run smoke tests; return (ok, stdout+stderr)."""
    if not patterns:
        return True, "no smoke patterns matched"
    if runner == "vitest":
        cmd = ["npx", "vitest", "run", *patterns, "--reporter=basic"]
    elif runner == "jest":
        cmd = ["npx", "jest", "--testPathPattern", "|".join(patterns)]
    elif runner == "pytest":
        cmd = ["python3", "-m", "pytest", *patterns, "-x"]
    elif runner == "cargo":
        cmd = ["cargo", "test", "--", *patterns]
    else:
        return False, f"unknown runner: {runner}"
    try:
        proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, timeout=180)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f"runner failed: {e}"
    return proc.returncode == 0, proc.stdout + proc.stderr
```

- [ ] **Step 2: Smoke-test the helper**

Run a quick sanity check (no test file — just verify the module imports):

```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -c "
import sys
sys.path.insert(0, 'scripts/lib')
from regression_smoke import detect_runner, select_smoke_tests
from pathlib import Path
print('runner:', detect_runner(Path('.')))
print('patterns:', select_smoke_tests(Path('.'), [{'file': 'scripts/emit-tasklist.py'}]))
"
```
Expected: prints runner type (or None) and pattern list.

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/regression_smoke.py
git commit -m "feat(build-fix-loop): add B7 post-fix regression smoke runner library"
```

---

