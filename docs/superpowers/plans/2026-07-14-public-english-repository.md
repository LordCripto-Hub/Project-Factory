# Public English Repository Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert MyPeople into a community-facing English repository, prevent personal or secret material from entering public surfaces, and replace the published development history with one sanitized baseline.

**Architecture:** Rename the two Spanish documentation files, translate maintained documentation and runtime strings in place, and add public-tree and reachable-history audits that never print matched secret text. After the exact tree passes verification, create a protected local bundle and replace public `main` with a root commit built from that same tree by using a remote-object lease.

**Tech Stack:** Markdown, JavaScript, PowerShell, Python `unittest`, Git

---

## File map

- Create `CONTRIBUTING.md`: public language, privacy, and commit policy.
- Replace the two legacy public documents with `docs/MINIMAL-ARCHITECTURE.md` and `docs/USER-MANUAL.md`.
- Modify `README.md`: English project overview and corrected documentation links.
- Modify `docs/VOICE-DOCK.md`: English operator and privacy contract.
- Modify `bin/voice-dock.js`: English visible strings while retaining configurable recognition locale.
- Modify `windows/Start-MyPeople.ps1`: English errors and log messages.
- Modify `windows/Install-MyPeopleShortcut.ps1`: English shortcut description.
- Modify `verify/browser_journeys.js` and `verify/test_voice_dock.py`: English fixtures and assertions.
- Create `verify/test_public_repository.py`: privacy, secret, filename, and maintained-surface audit.
- Create `verify/audit_public_history.py`: non-disclosing scan of every blob reachable from `HEAD`.
- Create `verify/test_public_history.py`: history-auditor unit and live-history contracts.
- Modify `verify/verify.sh`: run the public repository audit.

### Task 1: Define the public repository contract

**Files:**
- Create: `CONTRIBUTING.md`
- Create: `verify/test_public_repository.py`
- Modify: `verify/verify.sh`

- [ ] **Step 1: Write the failing audit**

Create `verify/test_public_repository.py` with this contract:

```python
#!/usr/bin/env python3
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "docs" / "MINIMAL-ARCHITECTURE.md",
    ROOT / "docs" / "USER-MANUAL.md",
    ROOT / "docs" / "VOICE-DOCK.md",
    ROOT / "bin" / "voice-dock.js",
    ROOT / "windows" / "Start-MyPeople.ps1",
    ROOT / "windows" / "Install-MyPeopleShortcut.ps1",
]

class PublicRepositoryContract(unittest.TestCase):
    def test_public_document_names_are_english(self):
        names = {path.name for path in (ROOT / "docs").glob("*.md")}
        self.assertEqual(names, {"MINIMAL-ARCHITECTURE.md", "USER-MANUAL.md", "VOICE-DOCK.md"})

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

if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the audit and observe the expected failure**

Run:

```powershell
docker cp verify/test_public_repository.py mypeople:/home/mp/mypeople/verify/test_public_repository.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_public_repository.py
```

Expected: FAIL because `CONTRIBUTING.md` and the renamed English documents do not exist.

- [ ] **Step 3: Add the policy**

Create `CONTRIBUTING.md` with these enforceable rules:

```markdown
# Contributing

MyPeople is maintained as a public, community-facing repository.

- Write tracked documentation, code comments, CLI output, tests, UI strings, examples, and commit messages in English.
- Do not commit credentials, tokens, account identifiers, email addresses, private machine paths, or personal operational notes.
- Use generic provider profile and agent names in examples.
- Keep runtime state and credential stores outside Git.
- Run the complete verification suite before pushing.

Localized interfaces may be added through explicit locale files. The tracked default interface remains English.
```

Add this line before `core_verify.py` in `verify/verify.sh`:

```bash
python3 "$VERIFY/test_public_repository.py"
```

- [ ] **Step 4: Run the focused audit**

Run the Step 2 commands again.

Expected: the policy assertion passes while the legacy filename assertions still fail.

- [ ] **Step 5: Commit the policy and failing migration contract**

```powershell
git add CONTRIBUTING.md verify/test_public_repository.py verify/verify.sh
git commit -m "Define public repository policy"
```

### Task 2: Translate and rename maintained documentation

**Files:**
- Modify: `README.md`
- Create: `docs/MINIMAL-ARCHITECTURE.md`
- Create: `docs/USER-MANUAL.md`
- Delete: the two superseded non-English public documents
- Modify: `docs/VOICE-DOCK.md`
- Modify: `docs/superpowers/specs/2026-07-14-mypeople-operator-experience-design.md`
- Modify: `docs/superpowers/plans/2026-07-14-mypeople-operator-experience.md`

- [ ] **Step 1: Rename the two documentation files**

Run:

```powershell
git status --short docs
```

Expected: only the English public document names are present in the migration.

- [ ] **Step 2: Translate the renamed documents and README**

Preserve every command, path, warning, architecture decision, and verification result. Use these English headings:

```text
README.md:
  MyPeople
  Runtime state excluded from Git
  Quick start
  Interfaces
  Documentation
  Memory boundary

