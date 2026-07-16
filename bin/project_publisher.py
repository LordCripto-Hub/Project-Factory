#!/usr/bin/env python3
"""Single-use Boss approvals and exact-commit Git publication."""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import time
from typing import Callable

from mpcommon import (
    ENV,
    ROOT,
    atomic_json,
    http_json,
    json_lock,
    load_json,
    load_roster,
    parse_agent_id,
)


COMMIT = re.compile(r"^[0-9a-f]{40}$")
APPROVAL_ID = re.compile(r"^[0-9a-f]{24}$")
BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
PR_URL = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/pull/([1-9][0-9]*)$")
PUBLISH_MODES = {"direct_main", "draft_pr"}


class PublisherError(RuntimeError):
    pass


def safe_failure_detail(value: str) -> str:
    """Keep useful Git diagnostics while excluding URLs and secret-shaped data."""
    detail = re.sub(r"https?://[^\s'\"]+", "<remote>", str(value or ""))
    detail = re.sub(r"(?i)(password|token|secret|credential)[=:][^\s]+", r"\1=<redacted>", detail)
    return re.sub(r"\s+", " ", detail).strip()[:500]


def _run(args, **kwargs):
    return subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    )


def approvals_root(path: str | None = None) -> str:
    return os.path.realpath(
        path
        or os.environ.get(
            "PUBLISH_APPROVALS_DIR", os.path.join(ROOT, "run", "publish-approvals")
        )
    )


def profiles_root(path: str | None = None) -> str:
    return os.path.realpath(
        path
        or os.environ.get(
            "PROJECT_PROFILES_DIR", os.path.join(ROOT, "run", "project-profiles")
        )
    )


def approval_path(approval_id: str, root: str) -> str:
    if not APPROVAL_ID.fullmatch(approval_id):
        raise PublisherError("invalid approval ID")
    return os.path.join(os.path.realpath(root), approval_id + ".json")


def _master_boss(actor: str, roster: list[dict]) -> bool:
    try:
        _host, _session, tab = parse_agent_id(actor)
    except ValueError:
        return False
    if tab != "Boss":
        return False
    return any(
        row.get("agent_id") == actor
        and row.get("is_master") is True
        and row.get("state") == "alive"
        and not row.get("retired")
        for row in roster
    )


def _validate_profile(profile: dict, project_slug: str, branch: str) -> None:
    if not isinstance(profile, dict) or profile.get("schemaVersion") != 1:
        raise PublisherError("ProjectProfile is missing or invalid")
    if profile.get("slug") != project_slug:
        raise PublisherError("ProjectProfile slug mismatch")
    if branch not in (profile.get("allowedBranches") or []):
        raise PublisherError("branch is not allowed by ProjectProfile")
    workspace = str(profile.get("workingDirectory") or "")
    repository = str(profile.get("repository") or "")
    if not os.path.isabs(workspace):
        raise PublisherError("ProjectProfile workspace must be absolute")
    if not repository.startswith("https://github.com/") or not repository.endswith(".git"):
        raise PublisherError("ProjectProfile repository is not publishable")


def _valid_branch(value: str) -> bool:
    return bool(
        BRANCH.fullmatch(value)
        and ".." not in value
        and "//" not in value
        and not value.endswith("/")
        and not value.startswith("refs/")
    )


def default_head_branch(task_id: str, project_slug: str) -> str:
    suffix = re.sub(r"[^a-z0-9]+", "-", f"{task_id}-{project_slug}".lower()).strip("-")
    if not suffix:
        raise PublisherError("cannot derive draft PR head branch")
    return ("task/" + suffix)[:128].rstrip("-")


def _validate_draft_pr_fields(base_branch: str, head_branch: str, title: str, body: str) -> None:
    if not _valid_branch(base_branch):
        raise PublisherError("invalid draft PR base branch")
    if not _valid_branch(head_branch) or not head_branch.startswith("task/"):
        raise PublisherError("draft PR head branch must use the task/ namespace")
    if head_branch == base_branch or head_branch.lower() == "main":
        raise PublisherError("draft PR head branch cannot be the base branch")
    if not isinstance(title, str) or not title.strip() or len(title) > 240:
        raise PublisherError("draft PR title must contain 1 to 240 characters")
    if not isinstance(body, str) or len(body) > 8000:
        raise PublisherError("draft PR body exceeds 8000 characters")


