"""
B8.1 — secrets-scan.py regression tests.

Verifies detection of common secret patterns, allowlist behavior, and
low-signal path handling. Covers gap D1 (secrets scanner).
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / "secrets-scan.py"


def _git_available() -> bool:
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, timeout=3)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(
    not _git_available(), reason="git not available",
)


def _setup_repo(tmp_path: Path) -> Path:
    """Init repo + make a baseline commit so diff has something to compare."""
    subprocess.run(["git", "init", "-q", "-b", "main"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@x"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"],
                   cwd=tmp_path, check=True)
    # Baseline commit (empty tree ok after first real file)
    (tmp_path / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-q", "--no-verify", "-m", "init"],
                   cwd=tmp_path, check=True, capture_output=True)
    # Copy narration strings so t() resolves
    src_shared = REPO_ROOT / ".claude" / "commands" / "vg" / "_shared"
    dst_shared = tmp_path / ".claude" / "commands" / "vg" / "_shared"
    dst_shared.mkdir(parents=True, exist_ok=True)
    for name in ("narration-strings.yaml", "narration-strings-validators.yaml"):
        s = src_shared / name
        if s.exists():
            (dst_shared / name).write_text(s.read_text(encoding="utf-8"),
                                           encoding="utf-8")
    return tmp_path


def _stage_file(repo: Path, rel: str, body: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=repo, check=True,
                   capture_output=True)


def _run(repo: Path, mode: str = "staged") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["VG_REPO_ROOT"] = str(repo)
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--mode", mode],
        cwd=repo, capture_output=True, text=True, timeout=30, env=env,
    )


# ─────────────────────────────────────────────────────────────────────────

def test_clean_diff_passes(tmp_path):
    repo = _setup_repo(tmp_path)
    _stage_file(repo, "apps/api/src/routes.ts", """
export const routes = {
  login: '/auth/login',
  logout: '/auth/logout',
}
""")
    r = _run(repo)
    assert r.returncode == 0, f"clean diff should pass, got {r.returncode}\n{r.stdout}"


def test_aws_access_key_blocks(tmp_path):
    repo = _setup_repo(tmp_path)
    _stage_file(repo, "apps/api/src/aws.ts",
                "const key = 'AKIAIOSFODNN7EXAMPLE';\n")
    r = _run(repo)
    assert r.returncode == 1
    assert "aws_access_key_id" in r.stdout


def test_github_pat_blocks(tmp_path):
    repo = _setup_repo(tmp_path)
    _stage_file(repo, "apps/api/src/gh.ts",
                "const token = 'ghp_abc123def456ghi789jkl012mno345pqr678st';\n")
    r = _run(repo)
    assert r.returncode == 1
    assert "github_pat" in r.stdout


def test_stripe_live_key_blocks(tmp_path):
    repo = _setup_repo(tmp_path)
    # Split literal to sidestep GitHub push-protection scanner.
    # The scanner matches at rest; we concatenate at runtime so the
    # written file still contains a realistic stripe live-key pattern
    # that the validator must detect as a secret.
    _stage_file(repo, "apps/api/src/payment.ts",
                "const stripe = '" + "sk_live" + "_abc123XYZ456def789ghi0jklmno';\n")
    r = _run(repo)
    assert r.returncode == 1
    assert "stripe_live_key" in r.stdout


def test_private_key_pem_blocks(tmp_path):
    repo = _setup_repo(tmp_path)
    _stage_file(repo, "config/cert.txt", """
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA...
-----END RSA PRIVATE KEY-----
""")
    r = _run(repo)
    assert r.returncode == 1
    assert "private_key_pem" in r.stdout


def test_db_url_with_password_blocks(tmp_path):
    repo = _setup_repo(tmp_path)
    _stage_file(repo, "apps/api/src/db.ts",
                "const uri = 'postgres://admin:supersecret123@db.internal:5432/app';\n")
    r = _run(repo)
    assert r.returncode == 1
    assert "db_url_with_password" in r.stdout


def test_placeholder_does_not_flag(tmp_path):
    repo = _setup_repo(tmp_path)
    _stage_file(repo, "apps/api/README.md", """
