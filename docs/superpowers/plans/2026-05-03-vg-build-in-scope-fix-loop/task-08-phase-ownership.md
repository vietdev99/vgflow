<!-- Per-task plan file. Self-contained — execute as instructed. -->
<!-- Index: ../2026-05-03-vg-build-in-scope-fix-loop.md -->
<!-- Plan: 2026-05-03-vg-build-in-scope-fix-loop -->


## Task 8: B6 — Phase ownership allowlist

**Files:**
- Create: `scripts/lib/phase_ownership.py`
- Test: `tests/test_phase_ownership.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_phase_ownership.py`:

```python
"""Phase ownership allowlist — Codex blind-spot #6: auto-fix MUST NOT
'repair the world' beyond phase boundaries."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "scripts" / "lib"


def test_owned_files_extracted_from_plan_tasks(tmp_path: Path) -> None:
    pd = tmp_path / "phase"
    (pd / "PLAN").mkdir(parents=True)
    (pd / "PLAN" / "task-01.md").write_text(textwrap.dedent("""
        # task-01

        File: apps/api/src/billing/invoices.ts
        Edits: apps/api/src/billing/invoices.test.ts
    """).strip(), encoding="utf-8")
    (pd / "PLAN" / "task-02.md").write_text(textwrap.dedent("""
        # task-02

        File: apps/web/src/pages/InvoiceDetailPage.tsx
    """).strip(), encoding="utf-8")
    sys.path.insert(0, str(LIB))
    from phase_ownership import owned_paths  # type: ignore

    paths = owned_paths(pd)
    assert "apps/api/src/billing/invoices.ts" in paths
    assert "apps/api/src/billing/invoices.test.ts" in paths
    assert "apps/web/src/pages/InvoiceDetailPage.tsx" in paths
    sys.path.remove(str(LIB))


def test_is_owned_returns_true_for_listed_path(tmp_path: Path) -> None:
    pd = tmp_path / "phase"
    (pd / "PLAN").mkdir(parents=True)
    (pd / "PLAN" / "task-01.md").write_text("File: apps/api/src/x.ts\n", encoding="utf-8")
    sys.path.insert(0, str(LIB))
    from phase_ownership import is_owned  # type: ignore

    assert is_owned("apps/api/src/x.ts", pd)
    assert not is_owned("apps/api/src/middleware/error.ts", pd)
    sys.path.remove(str(LIB))


def test_is_owned_handles_subpath_match(tmp_path: Path) -> None:
    """File listed via directory ownership: 'Edits: apps/api/src/billing/' → owns
    everything under that prefix."""
    pd = tmp_path / "phase"
    (pd / "PLAN").mkdir(parents=True)
    (pd / "PLAN" / "task-01.md").write_text(
        "Edits dir: apps/api/src/billing/\n", encoding="utf-8",
    )
    sys.path.insert(0, str(LIB))
    from phase_ownership import is_owned  # type: ignore

    assert is_owned("apps/api/src/billing/invoices.ts", pd)
    assert is_owned("apps/api/src/billing/sub/file.ts", pd)
    assert not is_owned("apps/api/src/auth/x.ts", pd)
    sys.path.remove(str(LIB))
```

- [ ] **Step 2: Run failing tests**

Run: `python3 -m pytest tests/test_phase_ownership.py -v`
Expected: 3 failures.

- [ ] **Step 3: Write the module**

Create `scripts/lib/phase_ownership.py`:

```python
"""phase_ownership — auto-fix scope guard.

Per Codex review (2026-05-03) blind-spot #6: auto-fix subagent MUST NOT
modify files outside the current phase's stated ownership. Ownership is
extracted from PLAN/task-*.md files via two patterns:

  Pattern A (single file):    "File: <path>" or "Edits: <path>"
  Pattern B (directory):      "Edits dir: <path>/"

A path is OWNED when:
  - exact match against any pattern A
  - prefix match against any pattern B (directory)
"""
from __future__ import annotations

import re
from pathlib import Path

FILE_RE = re.compile(r"(?:^|\b)(?:File|Edits)\s*:\s*(\S+)", re.MULTILINE)
DIR_RE = re.compile(r"(?:^|\b)Edits\s+dir\s*:\s*(\S+/)", re.MULTILINE)


def _extract(phase_dir: Path) -> tuple[set[str], list[str]]:
    files: set[str] = set()
    dirs: list[str] = []
    plan_dir = phase_dir / "PLAN"
    if not plan_dir.exists():
        return files, dirs
    for tp in plan_dir.glob("task-*.md"):
        try:
            text = tp.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in FILE_RE.finditer(text):
            files.add(m.group(1))
        for m in DIR_RE.finditer(text):
            dirs.append(m.group(1))
    return files, dirs


def owned_paths(phase_dir: Path) -> set[str]:
    """Return set of explicit file paths owned by this phase."""
    files, _ = _extract(phase_dir)
    return files


def is_owned(path: str, phase_dir: Path) -> bool:
    """Check if the given path is within this phase's ownership."""
    files, dirs = _extract(phase_dir)
    if path in files:
        return True
    return any(path.startswith(d) for d in dirs)
```

- [ ] **Step 4: Run tests + commit**

Run:
```bash
cd "/Users/dzungnguyen/Vibe Code/Code/vgflow-bugfix"
python3 -m pytest tests/test_phase_ownership.py -v
git add scripts/lib/phase_ownership.py tests/test_phase_ownership.py
git commit -m "feat(build-fix-loop): add B6 phase ownership allowlist (auto-fix scope guard)"
```
Expected: 3 passed.

---

