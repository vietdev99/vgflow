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
