#!/usr/bin/env python3
"""env_policy.py — per-environment constraints for v2.40 recursive lens probe.

Returns a policy dict (allow_mutations, mutation_budget, allowed_lenses)
keyed off the deploy environment. spawn_recursive_probe.py and
review_batch.py read this to filter the lens plan + cap mutation count
before any worker dispatch.

Environments:
  local    — developer laptop. Everything on, unlimited budget.
  sandbox  — disposable VPS. Everything on, 50-mutation budget.
  staging  — pre-prod. Drops untrusted-input mutation lenses (input-injection),
             keeps the rest at a 25-mutation budget.
  prod     — read-only. Only safe observational lenses (info-disclosure,
             auth-jwt token shape). No mutations whatsoever.

Tasks 26b implements the policy table; Task 26c wires it into
spawn_recursive_probe.py via --target-env.
"""
from __future__ import annotations

from typing import Any

# 16 lens names — kept in sync with commands/vg/_shared/lens-prompts/.
LENS_CATALOG: frozenset[str] = frozenset({
    "lens-idor",
    "lens-authz-negative",
    "lens-tenant-boundary",
    "lens-bfla",
    "lens-input-injection",
    "lens-mass-assignment",
    "lens-path-traversal",
    "lens-file-upload",
    "lens-auth-jwt",
    "lens-csrf",
    "lens-duplicate-submit",
    "lens-business-logic",
    "lens-ssrf",
    "lens-info-disclosure",
    "lens-modal-state",
    "lens-open-redirect",
})

# Lenses that are safe to fire even against a live production environment
# because they only OBSERVE responses (no state mutation, no side-effects
# beyond a benign GET). Staging strips input-injection because that lens
# explicitly fuzzes payloads and could pollute shared QA data. Prod is
# the strictest: only the two pure observers.
_SAFE_PROD_LENSES: frozenset[str] = frozenset({
    "lens-info-disclosure",
    "lens-auth-jwt",
})

_INPUT_INJECTION_LENSES: frozenset[str] = frozenset({
    "lens-input-injection",
})


def policy_for(env: str) -> dict[str, Any]:
    """Return the constraint dict for ``env``.

    Raises ``ValueError`` for unknown environments — caller must fail
    loudly rather than silently fall back to a permissive default.
    """
    if env == "local":
        return {
            "env": "local",
            "allow_mutations": True,
            "mutation_budget": -1,                  # unlimited
            "allowed_lenses": set(LENS_CATALOG),
        }

    if env == "sandbox":
        return {
            "env": "sandbox",
            "allow_mutations": True,
            "mutation_budget": 50,
            "allowed_lenses": set(LENS_CATALOG),
        }

    if env == "staging":
        return {
            "env": "staging",
            "allow_mutations": True,
            "mutation_budget": 25,
            "allowed_lenses": set(LENS_CATALOG) - _INPUT_INJECTION_LENSES,
        }

    if env == "prod":
        return {
            "env": "prod",
            "allow_mutations": False,
            "mutation_budget": 0,
            "allowed_lenses": set(_SAFE_PROD_LENSES),
        }

    raise ValueError(
        f"unknown env {env!r}; expected one of: local, sandbox, staging, prod"
    )


__all__ = ["LENS_CATALOG", "policy_for"]
