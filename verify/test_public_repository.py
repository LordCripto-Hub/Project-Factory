#!/usr/bin/env python3
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "docs" / "MINIMAL-ARCHITECTURE.md",
    ROOT / "docs" / "UPSTREAM-MYPEOPLE-REVIEW.md",
    ROOT / "docs" / "USER-MANUAL.md",
    ROOT / "windows" / "Start-MyPeople.ps1",
    ROOT / "windows" / "Install-MyPeopleShortcut.ps1",
]


class PublicRepositoryContract(unittest.TestCase):
    def test_public_document_names_are_english(self):
        names = {path.name for path in (ROOT / "docs").glob("*.md")}
        self.assertEqual(
            names,
            {
                "MINIMAL-ARCHITECTURE.md",
                "UPSTREAM-MYPEOPLE-REVIEW.md",
                "USER-MANUAL.md",
            },
        )

    def test_public_surfaces_exist_and_are_nonempty(self):
        for path in PUBLIC_FILES:
            self.assertTrue(path.is_file(), path)
            self.assertTrue(path.read_text(encoding="utf-8").strip(), path)

    def test_public_surfaces_do_not_contain_private_material(self):
        forbidden = [
            re.compile(r"(?i)" + "tskey" + r"-auth-"),
            re.compile(r"(?i)" + "sk" + r"-[a-z0-9]{20,}"),
            re.compile(r"(?i)[a-z0-9._%+-]+@gmail\.com"),
            re.compile(r"(?i)c:\\users\\[^\\]+"),
            re.compile(r"(?i)/users/[^/]+"),
        ]
        for path in PUBLIC_FILES:
            text = path.read_text(encoding="utf-8")
            for pattern in forbidden:
                self.assertIsNone(pattern.search(text), f"{path}: {pattern.pattern}")

    def test_repository_declares_english_only_public_content(self):
        policy = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("English", policy)
        self.assertIn("credentials", policy)
        self.assertIn("personal", policy)

    def test_durable_docker_operator_contract_is_public(self):
        for path in (ROOT / "README.md", ROOT / "docs" / "USER-MANUAL.md"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("Durable Docker state", text)
            self.assertIn("Migrate-MyPeopleDockerState.ps1", text)
            self.assertIn("mypeople-pre-volumes-", text)
            self.assertIn("Never run `docker compose down -v`", text)
            self.assertIn("Cloudflare memory remains disabled", text)

    def test_memory_pilot_documents_the_real_security_boundary(self):
        manual = (ROOT / "docs" / "USER-MANUAL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Test-MyPeopleMemoryPilot.ps1", manual)
        self.assertIn("disposable agent-free container", manual)
        self.assertIn("Persistent memory activation is blocked", manual)
        self.assertIn("same Linux user", manual)

    def test_launcher_degraded_mode_is_public(self):
        for path in (ROOT / "README.md", ROOT / "docs" / "USER-MANUAL.md"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("Ready degraded", text)
            self.assertIn("providers-resume", text)
            self.assertIn("never imports another Windows login automatically", text)

    def test_worker_context_isolation_is_public(self):
        manual = (ROOT / "docs" / "USER-MANUAL.md").read_text(encoding="utf-8")
        self.assertIn("TaskSpec-owned working directory", manual)
        self.assertIn("never modifies", manual)
        self.assertIn("the project's `AGENTS.md` or `CLAUDE.md`", manual)
        self.assertIn("role contract SHA-256", manual)

    def test_exact_session_recovery_contract_is_public(self):
        manual = (ROOT / "docs" / "USER-MANUAL.md").read_text(encoding="utf-8")
        for path in (ROOT / "README.md", ROOT / "docs" / "USER-MANUAL.md"):
            text = path.read_text(encoding="utf-8")
            normalized = " ".join(text.split())
            self.assertIn("exact session resume", normalized)
            self.assertIn("deliberate stop", normalized)
            self.assertIn("mp reconcile", normalized)
            self.assertIn("three recovery attempts", normalized)
            self.assertIn("explicit fresh handoff", normalized)
            self.assertIn("no silent fresh fallback", normalized)
        self.assertNotIn(
            "still opens a new Codex conversation",
            manual,
        )
        self.assertNotIn(
            "Codex conversations are not resumed automatically",
            manual,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
