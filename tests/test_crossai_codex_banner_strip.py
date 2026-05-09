"""v2.66.0 Task 4 (#155) — Strip Codex CLI banner before writing result XML.

Issue: scripts/crossai-runner.py wrote raw stdout to result-codex-rN.xml.
Codex CLI emits a banner (`Reading additional input from stdin...` /
`OpenAI Codex v0.118.0 (research preview)` / two `--------` separators
sandwiching `workdir:` + `model:` + `provider:` / a `user` line / the prompt
echo) BEFORE the model output. So the result file starts with banner, not
`<crossai_review>`, breaking the downstream XML extractor.

Fix: introduce `_strip_codex_banner(text)` helper. Wire into the write call
just before persisting stdout.
"""
import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


def _import_runner():
    spec_path = REPO_ROOT / "scripts" / "crossai-runner.py"
    spec = importlib.util.spec_from_file_location("crossai_runner", spec_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["crossai_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_codex_banner_stripped_before_xml():
    """Codex banner lines must be stripped before writing result-codex-rN.xml."""
    mod = _import_runner()
    raw = (
        "Reading additional input from stdin...\n"
        "OpenAI Codex v0.118.0 (research preview)\n"
        "--------\n"
        "workdir: /tmp/x\n"
        "model: gpt-5.4\n"
        "provider: openai\n"
        "--------\n"
        "user\n"
        "Review the artifacts and emit crossai_review XML.\n"
        "<crossai_review>\n"
        "  <verdict>pass</verdict>\n"
        "</crossai_review>\n"
    )
    cleaned = mod._strip_codex_banner(raw)
    assert cleaned.lstrip().startswith("<crossai_review>"), (
        f"Banner not stripped — output should start with <crossai_review>: {cleaned[:200]!r}"
    )


def test_non_codex_output_unchanged():
    """Claude/Gemini outputs (no banner) must pass through unchanged."""
    mod = _import_runner()
    raw = "<crossai_review>\n  <verdict>pass</verdict>\n</crossai_review>\n"
    assert mod._strip_codex_banner(raw) == raw, (
        "Non-Codex output must pass through byte-identical"
    )


def test_banner_only_content_yields_empty():
    """If output is ONLY banner (no actual model output), return empty/sentinel."""
    mod = _import_runner()
    raw = (
        "Reading additional input from stdin...\n"
        "OpenAI Codex v0.118.0 (research preview)\n"
        "--------\n"
        "workdir: /tmp/x\n"
        "--------\n"
    )
    cleaned = mod._strip_codex_banner(raw)
    assert not cleaned.strip(), (
        f"Banner-only output should clean to empty/whitespace: {cleaned!r}"
    )
