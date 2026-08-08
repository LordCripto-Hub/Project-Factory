#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from backend_resolution import (
    BackendResolutionError,
    resolve_backend,
    resolve_profile_backend,
)


class BackendResolutionContract(unittest.TestCase):
    def test_precedence_is_explicit_profile_then_policy(self):
        self.assertEqual(
            resolve_backend(explicit="codex", profile="claude", policy="claude"),
            {"backend": "codex", "resolutionSource": "explicit"},
        )
        self.assertEqual(
            resolve_backend(explicit="", profile="codex", policy="claude"),
            {"backend": "codex", "resolutionSource": "profile"},
        )
        self.assertEqual(
            resolve_backend(explicit="", profile="", policy="claude"),
            {"backend": "claude", "resolutionSource": "routing_policy"},
        )

    def test_missing_decision_fails_closed(self):
        with self.assertRaises(BackendResolutionError) as raised:
            resolve_backend()
        self.assertEqual(raised.exception.code, "backend_unresolved")

    def test_ambiguous_same_precedence_decision_fails_closed(self):
        with self.assertRaises(BackendResolutionError) as raised:
            resolve_backend(profile=["codex", "claude"])
        self.assertEqual(raised.exception.code, "backend_ambiguous")

    def test_unsupported_backend_never_becomes_a_default(self):
        with self.assertRaises(BackendResolutionError) as raised:
            resolve_backend(explicit="ollama")
        self.assertEqual(raised.exception.code, "backend_unsupported")

    def test_existing_codex_profile_binding_is_an_explicit_source(self):
        bindings = {
            "globalProfile": "primary",
            "agentProfiles": {"node-1/main:Worker": "secondary"},
        }
        self.assertEqual(resolve_profile_backend(bindings, "node-1/main:Boss"), "codex")
        self.assertEqual(resolve_profile_backend(bindings, "node-1/main:Worker"), "codex")
        self.assertEqual(resolve_profile_backend({}, "node-1/main:Boss"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