docs/MINIMAL-ARCHITECTURE.md:
  MyPeople Minimal Architecture
  Decision
  Minimal patterns worth adopting
  Patterns not adopted
  Current failure decisions
  Token discipline

docs/USER-MANUAL.md:
  MyPeople User Manual
  Active configuration
  Quick tour
  Checking Boss and Nightwatch
  Switching models
  Restarting the container
  Current persistence
  Known limitations
  Technical verification
  Recommended next stage
  Voice dictation
```

Update README links to:

```markdown
- [User manual](docs/USER-MANUAL.md)
- [Minimal architecture](docs/MINIMAL-ARCHITECTURE.md)
- [Voice Dock](docs/VOICE-DOCK.md)
```

- [ ] **Step 3: Translate Voice Dock and operator design documents**

Translate prose and examples without changing the native `SpeechRecognition`
design, the `Ctrl + Windows` shortcut, terminal safety, or the `Win + H`
fallback. Keep `es-AR` as a configurable recognition locale identifier; it is
not a visible repository language.

- [ ] **Step 4: Run the public repository audit**

```powershell
docker cp README.md mypeople:/home/mp/mypeople/README.md
docker cp docs mypeople:/home/mp/mypeople/docs
docker exec mypeople python3 /home/mp/mypeople/verify/test_public_repository.py
```

Expected: document existence and legacy filename tests pass.

- [ ] **Step 5: Commit the documentation migration**

```powershell
git add README.md docs
git commit -m "Translate public documentation to English"
```

### Task 3: Translate runtime and verification strings

**Files:**
- Modify: `bin/voice-dock.js`
- Modify: `windows/Start-MyPeople.ps1`
- Modify: `windows/Install-MyPeopleShortcut.ps1`
- Modify: `verify/browser_journeys.js`
- Modify: `verify/test_voice_dock.py`
- Modify: `verify/test_windows_launcher.py`

- [ ] **Step 1: Add failing English-string assertions**

Add these assertions to `verify/test_voice_dock.py`:

```python
def test_visible_voice_strings_are_english(self):
    js = (ROOT / "bin" / "voice-dock.js").read_text(encoding="utf-8")
    for phrase in ("MyPeople Dictation", "Start dictation", "Listening", "Text inserted"):
        self.assertIn(phrase, js)
```

Add these assertions to `verify/test_windows_launcher.py`:

```python
self.assertIn("MyPeople could not start", text)
self.assertIn("Docker CLI is not installed", text)
```

- [ ] **Step 2: Run the focused tests and observe failure**

```powershell
docker cp verify/test_voice_dock.py mypeople:/home/mp/mypeople/verify/test_voice_dock.py
docker cp verify/test_windows_launcher.py mypeople:/home/mp/mypeople/verify/test_windows_launcher.py
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_voice_dock.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_windows_launcher.py
```

Expected: FAIL because the current visible strings are not English.

- [ ] **Step 3: Translate runtime strings**

Use these exact visible states in `bin/voice-dock.js`:

```text
MyPeople Dictation
Start dictation
Stop dictation
Ready · Ctrl + Windows
Opening microphone…
Listening…
Text inserted · still listening
Dictation stopped · Ctrl + Windows
Microphone blocked · use Win + H
No speech detected · try again
Dictation unavailable
Use Win + H · browser dictation unavailable
```

Translate every PowerShell dialog, exception, description, and log message into
clear English. Do not change health checks, timeout behavior, or container
preservation.

Translate the mocked browser phrase to `native voice test` and update its
expected input value accordingly.

- [ ] **Step 4: Run focused tests and syntax checks**

```powershell
node --check bin/voice-dock.js
node --check verify/browser_journeys.js
[ScriptBlock]::Create((Get-Content -Raw windows/Start-MyPeople.ps1)) | Out-Null
docker exec -e PYTHONPATH=/home/mp/mypeople/bin mypeople python3 /home/mp/mypeople/verify/test_voice_dock.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_windows_launcher.py
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit runtime translations**

```powershell
git add bin/voice-dock.js windows verify/browser_journeys.js verify/test_voice_dock.py verify/test_windows_launcher.py
git commit -m "Translate public runtime strings to English"
```

### Task 4: Audit the complete tracked tree

**Files:**
- Modify: any maintained tracked text file identified by the audit
- Test: `verify/test_public_repository.py`

- [ ] **Step 1: Run deterministic repository scans**

```powershell
git grep -n -I -P "[^\x00-\x7F]" -- .
python verify/audit_public_history.py --tree-only
```

Expected: no personal path, account, or secret match. Language matches are
reviewed individually; technical identifiers and quoted locale codes may remain.

- [ ] **Step 2: Correct every maintained public match**

Translate prose, comments, fixtures, and visible strings into idiomatic English.
Do not translate URL routes, provider model identifiers, locale identifiers, or
historical Git object contents.

- [ ] **Step 3: Run the public audit and complete verifier**

