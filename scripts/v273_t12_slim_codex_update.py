"""v2.73.0 T12 — slim codex-skills/vg-update/SKILL.md.

Replaces inline <step name="X">...</step> blocks inside <process>...</process>
with slim routing entries that read from `_shared/update/*.md`.

Mirrors the v2.73.0 T5 strategy used for vg-deploy
(scripts/v273_t5_slim_codex_deploy.py).
"""
from pathlib import Path
import re


UPDATE_GROUPS = [
    {
        "title": "### Preflight section (extracted v2.73.0 T6)",
        "shared": "_shared/update/preflight.md",
        "steps": ["0_preflight", "1_check_only_mode"],
        "blurb": (
            "Includes 2 steps: 0_preflight (verify git/curl/python3 + helper "
            "script present, parse --repo= flag) and 1_check_only_mode (handle "
            "--check flag — print version state + exit)."
        ),
        "codex_note": None,
    },
    {
        "title": "### Version + changelog (extracted v2.73.0 T7)",
        "shared": "_shared/update/version-and-changelog.md",
        "steps": ["2_version_compare", "3_changelog_preview", "4_breaking_gate"],
        "blurb": (
            "Includes 3 steps: 2_version_compare (query latest release via helper, "
            "parse installed/latest/state), 3_changelog_preview (fetch + filter "
            "CHANGELOG entries between installed and latest, ask user to confirm "
            "via AskUserQuestion), and 4_breaking_gate (major-bump opt-in via "
            "--accept-breaking + migration doc display + deep compat scan)."
        ),
        "codex_note": (
            "CODEX NOTE: Step 3's confirmation prompt uses AskUserQuestion on "
            "Claude. On Codex, ask the same Yes/No question inline in the main "
            "Codex thread per the adapter contract above (Tool mapping table)."
        ),
    },
    {
        "title": "### Fetch + merge (extracted v2.73.0 T8)",
        "shared": "_shared/update/fetch-and-merge.md",
        "steps": [
            "5_fetch_tarball",
            "6_three_way_merge_per_file",
            "6b_verify_gate_integrity",
        ],
        "blurb": (
            "Includes 3 steps: 5_fetch_tarball (download + verify SHA256 + "
            "extract via helper, self-bootstrap to upstream vg_update.py), "
            "6_three_way_merge_per_file (walk extracted tree, 3-way merge each "
            "file vs ancestor, park conflicts to .claude/vgflow-patches/, "
            "force-upstream when ancestor missing, refuse VERSION bump on core "
            "update-tooling drift), and 6b_verify_gate_integrity (T8 hard-gate "
            "manifest re-hash + diff, soft-skip on pre-v1.8.0 404)."
        ),
        "codex_note": None,
    },
    {
        "title": "### Rotate + repair (extracted v2.73.0 T9)",
        "shared": "_shared/update/rotate-and-repair.md",
        "steps": ["7_rotate_ancestor_and_version", "7b_repair_hooks"],
        "blurb": (
            "Includes 2 steps: 7_rotate_ancestor_and_version (remove old "
            "ancestor stash, move extracted upstream into new vgflow-ancestor/"
            "v{LATEST}, atomic VGFLOW-VERSION bump) and 7b_repair_hooks "
            "(re-install Claude hooks via install-hooks.sh + prune legacy VG "
            "entries from settings.local.json to prevent v2.50.x double-hook "
            "drift)."
        ),
        "codex_note": None,
    },
    {
        "title": "### Sync + report (extracted v2.73.0 T10 — final)",
        "shared": "_shared/update/sync-and-report.md",
        "steps": [
            "8_sync_codex",
            "8b_repair_playwright_mcp",
            "8c_ensure_graphify",
            "9_report",
        ],
        "blurb": (
            "Includes 4 closing steps: 8_sync_codex (deploy Codex skills + "
            "agents + templates from rotated release ancestor into .codex/, "
            "optional global ~/.codex via VG_UPDATE_GLOBAL_CODEX=1, verify "
            "mirror equivalence), 8b_repair_playwright_mcp (verify/repair "
            "playwright1-5 MCP workers via verify-playwright-mcp-config.py), "
            "8c_ensure_graphify (verify/install Graphify tooling when "
            "graphify.enabled=true, soft-fail), and 9_report (final counts + "
            "NEXT_ACTION directive when conflicts parked, restart reminder)."
        ),
        "codex_note": (
            "CODEX NOTE: The final report's AI directive (`▶ NEXT_ACTION="
            "/vg:reapply-patches[ --verify-gates]`) is runtime-agnostic — "
            "Codex MUST chain into /vg:reapply-patches in the next turn when "
            "CONFLICTS > 0 OR gate-conflicts.md exists, without waiting for "
            "a fresh user prompt (matches Claude behavior)."
        ),
    },
]


def slim_step_blocks(text: str, groups: list) -> str:
    """Replace each step block listed in `groups` with a slim routing entry."""
    step_to_group = {}
    for gi, g in enumerate(groups):
        for s in g["steps"]:
            step_to_group[s] = gi

    emitted = set()
    output_chunks = []
    pos = 0
    pattern = re.compile(r'<step name="([^"]+)">', re.MULTILINE)
    last_known_group = None

    while True:
        m = pattern.search(text, pos)
        if not m:
            output_chunks.append(text[pos:])
            break
        step_name = m.group(1)
        close_idx = text.find("</step>", m.end())
        if close_idx == -1:
            raise RuntimeError(f"Unclosed <step name='{step_name}'>")
        close_end = close_idx + len("</step>")

        gi = step_to_group.get(step_name)

        between = text[pos:m.start()]
        if last_known_group is not None and gi == last_known_group:
            # Same group — drop interstitial prose
            pass
        else:
            output_chunks.append(between)

        if gi is None:
            output_chunks.append(text[m.start():close_end])
            last_known_group = None
        else:
            if gi not in emitted:
                g = groups[gi]
                steps_csv = ", ".join(g["steps"])
                routing = (
                    f"{g['title']}\n\n"
                    f"Read `{g['shared']}` and follow it exactly.\n"
                    f"{g['blurb']}\n\n"
                    f"Step coverage: {steps_csv}.\n"
                )
                if g.get("codex_note"):
                    routing += f"\n{g['codex_note']}\n"
                output_chunks.append(routing)
                emitted.add(gi)
            last_known_group = gi

        pos = close_end
        while pos < len(text) and text[pos] == "\n":
            pos += 1
        output_chunks.append("\n")

    return "".join(output_chunks)


def slim_file(path: Path, groups: list) -> tuple[int, int]:
    original = path.read_text(encoding="utf-8")
    before = len(original.splitlines())
    new_text = slim_step_blocks(original, groups)
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    path.write_text(new_text, encoding="utf-8")
    after = len(new_text.splitlines())
    return before, after


def main() -> None:
    before, after = slim_file(
        Path("codex-skills/vg-update/SKILL.md"), UPDATE_GROUPS
    )
    print(f"vg-update: {before} -> {after} lines")


if __name__ == "__main__":
    main()
