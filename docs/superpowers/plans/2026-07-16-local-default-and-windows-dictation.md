# Local-Default Networking and Windows Dictation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local-only networking the default, retain Tailscale as an explicit opt-in Compose profile, and remove browser microphone support in favor of Windows `Win + H`.

**Architecture:** The default Compose manifest binds every published port to loopback and has no elevated network capability. A separate override carries the Tailscale opt-in flag, TUN device, and `NET_ADMIN`; runtime and heartbeat discovery check that exact flag before invoking Tailscale. Browser microphone code and its server route are deleted, while Windows dictation remains external to MyPeople.

**Tech Stack:** Docker Compose, Bash, Python standard library, PowerShell, static HTML/CSS/JavaScript contract tests.

---

### Task 1: Local-default and optional Tailscale contracts

**Files:**
- Create: `verify/test_local_default_network.py`
- Create: `docker/compose.tailscale.yml`
- Modify: `docker/compose.volume-backed.yml`
- Modify: `bin/runtime-supervisor.sh`
- Modify: `bin/queue-client.py`

- [ ] **Step 1: Write the failing network contract**

```python
def test_default_compose_is_loopback_only_and_unprivileged(self):
    compose = (ROOT / "docker/compose.volume-backed.yml").read_text()
    for port in ("9900", "9933", "7681", "7682"):
        self.assertIn(f'"127.0.0.1:{port}:{port}"', compose)
    self.assertNotIn("/dev/net/tun", compose)
    self.assertNotIn("NET_ADMIN", compose)
    self.assertNotIn("MYPEOPLE_TAILSCALE_ENABLED", compose)

def test_optional_override_is_explicit(self):
    override = (ROOT / "docker/compose.tailscale.yml").read_text()
    self.assertIn("MYPEOPLE_TAILSCALE_ENABLED: \"1\"", override)
    self.assertIn("/dev/net/tun:/dev/net/tun", override)
    self.assertIn("NET_ADMIN", override)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `python verify/test_local_default_network.py`
Expected: FAIL because default ports are public, default Compose is privileged, and the override is absent.

- [ ] **Step 3: Implement the minimal network split**

```yaml
# default
ports:
  - "127.0.0.1:9900:9900"

# opt-in override
services:
  mypeople:
    environment:
      MYPEOPLE_TAILSCALE_ENABLED: "1"
    devices:
      - /dev/net/tun:/dev/net/tun
    cap_add:
      - NET_ADMIN
```

Guard all runtime Tailscale commands and `tail_ip()` with:

```text
MYPEOPLE_TAILSCALE_ENABLED == "1"
```

- [ ] **Step 4: Run focused tests**

Run: `python verify/test_local_default_network.py`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add docker bin/runtime-supervisor.sh bin/queue-client.py verify/test_local_default_network.py
git commit -m "feat: make local networking the safe default"
```

### Task 2: Remove browser microphone implementation

**Files:**
- Delete: `bin/voice-dock.js`
- Delete: `docs/VOICE-DOCK.md`
- Delete: `verify/test_voice_dock.py`
- Modify: `bin/todos.html`
- Modify: `bin/dashboard.html`
- Modify: `bin/wall.html`
- Modify: `bin/terminal.html`
- Modify: `bin/terminal-graph.html`
- Modify: `bin/todo-server.py`
- Modify: `bin/mypeople-ui.css`
- Modify: `verify/browser_journeys.js`
- Modify: `verify/test_scorpion_theme.py`
- Modify: `verify/test_public_repository.py`
- Modify: `verify/verify.sh`
- Create: `verify/test_windows_dictation_only.py`

- [ ] **Step 1: Write the failing removal contract**

```python
def test_production_has_no_browser_microphone(self):
    self.assertFalse((ROOT / "bin/voice-dock.js").exists())
    for path in OPERATOR_PAGES:
        self.assertNotIn("voice-dock", path.read_text())
    server = (ROOT / "bin/todo-server.py").read_text()
    self.assertNotIn("/voice/paste", server)
    self.assertNotIn("voice_paste", server)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `python verify/test_windows_dictation_only.py`
Expected: FAIL because the Voice Dock asset, page hooks, and paste route still exist.

- [ ] **Step 3: Remove only voice-specific production code**

Delete the asset, route, handler, page script tags, and `.voice-dock*` CSS rules. Remove the mocked SpeechRecognition journey and obsolete test. Preserve composer, terminal navigation, evidence UI, and Scorpion styling.

- [ ] **Step 4: Update affected contracts and run them**

Run:

```powershell
python verify/test_windows_dictation_only.py
python verify/test_scorpion_theme.py
python verify/test_public_repository.py
node --test verify/test_terminal_views.js
```

Expected: all tests pass and no browser microphone code is loaded.

- [ ] **Step 5: Commit**

```powershell
git add -A bin docs verify
git commit -m "refactor: use Windows dictation instead of browser voice"
```

### Task 3: Launcher and operator documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/USER-MANUAL.md`
- Modify: `windows/Start-MyPeople.ps1`
- Modify: `verify/test_windows_launcher.py`
- Modify: `verify/test_docker_persistence.py`

- [ ] **Step 1: Add failing documentation and launcher assertions**

```python
self.assertIn("Win + H", manual)
self.assertIn("compose.tailscale.yml", manual)
self.assertNotIn("Ctrl + Windows", manual)
self.assertNotIn("TS_AUTHKEY", launcher)
```

- [ ] **Step 2: Run the focused tests and confirm the new assertions fail**

Run: `python verify/test_windows_launcher.py && python verify/test_docker_persistence.py`
Expected: FAIL until documentation and deployment-copy contracts include the new override.

- [ ] **Step 3: Implement the operator path**

Document `http://localhost:9933`, loopback-only defaults, `Win + H`, and explicit optional override activation. Ensure deployment materialization copies `compose.tailscale.yml` but the one-click launcher invokes only `compose.volume-backed.yml`.

- [ ] **Step 4: Run focused verification**

Run: `python verify/test_windows_launcher.py && python verify/test_docker_persistence.py`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add README.md docs/USER-MANUAL.md windows verify
git commit -m "docs: document local launch and Windows dictation"
```

### Task 4: Full isolated verification and handoff

**Files:**
- Modify only if a test exposes a regression.

- [ ] **Step 1: Run static safety searches**

Run:

```powershell
rg -n "SpeechRecognition|voice-dock|/voice/paste" bin
rg -n "TS_AUTHKEY|/dev/net/tun|NET_ADMIN" docker/compose.volume-backed.yml windows/Start-MyPeople.ps1
```

Expected: both commands return no matches.

- [ ] **Step 2: Run the focused matrix in the disposable runtime image**

Run the networking, dictation-only, launcher, persistence, Scorpion theme, public repository, terminal-view, runtime-supervisor, and queue-client contracts inside a disposable container.

- [ ] **Step 3: Build a candidate image and perform no-port smoke**

Build from `docker/Dockerfile.runtime-image`, then run the focused tests without mounting live volumes or publishing host ports.

- [ ] **Step 4: Review the diff and commit any verification-only correction**

Run: `git diff --check && git status --short`
Expected: clean working tree after the final commit.
