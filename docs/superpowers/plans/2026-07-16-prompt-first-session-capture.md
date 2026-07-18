# Prompt-First Codex Session Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every fresh managed Codex process receives exactly one role-appropriate startup prompt before MyPeople discovers and persists its provider session ID.

**Architecture:** `bin/mp` computes one startup message per role, submits it while the profile-scoped capture lock is held, and then discovers the new Codex transcript. Claude and exact-resume launches preserve their current ordering; post-roster prompt delivery remains only for backends that do not use prompt-first Codex capture.

**Tech Stack:** Python 3.11, tmux, Codex CLI 0.144.3, Docker Compose isolated verifier, PowerShell 5.1, unittest/mock.

---

### Task 1: Specify prompt-before-discovery ordering

**Files:**
- Modify: `verify/test_exact_session_recovery.py`
- Verify: `bin/mp:487-805`

- [ ] **Step 1: Extend the spawn fixture to observe ordering**

Change `run_spawn` to accept `namespace` and `composer`, then replace its discovery and message mocks with:

~~~python
def send_message(target, message):
    self.events.append(('send', target, message))
    return True

def discover_session(*_args, **_kwargs):
    self.events.append(('discover',))
    if discovery_error:
        raise discovery_error
    return discovery_value
~~~

Patch `wait_for_composer` with `return_value=composer`, patch `tmux_send_message` with `side_effect=send_message`, patch `discover_codex_session` with `side_effect=discover_session`, and call `self.mp.spawn(namespace or self.namespace())`.

- [ ] **Step 2: Add failing Boss, temporary-worker, and composer contracts**

~~~python
def test_fresh_codex_submits_bootstrap_once_before_discovery(self):
    self.run_spawn({
        'session_id': '019f0000-0000-7000-8000-000000000333',
        'cwd': os.path.realpath(self.cwd),
        'path': str(self.root / 'rollout.jsonl'),
    })
    sends = [event for event in self.events if event[0] == 'send']
    self.assertEqual(len(sends), 1)
    self.assertIn('Read your Boss doctrine', sends[0][2])
    self.assertLess(self.events.index(sends[0]), self.events.index(('discover',)))

def test_temporary_codex_worker_gets_one_bounded_readiness_prompt(self):
    namespace = self.namespace()
    namespace.agent_id = 'node-1/canary:exact-canary'
    namespace.boss = 'node-1/main:Boss'
    namespace.master = False
    namespace.temporary = True
    self.run_spawn({
        'session_id': '019f0000-0000-7000-8000-000000000334',
        'cwd': os.path.realpath(self.cwd),
        'path': str(self.root / 'rollout.jsonl'),
    }, namespace=namespace)
    sends = [event for event in self.events if event[0] == 'send']
    self.assertEqual(len(sends), 1)
    self.assertIn('temporary MyPeople worker', sends[0][2])
    self.assertLess(self.events.index(sends[0]), self.events.index(('discover',)))

def test_codex_composer_failure_blocks_discovery_with_typed_state(self):
    self.run_spawn({
        'session_id': '019f0000-0000-7000-8000-000000000335',
        'cwd': os.path.realpath(self.cwd),
        'path': str(self.root / 'rollout.jsonl'),
    }, composer=False)
    self.assertNotIn(('discover',), self.events)
    self.assertFalse(any(event[0] == 'send' for event in self.events))
    self.assertEqual(self.records[-1]['resume_state'], 'unavailable')
    self.assertEqual(self.records[-1]['last_recovery_error'], 'session_process_not_ready')
~~~

- [ ] **Step 3: Run RED**

Run the current live image with the worktree mounted read-only:

~~~powershell
$image = docker inspect mypeople --format '{{.Config.Image}}'
docker run --rm --entrypoint bash -v '${PWD}:/work:ro' -e MYPEOPLE_MP_BIN=/work/bin/mp $image -lc 'cd /work && export PYTHONPATH=/work/bin && python3 -B verify/test_exact_session_recovery.py'
~~~

Expected: the three new tests fail because discovery precedes startup submission.

- [ ] **Step 4: Commit RED**

~~~bash
git add verify/test_exact_session_recovery.py
git commit -m 'test: require prompt-first Codex session capture'
~~~

### Task 2: Submit one startup prompt before discovery

**Files:**
- Modify: `bin/mp:487-805`
- Test: `verify/test_exact_session_recovery.py`

- [ ] **Step 1: Add the message selector before `spawn`**

~~~python
def startup_message_for(ns, tab, initial_message=''):
    if str(initial_message or '').strip():
        return str(initial_message)
    if ns.master:
        return ('Read your Boss doctrine now. Internalize the queue quickstart, '
                'operate autonomously, and reply with a concise readiness summary '
                'containing plan, queue, mp, and verify.')
    if tab == 'Nightwatch':
        doctrine = 'AGENTS.md' if ns.backend == 'codex' else 'CLAUDE.md'
        return (f'Read {doctrine} and internalize the Nightwatch approve/edit/reject '
                'protocol. Reply with a concise nightwatch, CEO-equivalent, approve, '
                'WhatsApp, never-done readiness summary.')
    if ns.owner_task:
        return ('Read the TaskSpec at $MYPEOPLE_TASKSPEC_PATH. The MyPeople worker '
                'contract is already mounted; also follow the repository instructions. '
                f'Work only on owner task {ns.owner_task}, run verification, then report '
                'with mp complete and at least one --proof. Do not close the task yourself.')
    if ns.backend == 'codex':
        return ('Initialize this temporary MyPeople worker session, read local project '
                'instructions when present, and reply with a concise readiness summary.')
    return ''
