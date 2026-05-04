"""Static check: refactored build entry + refs use vg-load instead of flat
PLAN.md / API-CONTRACTS.md / TEST-GOALS.md reads in AI-context paths.

Audit doc docs/audits/2026-05-04-build-flat-vs-split.md classified only 3
backup lines as MIGRATE (entry line 162 + refs lines 783, 1232). After
refactor, those are replaced with vg-load. Remaining flat references
in refs are KEEP-FLAT (deterministic transforms: ls/grep/wc/stat/mtime
checks) which do not match this regex (regex only catches `Read` and
`cat`-into-AI-context, not `ls`/`grep`/`stat`)."""
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]
ENTRY = REPO / "commands/vg/build.md"
REFS_DIR = REPO / "commands/vg/_shared/build"

# Per-file KEEP-FLAT line allow-lists. Empty by default — expand per audit
# if the regex below ever flags a legitimate KEEP-FLAT case (none expected
# at R2 ship; documented for future maintainers).
ALLOWED_FLAT_LINES = {
    # "ref-name.md": {line_no, ...},
}

FLAT_PATTERN = re.compile(
    r"(cat\s+[\"']?\$\{?PHASE_DIR\}?[/\"']?(?:PLAN|API-CONTRACTS|TEST-GOALS)\.md"
    r"|Read\s+\S*(?:PLAN|API-CONTRACTS|TEST-GOALS)\.md)"
)


def _flat_reads(path: Path):
    text = path.read_text()
    for i, line in enumerate(text.splitlines(), 1):
        if FLAT_PATTERN.search(line):
            yield i, line.strip()


def test_entry_or_refs_reference_vg_load():
    """vg-load helper must be referenced somewhere in the build pipeline.
    Entry slim form delegates the actual loads to refs, so this test
    accepts a mention in entry OR in refs (either places it correctly)."""
    found_entry = "vg-load" in ENTRY.read_text()
    found_refs = any("vg-load" in ref.read_text() for ref in REFS_DIR.glob("*.md"))
    assert found_entry or found_refs, "neither build.md entry nor _shared/build/ refs reference vg-load helper"


def test_refs_reference_vg_load():
    """At least one ref must invoke vg-load (executor capsule + plan discovery)."""
    found = False
    for ref in REFS_DIR.glob("*.md"):
        if "vg-load" in ref.read_text():
            found = True
            break
    assert found, "no ref under _shared/build/ references vg-load"


def test_no_unaudited_flat_reads():
    """Every flat read in slim entry + refs must be in audit allow-list.

    Per audit doc docs/audits/2026-05-04-build-flat-vs-split.md, all 3
    MIGRATE lines from the backup were replaced during refactor. ZERO
    flat reads of the cat/Read variety should remain in AI-context paths."""
    failures = []
    for path in [ENTRY, *sorted(REFS_DIR.glob("*.md"))]:
        allowed = ALLOWED_FLAT_LINES.get(path.name, set())
        for n, snippet in _flat_reads(path):
            if n not in allowed:
                failures.append(f"  {path.relative_to(REPO)}:{n}: {snippet}")
    assert not failures, (
        "Unaudited flat reads detected (see docs/audits/2026-05-04-build-flat-vs-split.md):\n"
        + "\n".join(failures)
    )
