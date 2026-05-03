"""
Tests for validate-crossai-review-xml.py + verify-crossai-multi-cli.py
— Phase L of v2.5.2.

Covers XML validator:
  - Valid XML with pass/flag/block verdict → OK
  - Missing <verdict> element → FAIL
  - Invalid verdict value → FAIL
  - Missing/unparseable <score> → FAIL
  - Score out of range 0-10 → FAIL
  - Missing <reviewer> → FAIL
  - Malformed XML (parse error) → FAIL
  - Empty file → FAIL
  - Content with preamble before <crossai_review> block → extracts correctly
  - Custom --require-xpath check

Covers multi-CLI consensus:
  - 3 CLIs agreeing → OK
  - 2 CLIs agree, 1 disagree → OK if min-consensus=2
  - No agreement → FAIL
  - 2 CLIs from same reviewer (spoofing) → FAIL on diversity
  - --require-all N enforces count
  - Empty glob → FAIL
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
XML_VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "validate-crossai-review-xml.py"
MULTI_CLI_VALIDATOR = REPO_ROOT / ".claude" / "scripts" / "validators" / \
    "verify-crossai-multi-cli.py"


def _run(script: Path, args: list[str], cwd: Path | None = None
         ) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=30,
        cwd=str(cwd) if cwd else None, env=env,
        encoding="utf-8", errors="replace",
    )


def _write_xml(path: Path, reviewer="Codex GPT 5.4", verdict="pass",
               score="8.5/10", include_findings=True) -> None:
    """Write a valid-ish crossai_review XML for tests."""
    findings_block = """
  <findings>
    <finding>
      <severity>minor</severity>
      <title>Example</title>
    </finding>
  </findings>""" if include_findings else ""
    content = f"""<crossai_review>
  <reviewer>{reviewer}</reviewer>
  <verdict>{verdict}</verdict>
  <score>{score}</score>{findings_block}
</crossai_review>"""
    path.write_text(content, encoding="utf-8")


# ─── XML validator tests ──────────────────────────────────────────────

class TestXmlValidator:
    def test_valid_xml_passes(self, tmp_path):
        f = tmp_path / "result-codex.xml"
        _write_xml(f)
        r = _run(XML_VALIDATOR, ["--path", str(f), "--quiet"])
        assert r.returncode == 0

    def test_missing_verdict_fails(self, tmp_path):
        f = tmp_path / "r.xml"
        f.write_text("""<crossai_review>
  <reviewer>X</reviewer>
  <score>5</score>
</crossai_review>""", encoding="utf-8")
        r = _run(XML_VALIDATOR, ["--path", str(f)])
        assert r.returncode == 1
        assert "verdict" in r.stdout.lower()

    def test_invalid_verdict_value_fails(self, tmp_path):
        f = tmp_path / "r.xml"
        _write_xml(f, verdict="FAKE_VERDICT")
        r = _run(XML_VALIDATOR, ["--path", str(f)])
        assert r.returncode == 1
        assert "not in" in r.stdout

    def test_missing_score_fails(self, tmp_path):
        f = tmp_path / "r.xml"
        f.write_text("""<crossai_review>
  <reviewer>X</reviewer>
  <verdict>pass</verdict>
</crossai_review>""", encoding="utf-8")
        r = _run(XML_VALIDATOR, ["--path", str(f)])
        assert r.returncode == 1
        assert "score" in r.stdout.lower()

    def test_score_out_of_range_fails(self, tmp_path):
        f = tmp_path / "r.xml"
        _write_xml(f, score="99")
        r = _run(XML_VALIDATOR, ["--path", str(f)])
        assert r.returncode == 1
        assert "range" in r.stdout.lower()

    def test_missing_reviewer_fails(self, tmp_path):
        f = tmp_path / "r.xml"
        f.write_text("""<crossai_review>
  <verdict>pass</verdict>
  <score>7</score>
</crossai_review>""", encoding="utf-8")
        r = _run(XML_VALIDATOR, ["--path", str(f)])
        assert r.returncode == 1
        assert "reviewer" in r.stdout.lower()

    def test_malformed_xml_fails(self, tmp_path):
        f = tmp_path / "r.xml"
        f.write_text("<crossai_review><verdict>pass</not-closed>", encoding="utf-8")
        r = _run(XML_VALIDATOR, ["--path", str(f)])
        assert r.returncode == 1
        assert "parse" in r.stdout.lower() or "block found" in r.stdout.lower()

    def test_empty_file_fails(self, tmp_path):
        f = tmp_path / "r.xml"
        f.write_text("", encoding="utf-8")
        r = _run(XML_VALIDATOR, ["--path", str(f)])
        assert r.returncode == 1

    def test_preamble_before_xml_extracted(self, tmp_path):
        """CrossAI output often has CLI chatter before XML — should extract."""
        f = tmp_path / "r.xml"
        f.write_text("""Codex CLI v0.122.0
Loading context...
Analyzing...

