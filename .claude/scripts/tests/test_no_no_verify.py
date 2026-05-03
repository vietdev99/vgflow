"""
Tests for verify-no-no-verify.py — Harness v2.6.1 Batch D.

Catches `--no-verify` / `--no-gpg-sign` / `HUSKY=0` patterns in source
code that bypass pre-commit hooks. Hook bypass is a security hole — hooks
enforce typecheck + commit-attribution + secrets-scan.

Covers:
  - Clean source file (no flag) → 0
  - .py file with `git commit --no-verify` → 1 (BLOCK)
  - .sh file with `HUSKY=0 git commit` → 1 (BLOCK)
  - .ts file with `git push --no-verify` → 1 (BLOCK)
  - .md file with NEGATIVE example ("NEVER use --no-verify") → 0 (allowed doc mention)
  - .md file with code fence + no negative marker → 0 with WARN
  - .git/ ignored
  - .vg/ ignored
  - Validator's own file ignored (allowlisted)
  - --strict treats WARN as BLOCK (markdown bare-mention escalates)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT_REAL = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT_REAL / ".claude" / "scripts" / "validators" / "verify-no-no-verify.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VG_REPO_ROOT"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True, text=True, timeout=30, env=env,
        encoding="utf-8", errors="replace", cwd=str(cwd),
    )


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestNoNoVerify:
    def test_clean_source_passes(self, tmp_path):
        _write(tmp_path / "apps/api/src/index.py", "import os\nprint('hello')\n")
        r = _run([], tmp_path)
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_no_verify_in_python_blocks(self, tmp_path):
        _write(tmp_path / "apps/api/src/deploy.py", """
import os

def push_changes():
    os.system("git commit -m wip --no-verify")
""")
        r = _run([], tmp_path)
        assert r.returncode == 1, f"expected BLOCK; got rc={r.returncode}\nstdout={r.stdout}"
        assert "no-verify" in r.stdout.lower() or "no_verify" in r.stdout.lower()

    def test_husky_zero_in_shell_blocks(self, tmp_path):
        _write(tmp_path / "scripts/release.sh", """#!/bin/bash
HUSKY=0 git commit -m "release"
""")
        r = _run([], tmp_path)
        assert r.returncode == 1, f"expected BLOCK; got rc={r.returncode}\nstdout={r.stdout}"

    def test_no_verify_push_in_typescript_blocks(self, tmp_path):
        _write(tmp_path / "apps/web/src/release.ts", """
const cmd = 'git push origin main --no-verify';
import { exec } from 'child_process';
exec(cmd);
""")
        r = _run([], tmp_path)
        assert r.returncode == 1

    def test_md_negative_example_allowed(self, tmp_path):
        _write(tmp_path / "docs/conventions.md", """# Git rules

NEVER use `--no-verify`. Hook bypass = security hole.

❌ Don't: `git commit --no-verify`
""")
        r = _run([], tmp_path)
        # negative-example marker → skip (legitimate doc)
        assert r.returncode == 0, f"stdout={r.stdout}"

    def test_vg_dir_ignored(self, tmp_path):
        _write(tmp_path / ".vg/some-log.md", "git commit --no-verify\n")
        r = _run([], tmp_path)
        # .vg/ is in skip_dirs → no scan → no block
        assert r.returncode == 0

    def test_git_dir_ignored(self, tmp_path):
        _write(tmp_path / ".git/hooks/pre-push.sh", "#!/bin/bash\ngit commit --no-verify\n")
        r = _run([], tmp_path)
        assert r.returncode == 0

    def test_validator_self_file_allowlisted(self, tmp_path):
        # Place file matching validator's own path — should be allowlisted
        _write(
            tmp_path / ".claude/scripts/validators/verify-no-no-verify.py",
            "# This file references --no-verify by design\nimport os\n",
        )
        r = _run([], tmp_path)
        assert r.returncode == 0

    def test_strict_mode_promotes_warn_to_block(self, tmp_path):
        # Markdown with bare mention in code fence (no negative marker) → WARN normally
        _write(tmp_path / "apps/web/README.md", """# Example

Run this:

```bash
git commit --no-verify
```
""")
        r_normal = _run([], tmp_path)
        # WARN in non-strict = exit 0
        assert r_normal.returncode == 0

        r_strict = _run(["--strict"], tmp_path)
        # In strict, WARN promotes to BLOCK
        assert r_strict.returncode == 1, f"strict mode: expected BLOCK; got rc={r_strict.returncode}\nstdout={r_strict.stdout}"

    def test_emits_valid_json(self, tmp_path):
        _write(tmp_path / "apps/api/src/clean.py", "x = 1\n")
        r = _run([], tmp_path)
        try:
            doc = json.loads(r.stdout)
            assert "verdict" in doc
            assert doc["validator"] == "verify-no-no-verify"
        except json.JSONDecodeError:
            pytest.fail(f"validator must emit JSON; got: {r.stdout[:200]}")
