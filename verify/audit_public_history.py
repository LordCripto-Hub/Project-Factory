#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "provider_token": re.compile(
        rb"(?i)(?<![A-Za-z0-9])(?:"
        + b"tskey"
        + rb"-auth-[A-Za-z0-9_-]{20,}|"
        + b"sk"
        + rb"-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"
    ),
    "email_address": re.compile(rb"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"),
    "private_windows_path": re.compile(rb"(?i)[A-Z]:\\Users\\[^\\\r\n]+"),
    "private_macos_path": re.compile(rb"/" + rb"Users/[^/\r\n]+"),
    "authorization_header": re.compile(
        rb"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{12,}"
    ),
}


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def history_blobs(tree_only: bool = False):
    revisions = ["HEAD"] if tree_only else git("rev-list", "HEAD").decode().splitlines()
    seen: set[str] = set()
    for revision in revisions:
        raw = git("ls-tree", "-r", "-z", "--full-tree", revision)
        for entry in raw.split(b"\0"):
            if not entry:
                continue
            metadata, path_bytes = entry.split(b"\t", 1)
            _mode, object_type, object_id = metadata.decode().split()
            if object_type != "blob" or object_id in seen:
                continue
            seen.add(object_id)
            yield object_id, path_bytes.decode("utf-8", errors="replace")


def commit_metadata_findings():
    findings = []
    rows = git("log", "--format=%H%x00%ae%x00%ce").decode().splitlines()
    for row in rows:
        commit_id, author_email, committer_email = row.split("\0")
        for email in (author_email, committer_email):
            if not re.fullmatch(
                r"[^@]+@users\.noreply\.github\.com", email, re.IGNORECASE
            ):
                findings.append(("commit_identity", commit_id[:12], "<commit-metadata>"))
                break
    return findings


def scan(tree_only: bool = False):
    findings = [] if tree_only else commit_metadata_findings()
    for object_id, path in history_blobs(tree_only):
        content = git("cat-file", "blob", object_id)
        if b"\0" in content[:4096]:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                findings.append((label, object_id[:12], path))
    return sorted(findings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree-only", action="store_true")
    args = parser.parse_args()
    findings = scan(args.tree_only)
    for label, object_id, path in findings:
        print(f"{label}\t{object_id}\t{path}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