~~~

- [ ] **Step 2: Compute once and submit inside the capture lock**

After `_build_launch_args`, set `startup_message = startup_message_for(ns, tab, initial_message)`. In the `created and capture_enabled` block, perform:

~~~python
try:
    if not wait_for_composer(target):
        raise SessionError('session_process_not_ready')
    if not tmux_send_message(target, startup_message):
        raise SessionError('session_process_not_ready')
    discovered = discover_codex_session(capture_home, cwd, capture_before, timeout=float(
        os.environ.get('MYPEOPLE_SESSION_CAPTURE_TIMEOUT_SEC', '90')
    ))
    session_identity.update(
        session_id=discovered['session_id'],
        session_backend='codex',
        session_profile=profile_id,
        session_cwd=cwd,
        session_recorded_at=time.time(),
        resume_state='available',
        last_recovery_error='',
    )
except SessionError as error:
    session_identity.update(
        session_id='',
        session_backend='codex',
        session_profile=profile_id,
        session_cwd=cwd,
        resume_state='unavailable',
        last_recovery_error=error.code,
    )
~~~

- [ ] **Step 3: Remove duplicate post-roster delivery**

Replace the existing role branches with:

~~~python
if created and resume_session:
    pass
elif created and capture_enabled:
    pass
elif created and startup_message:
    wait_for_composer(target)
    tmux_send_message(target, startup_message)
~~~

This preserves Claude hook ordering, sends nothing during exact resume, and prevents duplicate fresh Codex prompts.

- [ ] **Step 4: Run GREEN**

~~~powershell
$image = docker inspect mypeople --format '{{.Config.Image}}'
docker run --rm --entrypoint bash -v '${PWD}:/work:ro' -e MYPEOPLE_MP_BIN=/work/bin/mp -e MYPEOPLE_SESSION_CAPTURE_TIMEOUT_SEC=0 -e MYPEOPLE_RESUME_STABILITY_SEC=0 $image -lc 'cd /work && export PYTHONPATH=/work/bin && python3 -B verify/test_exact_session_recovery.py && python3 -B verify/test_worker_handoff.py && python3 -B verify/test_codex_boss_switch.py'
~~~

Expected: all focused contracts pass.

- [ ] **Step 5: Commit implementation**

~~~bash
git add bin/mp verify/test_exact_session_recovery.py
git commit -m 'fix: initialize Codex sessions before capture'
~~~

### Task 3: Review and verify the corrected candidate

**Files:**
- Verify: `bin/mp`
- Verify: `verify/test_exact_session_recovery.py`
- Verify: all lifecycle and public contracts

- [ ] **Step 1: Run all touched lifecycle suites**

Run:

~~~powershell
$image = docker inspect mypeople --format '{{.Config.Image}}'
$tests = 'test_agent_session.py test_exact_session_recovery.py test_claude_session_hook.py test_taskspec_spawn.py test_worker_handoff.py test_codex_boss_switch.py test_boss_supervisor_backend.py test_provider_session.py test_provider_launch_pause.py test_review_resume_revive.py test_queue_agent_reconciliation.py test_runtime_supervisor.py test_public_repository.py test_windows_provider_profiles.py test_project_workspace.py'
docker run --rm --entrypoint bash -v '${PWD}:/work:ro' -e MYPEOPLE_MP_BIN=/work/bin/mp -e MYPEOPLE_SUPERVISOR=/work/bin/boss-supervisor.sh -e MYPEOPLE_SESSION_CAPTURE_TIMEOUT_SEC=0 -e MYPEOPLE_RESUME_STABILITY_SEC=0 $image -lc "set -e; cd /work; export PYTHONPATH=/work/bin; for test in $tests; do python3 -B verify/`$test; done; bash -n bin/boss-supervisor.sh"
~~~

Expected: zero failures.

- [ ] **Step 2: Run static and public gates**

~~~powershell
git diff --check
python -B verify\test_public_history.py
$tokens = $null; $errors = $null
[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path windows\Switch-MyPeopleProviderProfile.ps1), [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count) { throw ($errors | Out-String) }
~~~

- [ ] **Step 3: Request independent read-only review**

Require review of exactly-once submission, prompt-before-discovery and lock release, no exact-resume prompt, Claude post-roster behavior, typed composer failure, and no regression to handoff redaction or bounded reconcile. Fix every Critical or Important finding through RED/GREEN.

- [ ] **Step 4: Run full host-source isolation**

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Invoke-IsolatedVerify.ps1 -TimeoutSeconds 600
~~~

