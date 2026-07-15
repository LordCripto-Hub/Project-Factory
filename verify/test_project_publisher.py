#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
if "fcntl" not in sys.modules:
    fcntl = types.ModuleType("fcntl")
    fcntl.LOCK_EX = 2
    fcntl.LOCK_UN = 8
    fcntl.flock = lambda *_args, **_kwargs: None
    sys.modules["fcntl"] = fcntl


def load_module():
    path = ROOT / "bin" / "project_publisher.py"
    spec = importlib.util.spec_from_file_location("project_publisher", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


COMMIT = "a" * 40
REPOSITORY = "https://github.com/LordCripto-Hub/Project-Factory.git"


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class GitRunner:
    def __init__(
        self,
        *,
        head=COMMIT,
        status="",
        branch="main",
        remote=REPOSITORY,
        push_code=0,
    ):
        self.calls = []
        self.head = head
        self.status = status
        self.branch = branch
        self.remote = remote
        self.push_code = push_code

    def __call__(self, args, **_kwargs):
        argv = list(args)
        self.calls.append(argv)
        suffix = argv[3:]
        if suffix == ["rev-parse", "HEAD"]:
            return Result(stdout=self.head + "\n")
        if suffix == ["status", "--porcelain"]:
            return Result(stdout=self.status)
        if suffix == ["branch", "--show-current"]:
            return Result(stdout=self.branch + "\n")
        if suffix == ["remote", "get-url", "origin"]:
            return Result(stdout=self.remote + "\n")
        if suffix[:3] == ["push", "--porcelain", "origin"]:
            return Result(self.push_code, "ok\n" if self.push_code == 0 else "", "denied")
        return Result(1, stderr="unexpected command")


def profile(workspace: pathlib.Path) -> dict:
    return {
        "schemaVersion": 1,
        "revision": 1,
        "slug": "project-factory",
        "repository": REPOSITORY,
        "workingDirectory": str(workspace),
        "allowedBranches": ["main"],
        "allowedActions": ["read", "edit", "test", "commit"],
        "forbiddenActions": ["deploy", "push", "delete"],
    }


def task(**overrides) -> dict:
    value = {
        "id": "task-123",
        "projectSlug": "project-factory",
        "state": "review",
        "proofs": [{"kind": "text", "body": "tests pass"}],
    }
    value.update(overrides)
    return value


def roster(master=True):
    return [{
        "agent_id": "node-1/main:Boss" if master else "node-1/main:Engineer-1",
        "is_master": master,
        "state": "alive",
        "retired": False,
    }]


class ProjectPublisherContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def create(self, root: pathlib.Path, **overrides):
        values = {
            "task_id": "task-123",
            "project_slug": "project-factory",
            "commit": COMMIT,
            "branch": "main",
            "actor": "node-1/main:Boss",
            "roster": roster(),
            "task": task(),
            "profile": profile(root / "workspace"),
            "approvals_dir": str(root / "approvals"),
            "now": 1000.0,
            "ttl_seconds": 900,
            "id_factory": lambda: "b" * 24,
        }
        values.update(overrides)
        return self.module.create_approval(**values)

    def save_profile(self, root: pathlib.Path):
        profiles = root / "profiles"
        profiles.mkdir()
        (profiles / "project-factory.json").write_text(
            json.dumps(profile(root / "workspace")), encoding="utf-8"
        )
        return profiles

    def test_only_live_master_boss_can_approve_review_with_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            approval = self.create(root)
            self.assertEqual(approval["status"], "pending")
            self.assertEqual(approval["commit"], COMMIT)
            self.assertEqual(approval["approvedBy"], "node-1/main:Boss")
            self.assertTrue((root / "approvals" / ("b" * 24 + ".json")).is_file())

            invalid = (
                {"actor": "node-1/main:Engineer-1", "roster": roster(False)},
                {"task": task(state="working")},
                {"task": task(proofs=[])},
                {"commit": "abc"},
                {"branch": "feature/not-allowed"},
            )
            for override in invalid:
                with self.subTest(override=override):
                    with self.assertRaises(self.module.PublisherError):
                        self.create(root, id_factory=lambda: "c" * 24, **override)

    def test_preflight_binds_clean_exact_head_branch_and_remote_without_push(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            approval = self.create(root)
            profiles = self.save_profile(root)
            runner = GitRunner()
            result = self.module.publish(
                approval["approvalId"],
                approvals_dir=str(root / "approvals"),
                profiles_dir=str(profiles),
                runner=runner,
                now=1100.0,
                execute=False,
            )
            self.assertEqual(result["status"], "validated")
            self.assertFalse(any("push" in call for call in runner.calls))

    def test_publish_pushes_only_exact_commit_once_and_records_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            approval = self.create(root)
            profiles = self.save_profile(root)
            runner = GitRunner()
            result = self.module.publish(
                approval["approvalId"],
                approvals_dir=str(root / "approvals"),
                profiles_dir=str(profiles),
                runner=runner,
                now=1100.0,
                execute=True,
            )
            expected = [
                "git", "-C", str(root / "workspace"), "push", "--porcelain",
                "origin", f"{COMMIT}:refs/heads/main",
            ]
            self.assertEqual(runner.calls[-1], expected)
            self.assertEqual(result["status"], "published")
            receipt = root / "approvals" / "receipts.jsonl"
            self.assertTrue(receipt.is_file())
            with self.assertRaisesRegex(self.module.PublisherError, "pending"):
                self.module.publish(
                    approval["approvalId"],
                    approvals_dir=str(root / "approvals"),
                    profiles_dir=str(profiles),
                    runner=runner,
                    now=1101.0,
                    execute=True,
                )

    def test_expired_dirty_or_mismatched_state_never_pushes(self):
        cases = (
            (GitRunner(), 2000.0),
            (GitRunner(status=" M README.md\n"), 1100.0),
            (GitRunner(head="d" * 40), 1100.0),
            (GitRunner(branch="feature"), 1100.0),
            (GitRunner(remote="https://github.com/example/wrong.git"), 1100.0),
        )
        for index, (runner, now) in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                approval = self.create(root)
                profiles = self.save_profile(root)
                with self.assertRaises(self.module.PublisherError):
                    self.module.publish(
                        approval["approvalId"],
                        approvals_dir=str(root / "approvals"),
                        profiles_dir=str(profiles),
                        runner=runner,
                        now=now,
                        execute=True,
                    )
                self.assertFalse(any("push" in call for call in runner.calls))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ProjectPublisherContract)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("PASS Boss-authorized single-use project publisher contract")

