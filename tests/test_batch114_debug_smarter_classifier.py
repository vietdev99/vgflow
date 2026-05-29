"""B114 v4.73.0 — smarter classifier + cross-symptom probe + graphify.

Tests cover:
  - debug_classifier scoring + confidence + alternates
  - debug_probe expand_sibling_routes against synthetic apps/
  - debug_probe graphify_neighbors graceful absence
  - debug_probe stack_trace_hash deterministic
  - preflight.md + discovery-and-fix.md wiring strings present
  - Mirror parity for new files
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def classifier():
    spec = importlib.util.spec_from_file_location(
        "debug_classifier", REPO_ROOT / "scripts" / "lib" / "debug_classifier.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probe():
    spec = importlib.util.spec_from_file_location(
        "debug_probe", REPO_ROOT / "scripts" / "lib" / "debug_probe.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Classifier scoring
# ---------------------------------------------------------------------------

def test_b114_classifier_network_500_wins_over_ui(classifier) -> None:
    """form submit 500 → network (status code outranks form keyword)."""
    v = classifier.classify("form submit POST /api/users returned 500")
    assert v["bug_type"] == "network"
    assert v["confidence"] >= 60
    assert "500" in str(v["evidence"].get("network", []))


def test_b114_classifier_ui_dropdown_empty(classifier) -> None:
    v = classifier.classify("dropdown trên trang /campaigns không hiển thị options")
    assert v["bug_type"] == "runtime_ui"
    assert v["probe_siblings_enabled"] is True


def test_b114_classifier_static_typeerror(classifier) -> None:
    v = classifier.classify(
        "TypeError: cannot read property 'id' of undefined at UserList.tsx:42"
    )
    assert v["bug_type"] == "static"
    assert v["confidence"] >= 80


def test_b114_classifier_spec_gap_vietnamese(classifier) -> None:
    v = classifier.classify("chưa có UI for bulk export tính năng")
    assert v["bug_type"] == "spec_gap"


def test_b114_classifier_infra_env(classifier) -> None:
    v = classifier.classify("ECONNREFUSED port 5432 cannot connect to db")
    assert v["bug_type"] in ("infra", "network")
    assert v["confidence"] >= 50


def test_b114_classifier_empty_returns_ambiguous(classifier) -> None:
    v = classifier.classify("")
    assert v["bug_type"] == "ambiguous"
    assert v["needs_clarification"] is True


def test_b114_classifier_emits_alternates_on_close_call(classifier) -> None:
    """Multi-signal text should surface alternates."""
    v = classifier.classify(
        "click form button on /users page sends POST returns 502 bad gateway"
    )
    assert len(v["alternates"]) >= 1


def test_b114_classifier_evidence_trail_populated(classifier) -> None:
    v = classifier.classify("timeout when calling /api/v1/users with axios")
    assert "network" in v["evidence"]
    assert len(v["evidence"]["network"]) >= 1


def test_b114_classifier_probe_flag_off_for_static(classifier) -> None:
    v = classifier.classify("TypeError null is not an object at line 5")
    assert v["probe_siblings_enabled"] is False


def test_b114_classifier_threshold_default_80(classifier) -> None:
    """Low-confidence input triggers needs_clarification=True."""
    v = classifier.classify("something weird happened")
    assert v["needs_clarification"] is True


# ---------------------------------------------------------------------------
# Probe — sibling routes
# ---------------------------------------------------------------------------

def test_b114_probe_expand_siblings_finds_other_routes(probe, tmp_path: Path) -> None:
    """Synthetic apps tree with /campaigns + /users + /products."""
    app = tmp_path / "apps" / "web" / "src" / "pages"
    app.mkdir(parents=True)
    for route in ("campaigns", "users", "products", "settings"):
        (app / route).mkdir()
    siblings = probe.expand_sibling_routes("/campaigns", tmp_path)
    assert "/users" in siblings
    assert "/products" in siblings
    assert "/campaigns" not in siblings  # exclude self


def test_b114_probe_expand_siblings_empty_on_unknown(probe, tmp_path: Path) -> None:
    assert probe.expand_sibling_routes("unknown", tmp_path) == []
    assert probe.expand_sibling_routes("", tmp_path) == []


def test_b114_probe_expand_siblings_caps_at_max(probe, tmp_path: Path) -> None:
    app = tmp_path / "apps" / "web" / "src" / "pages"
    app.mkdir(parents=True)
    for i in range(20):
        (app / f"route{i}").mkdir()
    (app / "campaigns").mkdir()
    siblings = probe.expand_sibling_routes("/campaigns", tmp_path, max_siblings=4)
    assert len(siblings) <= 4


# ---------------------------------------------------------------------------
# Probe — graphify
# ---------------------------------------------------------------------------

def test_b114_probe_graphify_missing_graph_returns_empty(
    probe, tmp_path: Path
) -> None:
    """No graphify-out/graph.json → empty list, no exception."""
    out = probe.graphify_neighbors("some symptom", tmp_path)
    assert out == []


def test_b114_probe_graphify_parses_markdown_citations(probe) -> None:
    text = """