def create_approval(
    *,
    task_id: str,
    project_slug: str,
    commit: str,
    branch: str,
    actor: str,
    roster: list[dict],
    task: dict,
    profile: dict,
    approvals_dir: str,
    now: float | None = None,
    ttl_seconds: int = 900,
    id_factory: Callable[[], str] = lambda: secrets.token_hex(12),
    mode: str = "direct_main",
    base_branch: str | None = None,
    head_branch: str | None = None,
    pr_title: str | None = None,
    pr_body: str | None = None,
) -> dict:
    current = time.time() if now is None else float(now)
    commit = commit.lower()
    if not _master_boss(actor, roster):
        raise PublisherError("only a live managed master Boss can approve publication")
    if not task_id or not isinstance(task, dict):
        raise PublisherError("priority task is missing")
    if task.get("projectSlug") != project_slug:
        raise PublisherError("priority project does not match publication project")
    if task.get("state") != "review":
        raise PublisherError("priority must be in review before publication approval")
    if not (task.get("proofs") or []):
        raise PublisherError("priority requires evidence before publication approval")
    if not COMMIT.fullmatch(commit):
        raise PublisherError("commit must be a full 40-character SHA")
    if not _valid_branch(branch):
        raise PublisherError("invalid publication branch")
    if mode not in PUBLISH_MODES:
        raise PublisherError("invalid publication mode")
    if not 60 <= int(ttl_seconds) <= 3600:
        raise PublisherError("approval TTL must be between 60 and 3600 seconds")
    _validate_profile(profile, project_slug, branch)
    if mode == "draft_pr":
        base_branch = base_branch or branch
        head_branch = head_branch or default_head_branch(task_id, project_slug)
        pr_title = (pr_title or str(task.get("text") or f"Task {task_id}")).strip()
        pr_body = pr_body if pr_body is not None else f"Authorized by Boss for MyPeople task `{task_id}`."
        _validate_draft_pr_fields(base_branch, head_branch, pr_title, pr_body)
        if base_branch != branch:
            raise PublisherError("draft PR base branch must match the approved workspace branch")
    approval_id = id_factory()
    if not APPROVAL_ID.fullmatch(approval_id):
        raise PublisherError("approval ID generator returned an invalid value")
    root = approvals_root(approvals_dir)
    path = approval_path(approval_id, root)
    if os.path.exists(path):
        raise PublisherError("approval ID collision")
    record = {
        "schemaVersion": 1,
        "approvalId": approval_id,
        "status": "pending",
        "taskId": task_id,
        "projectSlug": project_slug,
        "commit": commit,
        "branch": branch,
        "repository": profile["repository"],
        "workspace": os.path.realpath(profile["workingDirectory"]),
        "profileRevision": profile.get("revision"),
        "approvedBy": actor,
        "createdAt": current,
        "expiresAt": current + int(ttl_seconds),
        "mode": mode,
    }
    if mode == "draft_pr":
        record.update({
            "baseBranch": base_branch,
            "headBranch": head_branch,
            "prTitle": pr_title,
            "prBody": pr_body,
        })
    atomic_json(path, record, mode=0o600)
    return record


def load_profile(project_slug: str, root: str) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", project_slug):
        raise PublisherError("invalid project slug")
    profile = load_json(os.path.join(os.path.realpath(root), project_slug + ".json"), None)
    if not isinstance(profile, dict):
        raise PublisherError("ProjectProfile not found")
    return profile


def _git(runner: Callable, workspace: str, *args: str):
    result = runner(["git", "-C", workspace, *args])
    if result.returncode != 0:
        raise PublisherError("Git publication preflight failed")
    return (result.stdout or "").strip()


