#!/usr/bin/env python3
import contextlib
import importlib.machinery
import io
import json
import os
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
windows = (ROOT / "windows" / "Publish-MyPeopleProject.ps1").read_text(encoding="utf-8")
wrapper_path = ROOT / "bin" / "publish-with-credential"
wrapper = wrapper_path.read_text(encoding="utf-8")
askpass = (ROOT / "bin" / "mypeople-git-askpass").read_text(encoding="utf-8")

assert "[switch]$CheckOnly" in windows
assert "git credential fill" in windows
assert "System.Diagnostics.ProcessStartInfo" in windows
assert "$env:ComSpec" in windows
assert "RedirectStandardOutput" in windows
assert "[System.IO.File]::WriteAllText" in windows
assert "[System.Text.Encoding]::ASCII" in windows
assert "Remove-Item -LiteralPath" in windows
assert "$credentialRequest | & git credential fill" not in windows
assert "docker exec -i mypeople" in windows
assert "publish-with-credential" in windows
assert "gh pr create" in windows
assert "gh pr list" in windows
assert "gh pr view" in windows
assert "--head $result.headBranch" in windows
assert "--state all" in windows
assert "--limit 1" in windows
assert "$pullRequestCandidates" in windows
assert "$parsedPullRequests" in windows
assert "if ($null -ne $parsedPullRequests)" in windows
assert "headRefName,baseRefName 2>$null | Out-String" not in windows
assert "--draft" in windows
assert "publish-pr-complete" in windows
assert "branch_pushed" in windows
assert "ConvertFrom-Json" in windows
assert "headRefName" in windows
assert "baseRefName" in windows
assert "$pullRequest.state -ne 'OPEN'" in windows
assert "$pullRequest.isDraft -ne $true" in windows
assert "$preflight.status -in @('branch_pushed', 'pr_created')" in windows
assert "protocol=https" in windows
assert "host=github.com" in windows
assert "Write-Output $credential" not in windows
assert "Write-Host $credential" not in windows
assert "MYPEOPLE_GIT_PASSWORD" in wrapper
assert "GIT_ASKPASS" in wrapper
assert "MYPEOPLE_GIT_USERNAME" in askpass
assert "MYPEOPLE_GIT_PASSWORD" in askpass
assert "set -x" not in askpass
assert "print(payload)" not in wrapper
assert "print(secret)" not in wrapper

installer = (ROOT / "windows" / "Install-MyPeopleShortcut.ps1").read_text(encoding="utf-8")
assert "Publish-MyPeopleProject.ps1" in installer

fake_publisher = types.ModuleType("project_publisher")
fake_publisher.PublisherError = RuntimeError
captured = {}


def fake_publish(approval_id, execute):
    captured["approvalId"] = approval_id
    captured["execute"] = execute
    captured["username"] = os.environ.get("MYPEOPLE_GIT_USERNAME")
    captured["password"] = os.environ.get("MYPEOPLE_GIT_PASSWORD")
    return {"approvalId": approval_id, "status": "published"}


fake_publisher.publish = fake_publish
previous_publisher = sys.modules.get("project_publisher")
previous_stdin, previous_stdout, previous_argv = sys.stdin, sys.stdout, sys.argv
sys.modules["project_publisher"] = fake_publisher
try:
    module = importlib.machinery.SourceFileLoader(
        "publish_with_bom_credential", str(wrapper_path)
    ).load_module()
    body = json.dumps({"username": "test-user", "password": "test-secret"})
    sys.stdin = io.TextIOWrapper(
        io.BytesIO(b"\xef\xbb\xbf" + body.encode("utf-8")), encoding="utf-8"
    )
    output = io.StringIO()
    sys.stdout = output
    sys.argv = [str(wrapper_path), "a" * 24]
    assert module.main() == 0
finally:
    sys.stdin, sys.stdout, sys.argv = previous_stdin, previous_stdout, previous_argv
    if previous_publisher is None:
        sys.modules.pop("project_publisher", None)
    else:
        sys.modules["project_publisher"] = previous_publisher

assert captured == {
    "approvalId": "a" * 24,
    "execute": True,
    "username": "test-user",
    "password": "test-secret",
}
assert "test-secret" not in output.getvalue()

print("PASS transient Windows credential bridge contract")
