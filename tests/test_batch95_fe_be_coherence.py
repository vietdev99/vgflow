"""B95 v4.68.0 — issue #197 build-gate proposal + Gemini TLS docs.

Final batch closing the cross-cutting half of issue #197 (8 generator
findings already closed in B90-B94).

Ships:
  - `scripts/validators/verify-fe-be-shape-coherence.py` — static AST-lite
    heuristic for FE-BE response shape drift. ADVISORY (severity=warn).
    Three heuristics: H1 mixed `_id`/`id` field access, H2 mixed `.rows`/
    `.data` envelope deref, H3 useParams<{X}> name mismatch with route
    `:param` declaration in same file.
  - `scripts/validators/registry.yaml` entry `fe-be-shape-coherence`.
  - `docs/tooling/gemini-cli-tls-troubleshooting.md` — NODE_EXTRA_CA_CERTS
    setup for corporate TLS-intercepting environments. Closes CrossAI
    vote INCONCLUSIVE when behind ZScaler/corp proxy.

Runtime 1-GET-per-FE-route check (full build-gate proposal from issue
#197) deferred — needs dev server + route map. Static heuristic catches
the highest-frequency F-ROAM-01..06 patterns at build time. Wiring into
build/close.md gate is the operator's opt-in (registry severity=warn).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validators" / "verify-fe-be-shape-coherence.py"
MIRROR = REPO_ROOT / ".claude" / "scripts" / "validators" / "verify-fe-be-shape-coherence.py"
REGISTRY = REPO_ROOT / "scripts" / "validators" / "registry.yaml"
TLS_DOC = REPO_ROOT / "docs" / "tooling" / "gemini-cli-tls-troubleshooting.md"


def _run(tmp_path: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(tmp_path), *extra],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8", errors="replace",
    )


def _seed(tmp_path: Path, app: str, files: dict[str, str]) -> None:
    src = tmp_path / "apps" / app / "src"
    src.mkdir(parents=True)
    for name, body in files.items():
        (src / name).write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Heuristic H1 — mixed _id / id
# ---------------------------------------------------------------------------

def test_b95_h1_mixed_id_field_detected(tmp_path: Path) -> None:
    _seed(tmp_path, "admin", {
        "TopupList.tsx": """
const renderRow = (data) => {
  return <span key={data._id}>{data.id}</span>;
};
""",
    })
    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr  # warn mode
    out = json.loads(proc.stdout)
    assert out["status"] == "FAIL"
    assert out["by_heuristic"]["H1"] == 1


def test_b95_h1_only_id_no_finding(tmp_path: Path) -> None:
    _seed(tmp_path, "admin", {
        "TopupList.tsx": "const x = (data) => data.id;",
    })
    proc = _run(tmp_path)
    out = json.loads(proc.stdout)
    assert out["by_heuristic"]["H1"] == 0


# ---------------------------------------------------------------------------
# Heuristic H2 — mixed .rows / .data envelope
# ---------------------------------------------------------------------------

def test_b95_h2_mixed_envelope_detected(tmp_path: Path) -> None:
    _seed(tmp_path, "admin", {
        "Service.ts": """
async function fetchTopups() {
  const response = await api.get('/topups');
  const list = response.rows;
  const meta = response.data;
  return { list, meta };
}
""",
    })
    proc = _run(tmp_path)
    out = json.loads(proc.stdout)
    assert out["by_heuristic"]["H2"] == 1


# ---------------------------------------------------------------------------
# Heuristic H3 — useParams<{X}> vs route :param mismatch
# ---------------------------------------------------------------------------

def test_b95_h3_useparams_mismatch_detected(tmp_path: Path) -> None:
    _seed(tmp_path, "admin", {
        "BlueprintDetail.tsx": """
const routes = [
  { path: '/blueprints/:id', component: BlueprintDetail },
];
function BlueprintDetail() {
  const { blueprintId } = useParams<{ blueprintId: string }>();
  return <div>{blueprintId}</div>;
}
""",
    })
    proc = _run(tmp_path)
    out = json.loads(proc.stdout)
    assert out["by_heuristic"]["H3"] == 1


def test_b95_h3_matched_no_finding(tmp_path: Path) -> None:
    _seed(tmp_path, "admin", {
        "BlueprintDetail.tsx": """
const routes = [
  { path: '/blueprints/:id', component: BlueprintDetail },
];
function BlueprintDetail() {
  const { id } = useParams<{ id: string }>();
  return <div>{id}</div>;
}
""",
    })
    proc = _run(tmp_path)
    out = json.loads(proc.stdout)
    assert out["by_heuristic"]["H3"] == 0


# ---------------------------------------------------------------------------
# Severity gate
# ---------------------------------------------------------------------------

def test_b95_severity_block_fails_on_finding(tmp_path: Path) -> None:
    _seed(tmp_path, "admin", {
        "x.tsx": "const a = data._id; const b = data.id;",
    })
    proc = _run(tmp_path, "--severity", "block")
    assert proc.returncode == 1


def test_b95_severity_warn_exits_zero_with_finding(tmp_path: Path) -> None:
    _seed(tmp_path, "admin", {
        "x.tsx": "const a = data._id; const b = data.id;",
    })
    proc = _run(tmp_path, "--severity", "warn")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Empty repo
# ---------------------------------------------------------------------------

def test_b95_empty_repo_passes(tmp_path: Path) -> None:
    proc = _run(tmp_path)
    out = json.loads(proc.stdout)
    assert out["status"] == "PASS"
    assert out["scanned"] == 0


# ---------------------------------------------------------------------------
# Registry + docs presence
# ---------------------------------------------------------------------------

def test_b95_registry_has_entry() -> None:
    body = REGISTRY.read_text(encoding="utf-8")
    assert "id: fe-be-shape-coherence" in body
    sp_idx = body.index("id: fe-be-shape-coherence")
    region = body[sp_idx:sp_idx + 800]
    assert "severity: warn" in region
    assert "added_in: v4.68.0" in region


def test_b95_gemini_tls_doc_exists() -> None:
    assert TLS_DOC.is_file()
    body = TLS_DOC.read_text(encoding="utf-8")
    assert "NODE_EXTRA_CA_CERTS" in body
    assert "self-signed certificate in certificate chain" in body
    assert "loadCodeAssist" in body


# ---------------------------------------------------------------------------
# Mirror parity
# ---------------------------------------------------------------------------

def test_b95_validator_mirror_byte_identical() -> None:
    assert VALIDATOR.read_bytes() == MIRROR.read_bytes()


def test_b95_registry_mirror_byte_identical() -> None:
    mirror = REPO_ROOT / ".claude" / "scripts" / "validators" / "registry.yaml"
    assert REGISTRY.read_bytes() == mirror.read_bytes()