def _preflight(record: dict, profile: dict, runner: Callable) -> None:
    _validate_profile(profile, record["projectSlug"], record["branch"])
    workspace = os.path.realpath(profile["workingDirectory"])
    if workspace != os.path.realpath(record["workspace"]):
        raise PublisherError("approved workspace no longer matches ProjectProfile")
    if profile["repository"].rstrip("/") != record["repository"].rstrip("/"):
        raise PublisherError("approved repository no longer matches ProjectProfile")
    head = _git(runner, workspace, "rev-parse", "HEAD").lower()
    if head != record["commit"]:
        raise PublisherError("workspace HEAD does not match approved commit")
    if _git(runner, workspace, "status", "--porcelain"):
        raise PublisherError("workspace must be clean before publication")
    if _git(runner, workspace, "branch", "--show-current") != record["branch"]:
        raise PublisherError("workspace branch does not match approval")
    remote = _git(runner, workspace, "remote", "get-url", "origin")
    if remote.rstrip("/") != record["repository"].rstrip("/"):
        raise PublisherError("workspace origin does not match approval")


def _append_receipt(root: str, record: dict) -> None:
    path = os.path.join(root, "receipts.jsonl")
    os.makedirs(root, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o600)


def _credential_broker_ready() -> bool:
    askpass = os.environ.get("GIT_ASKPASS", "")
    return bool(
        askpass
        and os.path.isfile(askpass)
        and os.access(askpass, os.X_OK)
        and os.environ.get("GIT_TERMINAL_PROMPT") == "0"
    )


def publish(
    approval_id: str,
    *,
    approvals_dir: str | None = None,
    profiles_dir: str | None = None,
    runner: Callable = _run,
    now: float | None = None,
    execute: bool = True,
) -> dict:
    current = time.time() if now is None else float(now)
    root = approvals_root(approvals_dir)
    path = approval_path(approval_id, root)
    with json_lock(path):
        record = load_json(path, None)
        if not isinstance(record, dict):
            raise PublisherError("approval not found")
        if record.get("mode") == "draft_pr" and record.get("status") == "pr_created":
            return record
        if current >= float(record.get("expiresAt") or 0):
            raise PublisherError("approval has expired")
        if record.get("mode") == "draft_pr" and record.get("status") == "branch_pushed":
            return record
        if record.get("status") != "pending":
            raise PublisherError("approval is not pending")
        profile = load_profile(record["projectSlug"], profiles_root(profiles_dir))
        _preflight(record, profile, runner)
        if not execute:
            return {**record, "status": "validated", "validatedAt": current}
        if not _credential_broker_ready():
            raise PublisherError(
                "publication requires the Windows credential bridge; "
                "the approval remains pending"
            )
        record["status"] = "publishing"
        record["publishingAt"] = current
        atomic_json(path, record, mode=0o600)
        workspace = os.path.realpath(profile["workingDirectory"])
        destination = record.get("headBranch") if record.get("mode") == "draft_pr" else record["branch"]
        result = runner([
            "git", "-C", workspace, "push", "--porcelain", "origin",
            f"{record['commit']}:refs/heads/{destination}",
        ])
        if result.returncode != 0:
            record["status"] = "failed"
            record["failedAt"] = time.time()
            record["failure"] = "git_push_failed"
            record["failureDetail"] = safe_failure_detail(getattr(result, "stderr", ""))
            atomic_json(path, record, mode=0o600)
            _append_receipt(root, {
                "approvalId": approval_id,
                "taskId": record["taskId"],
                "projectSlug": record["projectSlug"],
                "commit": record["commit"],
                "branch": record["branch"],
                "headBranch": destination,
                "status": "failed",
                "timestamp": record["failedAt"],
            })
            raise PublisherError("git push failed; create a new approval after repair")
        record["status"] = "branch_pushed" if record.get("mode") == "draft_pr" else "published"
        timestamp_key = "branchPushedAt" if record.get("mode") == "draft_pr" else "publishedAt"
        record[timestamp_key] = time.time()
        atomic_json(path, record, mode=0o600)
        if record.get("mode") != "draft_pr":
            _append_receipt(root, {
                "approvalId": approval_id,
                "taskId": record["taskId"],
                "projectSlug": record["projectSlug"],
                "commit": record["commit"],
                "branch": record["branch"],
                "approvedBy": record["approvedBy"],
                "status": "published",
                "timestamp": record["publishedAt"],
            })
        return record


