"""Smoke tests for verify-narration-coverage validator.

This validator is authored in v2.5.2.10. Tests verify:
  - Raw-string Evidence fields detected as violations
  - t(...) calls pass
  - f-strings flagged as violations
  - Non-prose fields (actual/expected) ignored
  - Ternary with raw branch flagged
  - _common / _i18n themselves skipped
"""
import ast
import subprocess
import sys
from pathlib import Path

VALIDATOR = Path(__file__).resolve().parents[1] / "validators" / \
    "verify-narration-coverage.py"


def _run(tmp_dir: Path, args: list[str]) -> tuple[int, str]:
    """Run validator against tmp_dir and return (rc, stdout)."""
    cmd = [
        sys.executable, str(VALIDATOR),
        "--root", str(tmp_dir),
        "--json-only",
    ] + args
    p = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8"
    )
    return (p.returncode, p.stdout)


def test_raw_string_detected(tmp_path):
    f = tmp_path / "my_validator.py"
    f.write_text(
        "from _common import Evidence\n"
        "def fn():\n"
        "    return Evidence(type='x', message='hardcoded English')\n",
        encoding="utf-8",
    )
    rc, out = _run(tmp_path, [])
    assert rc == 1
    import json
    data = json.loads(out)
    assert data["verdict"] == "BLOCK"
    assert data["summary"]["hardcoded_prose"] >= 1


def test_t_call_passes(tmp_path):
    f = tmp_path / "good_validator.py"
    f.write_text(
        "from _common import Evidence\n"
        "from _i18n import t\n"
        "def fn():\n"
        "    return Evidence(type='x', message=t('good.foo.message'))\n",
        encoding="utf-8",
    )
    rc, out = _run(tmp_path, [])
    import json
    data = json.loads(out)
    assert rc == 0
    assert data["verdict"] == "PASS"
    assert data["summary"]["hardcoded_prose"] == 0


def test_fstring_detected_as_raw(tmp_path):
    f = tmp_path / "fstring_validator.py"
    f.write_text(
        "from _common import Evidence\n"
        "def fn(count):\n"
        "    return Evidence(type='x', message=f'{count} items broken')\n",
        encoding="utf-8",
    )
    rc, out = _run(tmp_path, [])
    import json
    data = json.loads(out)
    assert rc == 1
    assert data["summary"]["hardcoded_prose"] >= 1


def test_non_prose_field_ignored(tmp_path):
    f = tmp_path / "data_only.py"
    f.write_text(
        "from _common import Evidence\n"
        "def fn():\n"
        "    return Evidence(type='x', actual='file.ts:42',\n"
        "                    expected='/api/v1/endpoint')\n",
        encoding="utf-8",
    )
    rc, out = _run(tmp_path, [])
    import json
    data = json.loads(out)
    # actual/expected fields are data, not prose — should NOT trigger
    assert rc == 0
    assert data["verdict"] == "PASS"


def test_fix_hint_also_enforced(tmp_path):
    f = tmp_path / "hint_validator.py"
    f.write_text(
        "from _common import Evidence\n"
        "from _i18n import t\n"
        "def fn():\n"
        "    return Evidence(type='x', message=t('k.msg'),\n"
        "                    fix_hint='Run /vg:fix manually')\n",
        encoding="utf-8",
    )
    rc, out = _run(tmp_path, [])
    import json
    data = json.loads(out)
    assert rc == 1
    assert data["summary"]["hardcoded_prose"] >= 1


def test_conditional_raw_branch(tmp_path):
    f = tmp_path / "ternary.py"
    f.write_text(
        "from _common import Evidence\n"
        "from _i18n import t\n"
        "def fn(cond):\n"
        "    return Evidence(type='x',\n"
        "        message=t('k.msg') if cond else 'raw English fallback')\n",
        encoding="utf-8",
    )
    rc, out = _run(tmp_path, [])
    import json
    data = json.loads(out)
    assert rc == 1
    assert data["summary"]["conditional_raw_branch"] >= 1


def test_skip_basenames_not_scanned(tmp_path):
    # _common.py is the module that DEFINES Evidence — must not be flagged
    f = tmp_path / "_common.py"
    f.write_text(
        "class Evidence:\n"
        "    def __init__(self, **kw): self.__dict__.update(kw)\n"
        "# Also create an Evidence with raw message — this is library code,\n"
        "# not a validator, so it MUST be skipped.\n"
        "demo = Evidence(message='library demo string')\n",
        encoding="utf-8",
    )
    rc, out = _run(tmp_path, [])
    import json
    data = json.loads(out)
    # _common.py is skipped — 0 files scanned → PASS
    assert rc == 0
    assert data["summary"]["files_scanned"] == 0
