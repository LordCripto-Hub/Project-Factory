#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "provider_profiles", ROOT / "bin" / "provider_profiles.py"
)
provider_profiles = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provider_profiles)


class ProviderProfileContract(unittest.TestCase):
    def test_profile_id_rejects_path_and_shell_characters(self):
        for value in ("../bad", "bad/name", "bad name", "bad;name", ""):
            with self.assertRaises(ValueError):
                provider_profiles.validate_profile_id(value)
        self.assertEqual(
            provider_profiles.validate_profile_id("codex-primary"),
            "codex-primary",
        )

    def test_agent_override_precedes_global_binding(self):
        bindings = {
            "globalProfile": "codex-primary",
            "agentProfiles": {"node-1/main:Engineer-1": "codex-secondary"},
        }
        self.assertEqual(
            provider_profiles.resolve_profile(bindings, "node-1/main:Boss"),
            "codex-primary",
        )
        self.assertEqual(
            provider_profiles.resolve_profile(bindings, "node-1/main:Engineer-1"),
            "codex-secondary",
        )

    def test_role_model_resolution_is_deterministic(self):
        profile = {
            "defaultModel": "gpt-5.6-luna",
            "roleModels": {"boss": "gpt-5.6-sol"},
        }
        self.assertEqual(
            provider_profiles.resolve_model(profile, "boss"), "gpt-5.6-sol"
        )
        self.assertEqual(
            provider_profiles.resolve_model(profile, "engineer"), "gpt-5.6-luna"
        )

    def test_codex_home_stays_inside_runtime_root(self):
        path = provider_profiles.codex_home(
            "/runtime/provider-homes", "codex-primary"
        )
        self.assertEqual(path, "/runtime/provider-homes/codex/codex-primary")


if __name__ == "__main__":
    unittest.main(verbosity=2)
