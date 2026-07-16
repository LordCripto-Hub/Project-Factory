#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock


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

    def broker_environment(self, root: pathlib.Path):
        askpass = root / "askpass"
        askpass.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        askpass.chmod(0o700)
        return mock.patch.dict(self.module.os.environ, {
            "GIT_ASKPASS": str(askpass),
            "GIT_TERMINAL_PROMPT": "0",
        })

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
            with self.broker_environment(root):
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

    def test_missing_credential_broker_preserves_pending_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            approval = self.create(root)
            profiles = self.save_profile(root)
            runner = GitRunner()
            with mock.patch.dict(self.module.os.environ, {
                "GIT_ASKPASS": "",
                "GIT_TERMINAL_PROMPT": "",
            }), self.assertRaisesRegex(
                self.module.PublisherError, "Windows credential bridge"
            ):
                self.module.publish(
                    approval["approvalId"],
                    approvals_dir=str(root / "approvals"),
                    profiles_dir=str(profiles),
                    runner=runner,
                    now=1100.0,
                    execute=True,
                )
            saved = json.loads(
                (root / "approvals" / (approval["approvalId"] + ".json")).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(saved["status"], "pending")
            self.assertFalse(any("push" in call for call in runner.calls))

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

    def test_draft_pr_approval_binds_safe_head_base_title_and_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            approval = self.create(
                root,
                mode="draft_pr",
                base_branch="main",
                head_branch="task/task-1-project-factory",
                pr_title="Fix the publisher",
                pr_body="Evidence is attached to task-1.",
            )
            self.assertEqual(approval["mode"], "draft_pr")
            self.assertEqual(approval["baseBranch"], "main")
            self.assertEqual(approval["headBranch"], "task/task-1-project-factory")
            self.assertEqual(approval["prTitle"], "Fix the publisher")
            self.assertEqual(approval["prBody"], "Evidence is attached to task-1.")
            for invalid in ("main", "refs/heads/main", "../escape", "task//bad"):
                with self.subTest(head=invalid), self.assertRaises(self.module.PublisherError):
                    self.create(
                        root,
                        id_factory=lambda: "d" * 24,
                        mode="draft_pr",
                        base_branch="main",
                        head_branch=invalid,
                    )

    def test_draft_pr_push_is_exact_and_stops_at_branch_pushed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            approval = self.create(
                root,
                mode="draft_pr",
                base_branch="main",
                head_branch="task/task-1-project-factory",
            )
            profiles = self.save_profile(root)
            runner = GitRunner()
            with self.broker_environment(root):
                result = self.module.publish(
                    approval["approvalId"],
                    approvals_dir=str(root / "approvals"),
                    profiles_dir=str(profiles),
                    runner=runner,
                    now=1100.0,
                    execute=True,
                )
            self.assertEqual(result["status"], "branch_pushed")
            self.assertEqual(runner.calls[-1], [
                "git", "-C", str(root / "workspace"), "push", "--porcelain",
                "origin", f"{COMMIT}:refs/heads/task/task-1-project-factory",
            ])
            calls = len(runner.calls)
            resumed = self.module.publish(
                approval["approvalId"],
                approvals_dir=str(root / "approvals"),
                profiles_dir=str(profiles),
                runner=runner,
                now=1101.0,
                execute=True,
            )
            self.assertEqual(resumed["status"], "branch_pushed")
            self.assertEqual(len(runner.calls), calls)
            with self.assertRaisesRegex(self.module.PublisherError, "expired"):
                self.module.publish(
                    approval["approvalId"],
                    approvals_dir=str(root / "approvals"),
                    profiles_dir=str(profiles),
                    runner=runner,
                    now=2000.0,
                    execute=True,
                )

    def test_finalize_draft_pr_is_idempotent_and_records_sanitized_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            approval = self.create(
                root,
                mode="draft_pr",
                base_branch="main",
                head_branch="task/task-1-project-factory",
            )
            profiles = self.save_profile(root)
            with self.broker_environment(root):
                self.module.publish(
                    approval["approvalId"], approvals_dir=str(root / "approvals"),
                    profiles_dir=str(profiles), runner=GitRunner(), now=1100.0,
                )
            final = self.module.finalize_draft_pr(
                approval["approvalId"], 42,
                "https://github.com/LordCripto-Hub/Project-Factory/pull/42",
                approvals_dir=str(root / "approvals"), now=1102.0,
            )
            self.assertEqual(final["status"], "pr_created")
            self.assertEqual(final["pullRequest"]["number"], 42)
            again = self.module.finalize_draft_pr(
                approval["approvalId"], 42,
                "https://github.com/LordCripto-Hub/Project-Factory/pull/42",
                approvals_dir=str(root / "approvals"), now=1103.0,
            )
            self.assertEqual(again, final)
            receipt = (root / "approvals" / "receipts.jsonl").read_text(encoding="utf-8")
            self.assertIn('\"status\":\"pr_created\"', receipt)
            self.assertNotIn("password", receipt.lower())

    def test_finalize_rejects_wrong_repository_or_number(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            approval = self.create(
                root, mode="draft_pr", base_branch="main",
                head_branch="task/task-1-project-factory",
            )
            profiles = self.save_profile(root)
            with self.broker_environment(root):
                self.module.publish(
                    approval["approvalId"], approvals_dir=str(root / "approvals"),
                    profiles_dir=str(profiles), runner=GitRunner(), now=1100.0,
                )
            for number, url in (
                (42, "https://github.com/example/wrong/pull/42"),
                (42, "https://github.com/LordCripto-Hub/Project-Factory/pull/43"),
                (0, "https://github.com/LordCripto-Hub/Project-Factory/pull/0"),
            ):
                with self.subTest(number=number, url=url), self.assertRaises(self.module.PublisherError):
                    self.module.finalize_draft_pr(
                        approval["approvalId"], number, url,
                        approvals_dir=str(root / "approvals"), now=1102.0,
                    )


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ProjectPublisherContract)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("PASS Boss-authorized single-use project publisher contract")