def finalize_draft_pr(
    approval_id: str,
    number: int,
    url: str,
    *,
    approvals_dir: str | None = None,
    now: float | None = None,
) -> dict:
    current = time.time() if now is None else float(now)
    root = approvals_root(approvals_dir)
    path = approval_path(approval_id, root)
    with json_lock(path):
        record = load_json(path, None)
        if not isinstance(record, dict):
            raise PublisherError("approval not found")
        if record.get("mode") != "draft_pr":
            raise PublisherError("approval is not a draft PR publication")
        expected = record.get("pullRequest")
        if record.get("status") == "pr_created":
            if expected == {"number": int(number), "url": url}:
                return record
            raise PublisherError("draft PR is already finalized with different metadata")
        if record.get("status") != "branch_pushed":
            raise PublisherError("draft PR branch has not been pushed")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise PublisherError("invalid pull request number")
        match = PR_URL.fullmatch(str(url or ""))
        if not match or int(match.group(3)) != number:
            raise PublisherError("invalid pull request URL")
        repository = record["repository"].removesuffix(".git")
        if url.rsplit("/pull/", 1)[0] != repository:
            raise PublisherError("pull request repository does not match approval")
        record["status"] = "pr_created"
        record["pullRequest"] = {"number": number, "url": url}
        record["prCreatedAt"] = current
        atomic_json(path, record, mode=0o600)
        _append_receipt(root, {
            "approvalId": approval_id,
            "taskId": record["taskId"],
            "projectSlug": record["projectSlug"],
            "commit": record["commit"],
            "baseBranch": record["baseBranch"],
            "headBranch": record["headBranch"],
            "approvedBy": record["approvedBy"],
            "pullRequest": record["pullRequest"],
            "status": "pr_created",
            "timestamp": current,
        })
        return record


def get_approval(approval_id: str, approvals_dir: str | None = None) -> dict:
    record = load_json(approval_path(approval_id, approvals_root(approvals_dir)), None)
    if not isinstance(record, dict):
        raise PublisherError("approval not found")
    return record


def approve_runtime(
    task_id: str,
    project_slug: str,
    commit: str,
    branch: str,
    ttl_seconds: int,
    mode: str = "direct_main",
    base_branch: str | None = None,
    head_branch: str | None = None,
    pr_title: str | None = None,
    pr_body: str | None = None,
) -> dict:
    actor = os.environ.get("AGENT_ID", "").strip()
    todo_base = (
        os.environ.get("MYPEOPLE_TODO_URL")
        or os.environ.get("TODO_URL")
        or f"http://127.0.0.1:{ENV.get('TODO_PORT', '9933')}"
    )
    board = http_json("/todo/board", base=todo_base, token=ENV.get("QUEUE_SECRET", ""))
    task = (board.get("tasks") or {}).get(task_id)
    profile = load_profile(project_slug, profiles_root())
    record=create_approval(
        task_id=task_id,
        project_slug=project_slug,
        commit=commit,
        branch=branch,
        actor=actor,
        roster=load_roster(),
        task=task,
        profile=profile,
        approvals_dir=approvals_root(),
        ttl_seconds=ttl_seconds,
        mode=mode,
        base_branch=base_branch,
        head_branch=head_branch,
        pr_title=pr_title,
        pr_body=pr_body,
    )
    try:
        result=http_json("/todo/status", "POST", {
            "task_id": task_id,
            "state": "working",
            "verified": False,
            "by": actor,
            "expected_updated": task.get("updated"),
        }, base=todo_base, token=ENV.get("QUEUE_SECRET", ""))
        if isinstance(result, dict) and result.get("ok") is False:
            raise RuntimeError("todo status update was rejected")
    except Exception as error:
        try:
            os.unlink(approval_path(record["approvalId"], approvals_root()))
        except OSError:
            pass
        raise PublisherError(f"approval_resume_failed: {error}") from error
    return record