Expected: `Isolated MyPeople verification passed.`

### Task 4: Build, deploy, canary, and publish

**Files:**
- Runtime: Docker image and volume-backed deployment
- GitHub: `feat/exact-session-recovery`
- Evidence: canonical ObsidianBrain MyPeople records

- [ ] **Step 1: Build and verify packaged source**

~~~powershell
$base = docker inspect mypeople --format '{{.Config.Image}}'
$sha = git rev-parse --short HEAD
$image = 'mypeople-node:prompt-first-' + $sha
docker build -f docker/Dockerfile.runtime-image --build-arg BASE_IMAGE=$base -t $image .
powershell -NoProfile -ExecutionPolicy Bypass -File verify\Invoke-IsolatedVerify.ps1 -Image $image -UsePackagedSource -TimeoutSeconds 600
~~~

Expected: immutable image ID and packaged verifier PASS.

- [ ] **Step 2: Perform backup-first upgrade**

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows\Upgrade-MyPeopleDockerImage.ps1 -CandidateImage $image -VerifyTimeoutSeconds 600
~~~

Expected: `UPGRADE PASS`, pinned rollback, unchanged board/workspaces, healthy control plane.

- [ ] **Step 3: Spawn the disposable canary**

~~~powershell
$agent = 'node-1/canary:exact-canary'
$marker = 'MYPEOPLE-EXACT-CANARY-PROMPT-FIRST-20260716'
docker exec mypeople /home/mp/mypeople/bin/mp spawn $agent --boss node-1/main:Boss --cwd /home/mp/mypeople/run/eng/eng-1 --backend codex --model gpt-5.6-luna --temporary
docker exec mypeople /home/mp/mypeople/bin/mp send $agent ('Remember the non-secret marker ' + $marker + ' and reply with that exact marker only.')
~~~

Expected: temporary lifecycle, empty owner task, nonempty UUID, and `resume_state=available`.

- [ ] **Step 4: Prove deliberate stop and exact revive**

~~~powershell
$before = docker exec mypeople python3 -c "import json; r=json.load(open('/home/mp/mypeople/run/roster.json')); print(next(x for x in r if x.get('agent_id')=='node-1/canary:exact-canary')['session_id'])"
docker exec mypeople /home/mp/mypeople/bin/mp kill $agent --reason exact-session-canary
Start-Sleep -Seconds 32
docker exec mypeople tmux has-session -t mc-canary:exact-canary
if ($LASTEXITCODE -eq 0) { throw 'Canary revived despite deliberate stop.' }
docker exec mypeople /home/mp/mypeople/bin/mp revive $agent
$after = docker exec mypeople python3 -c "import json; r=json.load(open('/home/mp/mypeople/run/roster.json')); print(next(x for x in r if x.get('agent_id')=='node-1/canary:exact-canary')['session_id'])"
if ($before.Trim() -ne $after.Trim()) { throw 'Canary session ID changed.' }
docker exec mypeople /home/mp/mypeople/bin/mp send $agent 'Reply with the marker you were asked to remember earlier.'
~~~

Expected: stopped across two supervisor cycles, same UUID after revive, marker visible in the pane.

- [ ] **Step 5: Remove only canary-owned artifacts**

~~~powershell
docker exec mypeople /home/mp/mypeople/bin/mp kill $agent --reason canary-complete
docker exec mypeople python3 -c "import sys; sys.path.insert(0,'/home/mp/mypeople/bin'); from mpcommon import remove_roster; remove_roster('node-1/canary:exact-canary')"
docker exec mypeople rm -f /home/mp/mypeople/status/mc-canary/exact-canary.json /home/mp/recordings/node-1-exact-canary.cast
~~~

Expected: no canary row/window/recorder/status; Boss, Nightwatch, board, tasks, and workspaces unchanged.

- [ ] **Step 6: Launcher smoke, GitHub, and durable evidence**

Run:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\MyPeople\launcher\Start-MyPeople.ps1" -NoBrowser -NonInteractive
Select-String -LiteralPath "$env:LOCALAPPDATA\MyPeople\launcher.log" -Pattern 'READY http://localhost:9933/' | Select-Object -Last 1
git push -u origin feat/exact-session-recovery
gh pr create --repo LordCripto-Hub/Project-Factory --base main --head feat/exact-session-recovery --title 'Add exact agent session recovery' --body 'Adds provider session capture, prompt-first Codex initialization, deliberate stop intent, strict exact revive, bounded reconcile, and transaction-authorized fresh handoffs. Verified with focused lifecycle suites, full isolated host and packaged-source runs, backup-first live upgrade, disposable same-UUID canary, and launcher smoke.'
~~~

Require `READY http://localhost:9933/`, verify the PR head equals local HEAD, public text is English, checks and independent review are clean, then merge. Record commit, PR, image IDs, upgrade transaction, backup hash, test evidence, UUID equality without the UUID, the prompt-order learning, and remaining Minor race notes in canonical ObsidianBrain. Never store credentials, transcripts, private prompts, or session IDs.
