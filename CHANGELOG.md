# Changelog

All notable changes to VG workflow documented here. Format follows [Keep a Changelog](https://keepachangelog.com/), adheres to [SemVer](https://semver.org/).

## [1.1.0] - 2026-04-17

### Added
- `/vg:update` command — pull latest release from GitHub, 3-way merge with local edits, park conflicts in `.claude/vgflow-patches/`
- `/vg:reapply-patches` command — interactive per-conflict resolution (edit / keep-upstream / restore-local / skip)
- `scripts/vg_update.py` — Python helper implementing SemVer compare, SHA256 verify, 3-way merge via `git merge-file`, patches manifest persistence, GitHub release API query
- `/vg:progress` version banner — shows installed VG version + daily update check (lazy-cached)
- `migrations/template.md` — template for breaking-change migration guides
- Release tarball auto-build: GitHub Action builds + attaches `vgflow-vX.Y.Z.tar.gz` + `.sha256` per tag

### Fixed
- Windows Python text mode CRLF translation in 3-way merge tmp file (caused false conflicts against LF-terminated ancestor files)

## [1.0.0] - 2026-04-17

### Added
- Initial public release of VGFlow
- 6-step pipeline: scope → blueprint → build → review → test → accept
- Config-driven engine via `vg.config.md` — zero hardcoded stack values
- `install.sh` for fresh project install
- `sync.sh` for dev-side source↔mirror sync
- Claude Code commands (`commands/vg/`) + shared helpers
- Codex CLI skills parity (`codex-skills/vg-review`, `vg-test`)
- Gemini CLI skills parity (`gemini-skills/`)
- Python scripts for graphify, caller graph, visual diff, phase recon
- Commit-msg hook template enforcing citation + SemVer task IDs
- Infrastructure: override debt register, i18n narration, telemetry, security register, visual regression, incremental graphify