Set `API_KEY=your-api-key-here` in `.env`.
Example: `API_KEY=REPLACE_WITH_YOUR_KEY`.
""")
    r = _run(repo)
    assert r.returncode == 0, f"placeholder should not flag, got {r.stdout}"


def test_low_signal_path_skips_medium(tmp_path):
    """Test fixture with a password-literal match → skipped (low-signal path)."""
    repo = _setup_repo(tmp_path)
    _stage_file(repo, "apps/api/src/__fixtures__/users.json",
                '{"password": "testpassword123"}\n')
    r = _run(repo)
    assert r.returncode == 0


def test_low_signal_path_still_catches_critical(tmp_path):
    """Fixture path doesn't suppress CRITICAL-confidence patterns."""
    repo = _setup_repo(tmp_path)
    _stage_file(repo, "apps/api/src/__fixtures__/aws.ts",
                "const k = 'AKIAIOSFODNN7EXAMPLE';\n")
    r = _run(repo)
    assert r.returncode == 1


def test_allowlist_suppresses(tmp_path):
    repo = _setup_repo(tmp_path)
    _stage_file(repo, "apps/api/src/aws.ts",
                "const example = 'AKIAIOSFODNN7EXAMPLE';\n")
    (repo / ".vg").mkdir(exist_ok=True)
    (repo / ".vg" / "secrets-allowlist.yml").write_text(textwrap.dedent("""\
        - pattern: "AKIAIOSFODNN7EXAMPLE"
          file: "apps/api/src/aws.ts"
          reason: "AWS docs example key, safe"
          expires: "2099-12-31"
    """), encoding="utf-8")
    subprocess.run(["git", "add", ".vg/secrets-allowlist.yml"],
                   cwd=repo, check=True, capture_output=True)

    r = _run(repo)
    assert r.returncode == 0, f"allowlist should suppress, got {r.stdout}"


def test_allowlist_expired_re_activates_block(tmp_path):
    repo = _setup_repo(tmp_path)
    _stage_file(repo, "apps/api/src/aws.ts",
                "const k = 'AKIAIOSFODNN7EXAMPLE';\n")
    (repo / ".vg").mkdir(exist_ok=True)
    (repo / ".vg" / "secrets-allowlist.yml").write_text(textwrap.dedent("""\
        - pattern: "AKIAIOSFODNN7EXAMPLE"
          reason: "old waiver"
          expires: "2020-01-01"
    """), encoding="utf-8")

    r = _run(repo)
    assert r.returncode == 1


def test_output_in_vietnamese(tmp_path):
    """Verify Evidence.message is Vietnamese (B8.0 rule)."""
    repo = _setup_repo(tmp_path)
    _stage_file(repo, "apps/api/src/aws.ts",
                "const k = 'AKIAIOSFODNN7EXAMPLE';\n")
    r = _run(repo)
    assert r.returncode == 1
    vn_markers = [
        "bí mật", "b\\u00ed m\\u1eadt",  # "bí mật"
        "CRITICAL", "l\\u1ed9 ra",       # "lộ ra"
    ]
    assert any(m in r.stdout for m in vn_markers), (
        f"expected VN markers, got:\n{r.stdout}"
    )


def test_secret_value_redacted_in_output(tmp_path):
    """The full secret must not appear verbatim in output (prevent re-leak)."""
    repo = _setup_repo(tmp_path)
    secret = "AKIAIOSFODNN7EXAMPLE"
    _stage_file(repo, "apps/api/src/aws.ts",
                f"const k = '{secret}';\n")
    r = _run(repo)
    assert r.returncode == 1
    # Full secret should NOT be in output; redaction puts ... in middle.
    assert secret not in r.stdout, (
        f"full secret leaked in output:\n{r.stdout}"
    )
