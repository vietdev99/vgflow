"""Root-verifier unit tests (Phase I, harness v2.6).

Backfills coverage for 13 UNQUARANTINABLE/BLOCK-severity validators that the
v2.6.1 CI pytest gate runs but had no actual coverage. Each test file
exercises 5-8 cases per verifier, scoped to ``tmp_path`` via ``VG_REPO_ROOT``.
"""
