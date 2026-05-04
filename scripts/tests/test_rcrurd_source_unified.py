"""R7 Task 2 (G7): RCRURD source-of-truth unification.

pre-executor-check.py must extract invariants from inline yaml-rcrurd
fences in TEST-GOALS/G-NN.md (modern source). Legacy directory
RCRURD-INVARIANTS/ is supported as backward-compat fallback only.
"""
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_CHECK_PATH = REPO_ROOT / "scripts" / "pre-executor-check.py"


def _load_pre_check():
    """Load pre-executor-check.py as a module (filename has dash, can't import directly)."""
    spec = importlib.util.spec_from_file_location("pre_executor_check", PRE_CHECK_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
    spec.loader.exec_module(mod)
    return mod


SAMPLE_INLINE_FENCE_GOAL_MD = """\
# Goal G-04 — Create site

## Read-after-write invariant

```yaml-rcrurd
goal_type: mutation
read_after_write_invariant:
  write:
    method: POST
    endpoint: /api/sites
  read:
    method: GET
    endpoint: /api/sites/123
    cache_policy: no_store
    settle:
      mode: immediate
  assert:
    - path: $.name
      op: equals
      value: Test
```

## Other content here.
"""


def test_extract_from_inline_fence_modern_phase(tmp_path):
    """Modern phase: TEST-GOALS/G-NN.md has inline yaml-rcrurd fence → extracted to .yaml in cache_dir."""
    mod = _load_pre_check()
    phase_dir = tmp_path / "phase"
    (phase_dir / "TEST-GOALS").mkdir(parents=True)
    (phase_dir / "TEST-GOALS" / "G-04.md").write_text(SAMPLE_INLINE_FENCE_GOAL_MD)
    cache_dir = tmp_path / ".vg-tmp"

    result = mod.build_per_task_slices(
        phase_dir=phase_dir, task_num=1, endpoints=[], goals=["G-04"], cache_dir=cache_dir
    )

    assert "rcrurd_invariants_paths" in result
    assert len(result["rcrurd_invariants_paths"]) == 1, result
    extracted = Path(result["rcrurd_invariants_paths"][0])
    assert extracted.exists(), f"Expected extracted file at {extracted}"
    assert extracted.name == "G-04.yaml"
    assert extracted.parent.name == "rcrurd-extracted"
    body = extracted.read_text()
    assert "endpoint" in body  # canonical yaml shape


def test_legacy_dir_fallback_when_no_inline_fence(tmp_path):
    """Legacy phase: no inline fence but RCRURD-INVARIANTS/G-NN.yaml exists → use that."""
    mod = _load_pre_check()
    phase_dir = tmp_path / "phase"
    (phase_dir / "TEST-GOALS").mkdir(parents=True)
    # Goal MD without inline fence
    (phase_dir / "TEST-GOALS" / "G-04.md").write_text("# Goal G-04\n\nNo inline fence here.\n")
    # Legacy yaml file
    legacy_dir = phase_dir / "RCRURD-INVARIANTS"
    legacy_dir.mkdir()
    legacy_file = legacy_dir / "G-04.yaml"
    legacy_file.write_text("endpoint: GET /api/sites\nphases: []\n")
    cache_dir = tmp_path / ".vg-tmp"

    result = mod.build_per_task_slices(
        phase_dir=phase_dir, task_num=1, endpoints=[], goals=["G-04"], cache_dir=cache_dir
    )

    assert len(result["rcrurd_invariants_paths"]) == 1
    assert result["rcrurd_invariants_paths"][0] == str(legacy_file)


def test_no_invariant_returns_empty_list(tmp_path):
    """Goal without inline fence and no legacy file → empty list (graceful)."""
    mod = _load_pre_check()
    phase_dir = tmp_path / "phase"
    (phase_dir / "TEST-GOALS").mkdir(parents=True)
    (phase_dir / "TEST-GOALS" / "G-04.md").write_text("# Goal G-04\n\nNo invariant.\n")
    cache_dir = tmp_path / ".vg-tmp"

    result = mod.build_per_task_slices(
        phase_dir=phase_dir, task_num=1, endpoints=[], goals=["G-04"], cache_dir=cache_dir
    )
    assert result["rcrurd_invariants_paths"] == []


def test_modern_takes_precedence_over_legacy(tmp_path):
    """Both inline fence AND legacy file exist → inline fence wins (modern source)."""
    mod = _load_pre_check()
    phase_dir = tmp_path / "phase"
    (phase_dir / "TEST-GOALS").mkdir(parents=True)
    (phase_dir / "TEST-GOALS" / "G-04.md").write_text(SAMPLE_INLINE_FENCE_GOAL_MD)
    legacy_dir = phase_dir / "RCRURD-INVARIANTS"
    legacy_dir.mkdir()
    (legacy_dir / "G-04.yaml").write_text("endpoint: LEGACY\nphases: []\n")
    cache_dir = tmp_path / ".vg-tmp"

    result = mod.build_per_task_slices(
        phase_dir=phase_dir, task_num=1, endpoints=[], goals=["G-04"], cache_dir=cache_dir
    )

    assert len(result["rcrurd_invariants_paths"]) == 1
    extracted = Path(result["rcrurd_invariants_paths"][0])
    assert extracted.parent.name == "rcrurd-extracted", "Should use inline-extracted, not legacy"


def test_doc_clarifies_single_source_of_truth():
    """rcrurdr-overview.md must document inline fences as canonical (R7 Task 2 fix for G7)."""
    doc = (REPO_ROOT / "commands/vg/_shared/blueprint/rcrurdr-overview.md").read_text()
    assert "single source of truth" in doc.lower() or "Single source of truth" in doc
    assert "R7 Task 2" in doc
    assert "G7" in doc
