#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bin" / "project_workspace.py"
sys.path.insert(0, str(ROOT / "bin"))
if "fcntl" not in sys.modules:
    fcntl = types.ModuleType("fcntl")
    fcntl.LOCK_EX = 2
    fcntl.LOCK_UN = 8
    fcntl.flock = lambda *_args, **_kwargs: None
    sys.modules["fcntl"] = fcntl


def load_module():
    spec = importlib.util.spec_from_file_location("project_workspace", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RecordingRunner:
    def __init__(self, *, session_exists=False, remote=""):
        self.calls = []
        self.session_exists = session_exists
        self.remote = remote

    def __call__(self, args, **_kwargs):
        argv = list(args)
        self.calls.append(argv)
        if argv[:2] == ["tmux", "has-session"]:
            return Result(0 if self.session_exists else 1)
        if "remote" in argv and "get-url" in argv:
            return Result(0, self.remote + "\n")
        if argv[:2] == ["git", "clone"]:
            workspace = pathlib.Path(argv[-1])
            (workspace / ".git").mkdir(parents=True)
            return Result()
        return Result()


def project(workspace: pathlib.Path) -> dict:
    return {
        "schemaVersion": 1,
        "slug": "project-factory",
        "repository": "https://github.com/LordCripto-Hub/Project-Factory.git",
        "branch": "main",
        "workspace": str(workspace),
        "tmuxSession": "repo-project-factory",
    }


class ProjectWorkspaceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_manifest_validation_rejects_unsafe_or_external_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            valid = project(root / "project-factory")
            normalized = self.module.validate_project(valid, str(root))
            self.assertEqual(normalized["slug"], "project-factory")

            invalid = []
            invalid.append({**valid, "workspace": "relative/project"})
            invalid.append({**valid, "workspace": str(root.parent / "outside")})
            invalid.append({**valid, "tmuxSession": "repo;rm"})
            invalid.append(
                {
                    **valid,
                    "repository": (
                        "ssh://git" + "@" + "example.invalid/repo.git"
                    ),
                }
            )
            invalid.append({**valid, "branch": "main:force"})
            for item in invalid:
                with self.subTest(item=item):
                    with self.assertRaises(self.module.WorkspaceError):
                        self.module.validate_project(item, str(root))

    def test_absent_workspace_is_cloned_once_without_pull_or_reset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            item = self.module.validate_project(project(root / "project-factory"), str(root))
            runner = RecordingRunner()
            state = self.module.ensure_workspace(item, runner=runner)
            self.assertEqual(state, "cloned")
            self.assertEqual(
                runner.calls,
                [[
                    "git", "clone", "--origin", "origin", "--branch", "main",
                    "--single-branch",
                    "https://github.com/LordCripto-Hub/Project-Factory.git",
                    str(root / "project-factory"),
                ]],
            )

    def test_existing_workspace_requires_matching_origin_and_is_not_updated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            workspace = root / "project-factory"
            (workspace / ".git").mkdir(parents=True)
            item = self.module.validate_project(project(workspace), str(root))
            runner = RecordingRunner(remote=item["repository"])
            self.assertEqual(self.module.ensure_workspace(item, runner=runner), "existing")
            flat = " ".join(" ".join(call) for call in runner.calls)
            for forbidden in (" pull ", " fetch ", " reset ", " checkout ", " push "):
                self.assertNotIn(forbidden, f" {flat} ")

            mismatch = RecordingRunner(remote="https://github.com/example/wrong.git")
            with self.assertRaisesRegex(self.module.WorkspaceError, "origin"):
                self.module.ensure_workspace(item, runner=mismatch)

    def test_tmux_session_is_created_only_when_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            item = self.module.validate_project(project(root / "project-factory"), str(root))
            item_path = pathlib.Path(item["workspace"])
            item_path.mkdir()

            absent = RecordingRunner(session_exists=False)
            self.assertTrue(self.module.ensure_tmux_session(item, runner=absent))
            self.assertIn(
                ["tmux", "new-session", "-d", "-s", "repo-project-factory", "-c", str(item_path)],
                absent.calls,
            )

            present = RecordingRunner(session_exists=True)
            self.assertFalse(self.module.ensure_tmux_session(item, runner=present))
            self.assertFalse(any(call[:2] == ["tmux", "new-session"] for call in present.calls))

    def test_project_profile_is_created_once_with_push_forbidden(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            item = self.module.validate_project(project(root / "project-factory"), str(root))
            profiles = root / "profiles"
            self.assertEqual(
                self.module.ensure_project_profile(item, str(profiles)), "created"
            )
            profile_path = profiles / "project-factory.json"
            profile = __import__("json").loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(profile["workingDirectory"], item["workspace"])
            self.assertIn("commit", profile["allowedActions"])
            self.assertIn("push", profile["forbiddenActions"])
            self.assertEqual(
                self.module.ensure_project_profile(item, str(profiles)), "existing"
            )


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ProjectWorkspaceContract)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("PASS persistent project workspace and tmux contract")