<crossai_review>
  <reviewer>Codex</reviewer>
  <verdict>flag</verdict>
  <score>7.2</score>
</crossai_review>

tokens used: 1234""", encoding="utf-8")
        r = _run(XML_VALIDATOR, ["--path", str(f), "--quiet"])
        assert r.returncode == 0

    def test_custom_xpath_required(self, tmp_path):
        f = tmp_path / "r.xml"
        _write_xml(f, verdict="pass")
        r = _run(XML_VALIDATOR, [
            "--path", str(f),
            "--require-xpath", "/crossai_review/verdict[text() = 'pass']",
        ])
        assert r.returncode == 0

        # Same file, require different verdict → should fail
        r = _run(XML_VALIDATOR, [
            "--path", str(f),
            "--require-xpath", "/crossai_review/verdict[text() = 'block']",
        ])
        assert r.returncode == 1


# ─── Multi-CLI consensus tests ────────────────────────────────────────

class TestMultiCliConsensus:
    def test_three_agree_passes(self, tmp_path):
        _write_xml(tmp_path / "result-codex.xml", reviewer="Codex")
        _write_xml(tmp_path / "result-gemini.xml", reviewer="Gemini")
        _write_xml(tmp_path / "result-claude.xml", reviewer="Claude")

        r = _run(MULTI_CLI_VALIDATOR, [
            "--glob", str(tmp_path / "result-*.xml"),
            "--min-consensus", "2", "--quiet",
        ])
        assert r.returncode == 0

    def test_two_agree_one_conflict_with_min_2(self, tmp_path):
        _write_xml(tmp_path / "result-codex.xml", reviewer="Codex", verdict="pass")
        _write_xml(tmp_path / "result-gemini.xml", reviewer="Gemini", verdict="pass")
        _write_xml(tmp_path / "result-claude.xml", reviewer="Claude", verdict="block")

        r = _run(MULTI_CLI_VALIDATOR, [
            "--glob", str(tmp_path / "result-*.xml"),
            "--min-consensus", "2",
        ])
        assert r.returncode == 0

    def test_no_agreement_fails(self, tmp_path):
        _write_xml(tmp_path / "result-a.xml", reviewer="A", verdict="pass")
        _write_xml(tmp_path / "result-b.xml", reviewer="B", verdict="flag")
        _write_xml(tmp_path / "result-c.xml", reviewer="C", verdict="block")

        r = _run(MULTI_CLI_VALIDATOR, [
            "--glob", str(tmp_path / "result-*.xml"),
            "--min-consensus", "2",
        ])
        # Each verdict has 1 vote; max agreement=1 < required 2
        assert r.returncode == 1

    def test_same_reviewer_twice_flagged_as_spoof(self, tmp_path):
        _write_xml(tmp_path / "result-1.xml", reviewer="Codex")
        _write_xml(tmp_path / "result-2.xml", reviewer="Codex")  # same name!

        r = _run(MULTI_CLI_VALIDATOR, [
            "--glob", str(tmp_path / "result-*.xml"),
            "--min-consensus", "2",
        ])
        assert r.returncode == 1
        assert "diversity" in r.stdout.lower()

    def test_require_all_enforced(self, tmp_path):
        _write_xml(tmp_path / "result-codex.xml", reviewer="Codex")
        _write_xml(tmp_path / "result-gemini.xml", reviewer="Gemini")

        # Only 2 files, require 3
        r = _run(MULTI_CLI_VALIDATOR, [
            "--glob", str(tmp_path / "result-*.xml"),
            "--min-consensus", "2", "--require-all", "3",
        ])
        assert r.returncode == 1
        assert "require_all" in r.stdout.lower() or "require 3" in r.stdout.lower()

    def test_json_output_parseable(self, tmp_path):
        _write_xml(tmp_path / "result-a.xml", reviewer="A")
        _write_xml(tmp_path / "result-b.xml", reviewer="B")

        r = _run(MULTI_CLI_VALIDATOR, [
            "--glob", str(tmp_path / "result-*.xml"),
            "--min-consensus", "2", "--json",
        ])
        data = json.loads(r.stdout)
        assert data["files_found"] == 2
        assert "consensus" in data
        assert data["consensus"]["agreement_count"] == 2

    def test_empty_glob_fails(self, tmp_path):
        r = _run(MULTI_CLI_VALIDATOR, [
            "--glob", str(tmp_path / "nonexistent-*.xml"),
            "--min-consensus", "2",
        ])
        # Empty glob produces no files_found + no consensus
        assert r.returncode == 1

    def test_malformed_xml_doesnt_count(self, tmp_path):
        _write_xml(tmp_path / "result-a.xml", reviewer="A", verdict="pass")
        (tmp_path / "result-b.xml").write_text("garbage", encoding="utf-8")

        r = _run(MULTI_CLI_VALIDATOR, [
            "--glob", str(tmp_path / "result-*.xml"),
            "--min-consensus", "2",
        ])
        # Only 1 parseable → can't reach consensus of 2
        assert r.returncode == 1