- [UserService] (apps/api/src/UserService.ts) — handles user CRUD
- [Login] (apps/web/src/pages/login.tsx)
"""
    result = probe._parse_graphify_output(text)
    assert len(result) == 2
    assert result[0]["node"] == "UserService"


def test_b114_probe_graphify_parses_json_block(probe) -> None:
    text = """
```json
[{"node": "Foo", "path": "x.ts", "edge": "calls"}]
```
"""
    result = probe._parse_graphify_output(text)
    assert len(result) == 1
    assert result[0]["node"] == "Foo"


# ---------------------------------------------------------------------------
# Probe — stack trace hash
# ---------------------------------------------------------------------------

def test_b114_probe_stack_hash_deterministic(probe) -> None:
    stack = """
TypeError: Cannot read property 'id' of undefined
    at UserList (apps/web/src/UserList.tsx:42:18)
    at renderWithHooks (node_modules/react-dom/index.js:1234:21)
    at mountIndeterminateComponent (node_modules/react-dom/index.js:5678:5)
"""
    h1 = probe.stack_trace_hash(stack)
    h2 = probe.stack_trace_hash(stack)
    assert h1 is not None
    assert h1 == h2
    assert len(h1) == 16


def test_b114_probe_stack_hash_normalizes_absolute_paths(probe) -> None:
    """Same stack with different abs prefix → same hash."""
    stack1 = "at UserList (/home/user/repo/apps/web/src/UserList.tsx:42)"
    stack2 = "at UserList (D:\\workspace\\repo\\apps\\web\\src\\UserList.tsx:42)"
    h1 = probe.stack_trace_hash(stack1)
    h2 = probe.stack_trace_hash(stack2)
    assert h1 is not None
    assert h1 == h2


def test_b114_probe_stack_hash_empty_returns_none(probe) -> None:
    assert probe.stack_trace_hash("no frames here") is None
    assert probe.stack_trace_hash("") is None


def test_b114_probe_scan_related_errors_finds_match(
    probe, tmp_path: Path
) -> None:
    log = tmp_path / "error.log"
    log.write_text(
        "2026-05-30 ERROR\n"
        "    at handleClick (apps/web/src/Foo.tsx:10:5)\n"
        "    at onClick (apps/web/src/Bar.tsx:20:5)\n"
        "    at fireEvent (apps/web/src/Baz.tsx:30:5)\n",
        encoding="utf-8",
    )
    stack = (
        "at handleClick (apps/web/src/Foo.tsx:10:5)\n"
        "at onClick (apps/web/src/Bar.tsx:20:5)\n"
        "at fireEvent (apps/web/src/Baz.tsx:30:5)"
    )
    h = probe.stack_trace_hash(stack)
    matches = probe.scan_related_errors(h, [log])
    assert len(matches) >= 1


# ---------------------------------------------------------------------------
# Wiring in markdown skills
# ---------------------------------------------------------------------------

def test_b114_preflight_invokes_classifier_script() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "debug" / "preflight.md").read_text(encoding="utf-8")
    assert ".claude/scripts/lib/debug_classifier.py" in body
    assert "PROBE_SIBLINGS" in body


def test_b114_preflight_invokes_probe_script_for_siblings() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "debug" / "preflight.md").read_text(encoding="utf-8")
    assert "debug_probe.py expand" in body
    assert "debug_probe.py graphify" in body


def test_b114_discovery_consumes_sibling_routes_json() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "debug" / "discovery-and-fix.md").read_text(encoding="utf-8")
    assert "sibling_routes.json" in body
    assert "B114 cross-symptom probe" in body


def test_b114_discovery_includes_stack_hash_block() -> None:
    body = (REPO_ROOT / "commands" / "vg" / "_shared" / "debug" / "discovery-and-fix.md").read_text(encoding="utf-8")
    assert "debug_probe.py hash" in body
    assert "scan_related_errors" in body


# ---------------------------------------------------------------------------
# Mirror parity (every canonical → .claude/ mirror)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "scripts/lib/debug_classifier.py",
    "scripts/lib/debug_probe.py",
    "commands/vg/_shared/debug/preflight.md",
    "commands/vg/_shared/debug/discovery-and-fix.md",
])
def test_b114_mirror_parity(rel: str) -> None:
    a = (REPO_ROOT / rel).read_bytes()
    b = (REPO_ROOT / ".claude" / rel).read_bytes()
    assert a == b, f"Mirror drift on {rel}"
