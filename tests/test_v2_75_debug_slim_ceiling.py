"""v2.75.0 T9 — verify slim debug.md is under ceiling + sub-files exist + routing complete."""
from pathlib import Path


def test_debug_md_under_slim_ceiling():
    body = Path("commands/vg/debug.md").read_text(encoding="utf-8")
    line_count = len(body.splitlines())
    assert line_count <= 200, (
        f"commands/vg/debug.md is {line_count} lines — ceiling is 200 after v2.75.0 T6-T8 "
        f"extraction (was 570 lines pre-v2.75.0)."
    )


def test_shared_debug_dir_has_3_files():
    md_files = sorted(Path("commands/vg/_shared/debug").glob("*.md"))
    assert len(md_files) >= 3, (
        f"commands/vg/_shared/debug/ must have at least 3 .md files after v2.75.0 T6-T8 "
        f"split (got {len(md_files)})."
    )


def test_debug_md_routes_to_each_subfile():
    body = Path("commands/vg/debug.md").read_text(encoding="utf-8")
    expected = ["preflight.md", "discovery-and-fix.md", "verify-and-close.md"]
    missing = [s for s in expected if f"_shared/debug/{s}" not in body]
    assert not missing, (
        f"commands/vg/debug.md missing routing references to: {missing}"
    )


def test_debug_md_mirror_byte_identity_after_split():
    canonical = Path("commands/vg/debug.md").read_bytes()
    mirror = Path(".claude/commands/vg/debug.md").read_bytes()
    assert canonical == mirror, "commands/vg/debug.md mirrors must be byte-identical"


def test_shared_debug_dir_mirror_byte_identity():
    canonical_dir = Path("commands/vg/_shared/debug")
    mirror_dir = Path(".claude/commands/vg/_shared/debug")
    canonical_files = sorted(p.name for p in canonical_dir.glob("*.md"))
    mirror_files = sorted(p.name for p in mirror_dir.glob("*.md"))
    assert canonical_files == mirror_files, (
        f"_shared/debug/ file lists must match. Canonical={canonical_files} Mirror={mirror_files}"
    )
    for name in canonical_files:
        c = (canonical_dir / name).read_bytes()
        m = (mirror_dir / name).read_bytes()
        assert c == m, f"_shared/debug/{name} must be byte-identical between canonical and mirror"