```powershell
docker cp verify/. mypeople:/home/mp/mypeople/verify/
docker exec mypeople bash /home/mp/mypeople/verify/verify.sh
git diff --check
```

Expected: the full verifier exits 0 and `git diff --check` emits no errors.

- [ ] **Step 4: Review the staged public diff**

```powershell
git add -A
git diff --cached --check
git diff --cached --stat
git status --short
```

Expected: only intentional English migration files are staged.

- [ ] **Step 5: Commit the completed public audit**

```powershell
git commit -m "Complete public English repository migration"
```


### Task 5: Audit and replace the published development history

**Files:**
- Create: `verify/audit_public_history.py`
- Create: `verify/test_public_history.py`

- Local only: `%LOCALAPPDATA%\MyPeople\backups\Project-Factory-before-public-rewrite-<timestamp>.bundle`

- [ ] **Step 1: Write the non-disclosing history auditor and its failing contract**

Create `verify/audit_public_history.py`:

```python
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
    "authorization_header": re.compile(rb"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{12,}"),
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
            if not re.fullmatch(r"[^@]+@users\.noreply\.github\.com", email, re.IGNORECASE):
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
```

Create `verify/test_public_history.py`:

```python
#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audit_public_history", ROOT / "verify" / "audit_public_history.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class PublicHistoryContract(unittest.TestCase):
    def test_patterns_detect_constructed_sensitive_samples(self):
        samples = {
            "provider_token": b"token=" + b"tskey" + b"-auth-examplevalue1234567890",
            "email_address": b"operator" + b"@example.com",
            "private_windows_path": b"C:\\" + b"Users\\PrivateOperator\\project",
            "private_macos_path": b"/" + b"Users/PrivateOperator/project",
            "authorization_header": b"Authorization:" + b" Bearer examplevalue12345",
        }
        for label, sample in samples.items():
            self.assertIsNotNone(audit.PATTERNS[label].search(sample), label)

    def test_current_tree_has_no_sensitive_public_blob(self):
        self.assertEqual(audit.scan(tree_only=True), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```


- [ ] **Step 2: Run the tests and record only metadata from expected findings**

```powershell
python verify/test_public_history.py
python verify/audit_public_history.py
```

Expected: the unit contract passes. The history audit may exit 1 before the
rewrite, but it prints only finding labels, abbreviated object IDs, and paths;
it never prints the matching content.

- [ ] **Step 3: Create two local recovery anchors outside the public branch**

```powershell
$oldHead = git rev-parse HEAD
$remoteRows = @(git ls-remote --heads --tags origin)
$unexpectedRefs = @($remoteRows | ForEach-Object { ($_ -split "`t", 2)[1] } | Where-Object { $_ -ne 'refs/heads/main' })
if ($unexpectedRefs.Count -gt 0) { throw 'Unexpected public refs must be reviewed before rewrite' }
$remoteBefore = (git ls-remote origin refs/heads/main).Split("`t")[0]
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupRoot = Join-Path $env:LOCALAPPDATA 'MyPeople\backups'
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
$backupRef = "local/pre-public-rewrite-$stamp"
git branch $backupRef $oldHead
$bundle = Join-Path $backupRoot "Project-Factory-before-public-rewrite-$stamp.bundle"
git bundle create $bundle --all
git bundle verify $bundle
```

Expected: the bundle verifies successfully. `$backupRef` remains local and is
not included in any push refspec.

- [ ] **Step 4: Create a new root commit from the exact verified tree**

```powershell
$publicEmail = git config user.email
if ($publicEmail -notmatch '@users\.noreply\.github\.com$') { throw 'Configure a GitHub no-reply email before creating the public root' }
$tree = git rev-parse "$oldHead^{tree}"
$newHead = git commit-tree $tree -m "Initial public release"
$newTree = git rev-parse "$newHead^{tree}"
if ($tree -ne $newTree) { throw 'Root commit tree mismatch' }
git update-ref refs/heads/main $newHead $oldHead
git status --short
```

Expected: the tree IDs match and the worktree remains clean because only commit
ancestry changed.

- [ ] **Step 5: Verify the rewritten branch before publishing**

```powershell
python verify/test_public_history.py
python verify/audit_public_history.py
docker exec mypeople bash /home/mp/mypeople/verify/verify.sh
git rev-list --count HEAD
git diff "$backupRef^{tree}" "HEAD^{tree}" --exit-code
```

Expected: all audits and verification pass, commit count is `1`, and the tree
comparison exits 0.

- [ ] **Step 6: Publish with a pinned lease and verify the remote**

```powershell
git push --force-with-lease="refs/heads/main:$remoteBefore" origin main
$remoteAfter = (git ls-remote origin refs/heads/main).Split("`t")[0]
if ($remoteAfter -ne $newHead) { throw 'Remote main does not match sanitized root' }
git branch -r --contains $oldHead
```

Expected: remote `main` equals `$newHead`; no remote branch contains `$oldHead`.
The local backup branch and bundle remain available for recovery.
