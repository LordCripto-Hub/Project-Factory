# MyPeople operator experience implementation plan

> Execute in this session with red/green verification after each subsystem.

**Goal:** Add first-class task evidence, a global safe Voice Dock, a Scorpion-inspired visual system, and a one-click Windows launcher while keeping MyPeople a compact execution plane.

**Architecture:** Extend the existing `todo-server.py` and board proof timeline. Serve one shared CSS file and one shared Voice Dock module to every UI. Use native browser speech recognition and keep only tmux paste behind an authenticated same-origin endpoint. Keep Windows startup orchestration outside the container and preserve the existing container rather than recreating it.

**Technology:** Python standard library, browser SpeechRecognition/fetch, tmux, PowerShell, Docker Desktop, existing Node/Playwright verification.

---

## Task 1: Evidence contract tests

**Files:**
- Create: `verify/test_task_evidence.py`
- Modify: `verify/browser_journeys.js`

1. Add failing tests for proof metadata, downloadable file classification, SHA-256, evidence policy updates, and done rejection without required proof/verification.
2. Add failing CLI tests for `--proof-file` and `--proof-url`.
3. Run focused tests and confirm they fail for the intended missing behavior.

## Task 2: Evidence backend and CLI

**Files:**
- Modify: `bin/todo-server.py`
- Modify: `bin/mp`

1. Add `evidencePolicy` normalization and validated updates.
2. Enrich proof records with author, filename, MIME, bytes, and SHA-256.
3. Add generic file classification and safe download headers.
4. Enforce the review/done evidence gate.
5. Add multipart and URL proof submission to `mp complete`.
6. Run focused tests until green.

## Task 3: Shared UI foundation and evidence composer

**Files:**
- Create: `bin/mypeople-ui.css`
- Modify: `bin/todo-server.py`
- Modify: `bin/todos.html`
- Modify: `bin/terminal-graph.html`

1. Add asset routes with correct MIME types.
2. Add Evidence controls to the task modal: file picker, URL/text proof, drag/drop, and clipboard image upload.
3. Render preview/download evidence cards chronologically with metadata.
4. Expose the evidence policy selector.
5. Add and pass browser journey assertions.

## Task 4: Voice endpoint tests

**Files:**
- Create: `verify/test_voice_dock.py`

1. Add failing tests for native browser recognition, Spanish default, `Ctrl + Windows` shortcut latching, compact recording animation, terminal target validation, newline-neutral paste, and no implicit Enter.
2. Add route and static-module contracts proving that no paid transcription proxy or API key remains.
3. Confirm focused failures.

## Task 5: Voice backend and global dock

**Files:**
- Create: `bin/voice-dock.js`
- Create: `bin/terminal.html`
- Modify: `bin/todo-server.py`
- Modify: `bin/todos.html`
- Modify: `bin/wall.html`
- Modify: `bin/terminal-graph.html`
- Modify: `bin/dashboard.html`

1. Use native `SpeechRecognition` with `es-AR` by default and remove the OpenAI transcription proxy and API-key dependency.
2. Implement authenticated live-agent tmux paste with newline neutralization and no Enter.
3. Implement a compact 30-pixel control with idle, listening, inserted, denied, and unsupported states plus animated green audio bars.
4. Toggle dictation by click or latched `Ctrl + Windows`, inserting final phrases into the focused field or validated terminal target.
5. Change MyPeople terminal links to the same-origin wrapper while retaining the direct ttyd recovery port.
6. Mock SpeechRecognition events in browser tests and run focused verification.

## Task 6: Scorpion-inspired visual system

**Files:**
- Modify: `bin/mypeople-ui.css`
- Modify: `bin/todos.html`
- Modify: `bin/wall.html`
- Modify: `bin/terminal-graph.html`
- Modify: `bin/dashboard.html`
- Modify: `bin/terminal.html`
- Create: `verify/test_scorpion_theme.py`

1. Add failing token/asset inclusion tests.
2. Apply shared soot/charcoal/armor/gold/ember/bone tokens.
3. Add the gold mission rail and clipped evidence card signature without external copyrighted assets.
4. Preserve state readability and accessibility focus outlines.
5. Run static and browser visual checks at desktop and narrow widths.

## Task 7: One-click Windows launcher

**Files:**
- Create: `windows/Start-MyPeople.ps1`
- Create: `windows/Install-MyPeopleShortcut.ps1`
- Create: `verify/test_windows_launcher.py`
- Modify: `README.md`
- Modify: `docs/USER-MANUAL.md`

1. Add failing static contract tests for Docker Desktop startup, bounded waits, container preservation, health probes, logging, and browser opening after readiness.
2. Implement the idempotent launcher and shortcut installer.
3. Run tests, install the desktop shortcut, and execute a real restart-safe smoke against the current container.
4. Confirm a second launch is harmless and faster.

## Task 8: Integrated verification and deployment

**Files:**
- Modify: `verify/verify.sh`
- Modify: `docs/USER-MANUAL.md`
- Modify: `docs/MINIMAL-ARCHITECTURE.md`
- Modify: `docs/VOICE-DOCK.md`

1. Add new focused tests to the suite.
2. Run Python/Node focused tests, browser journeys, and the complete verification suite.
3. Copy the changed product files into the live `mypeople` container and restart only its managed supervisors.
4. Verify Priorities, evidence upload, terminal wrapper, and theme in the live browser.
5. Record native-recognition capability and fallback state without requesting microphone permission during diagnostics.
6. Commit intentionally and push `main` to `origin`.
