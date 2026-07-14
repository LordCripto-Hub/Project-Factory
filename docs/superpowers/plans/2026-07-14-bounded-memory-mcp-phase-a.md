# Bounded Memory MCP Phase A Implementation Plan

> **Execution rule:** use `test-driven-development` for every behavior change, `verification-before-completion` before each completion claim, and `requesting-code-review` before the final live update.

**Goal:** Add project-aware priority cards, validated ProjectProfiles, bounded TaskSpec compilation, and a read-only official-SDK MCP gateway without connecting real Cloudflare data.

**Architecture:** The board owns task/project identity, a Python compiler owns context policy, and a small Node CLI owns only the MCP Streamable HTTP transport. `mp spawn --owner-task` compiles a mode-0600 TaskSpec before creating a worker. Memory-disabled tasks make no network call; requested-memory failures prevent worker creation.

**Tech stack:** Python 3 standard library, Node.js 22+, `@modelcontextprotocol/sdk@1.29.0`, `zod@4.4.3`, MCP Streamable HTTP, HTML/CSS/JavaScript, Python `unittest`, Node test runner, Playwright.

---

## File map

- Create `bin/project_context.py`: profile validation, bounded recall invocation, TaskSpec compilation, atomic persistence, metadata events.
- Create `memory-gateway/`: pinned official MCP client, response normalization, unit and loopback integration tests.
- Create `examples/project-profile.example.json`: non-secret public example.
- Modify `bin/todo-server.py` and `bin/todos.html`: project and context-question card fields.
- Modify `bin/mp` and `bin/mpcommon.py`: compile-before-spawn and configuration overrides.
- Create focused tests in `verify/` and add them to `verify/verify.sh`.
- Modify `install.sh` and `docs/USER-MANUAL.md`.

## Task 1: Add project identity to priority cards

**Files:** `bin/todo-server.py`, `bin/todos.html`, `verify/test_task_project_fields.py`

- [ ] Write `verify/test_task_project_fields.py` first. It must load `todo-server.py` with temporary `BOARD_PATH` and `PROJECT_PROFILES_DIR`, then prove:
  - legacy tasks normalize to empty `projectSlug` and `contextQuestion`;
  - valid slugs match `^[a-z0-9]+(?:-[a-z0-9]+)*$` and are at most 64 characters;
  - empty, uppercase, doubled-hyphen, traversal, whitespace, and 65-character slugs fail;
  - control characters are replaced in context questions and the result is at most 500 characters;
  - profile discovery includes only JSON files whose filename slug matches the body slug;
  - the Priorities HTML contains `projectSlug`, `projectSlugs`, and `contextQuestion` controls.

- [ ] Run RED:

```powershell
python verify/test_task_project_fields.py
```

- [ ] Implement in `bin/todo-server.py`:

```python
PROJECT_PROFILES_DIR = os.path.realpath(
    os.environ.get("PROJECT_PROFILES_DIR", os.path.join(ROOT, "run", "project-profiles"))
)
PROJECT_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

def validate_project_slug(value, *, allow_empty=False):
    value = str(value or "").strip()
    if allow_empty and not value:
        return ""
    if len(value) > 64 or not PROJECT_SLUG_RE.fullmatch(value):
        raise ValueError("invalid_project_slug")
    return value

def validate_context_question(value):
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    if len(value) > 500:
        raise ValueError("context_question_too_long")
    return value
```

`available_project_slugs()` must enumerate only `*.json`, validate the filename, parse UTF-8 JSON, require `data["slug"] == path.stem`, ignore invalid files, and return sorted unique slugs. Add the two empty defaults in `normalize_task`. Validate add/set payloads before acquiring `STORE_LOCK`. Return HTTP 400 with the typed validator code. Add `projectSlugs` only to the board response, never the persisted board.

- [ ] Add a datalist-backed project input and a 500-character context-question input to the existing detail view. Populate from `board.projectSlugs`, load/save both fields, add project to the render signature, and show a compact project badge when non-empty.

- [ ] Run GREEN:

```powershell
python verify/test_task_project_fields.py
python verify/test_task_evidence.py
```

- [ ] Commit:

```powershell
git add bin/todo-server.py bin/todos.html verify/test_task_project_fields.py
git commit -m "Add project context fields to priority cards"
```

## Task 2: Implement the ProjectProfile contract

**Files:** `bin/project_context.py`, `bin/mpcommon.py`, `examples/project-profile.example.json`, `verify/test_project_context.py`

- [ ] Write failing profile tests first. Use a valid schema-version-1 fixture and prove:
  - normalization preserves slug and limits;
  - schema versions other than 1 fail with `unsupported_schema_version`;
  - unknown fields and plaintext fields matching `token|secret|password|credentialValue|apiKey` fail;
  - `memoryTopK > 3`, `memoryHops != 0`, `contextChars > 20000`, or timeout above 15 fail;
  - enabled remote memory requires HTTPS and `env://NAME`;
  - filename and body slug must match;
  - a resolved profile path cannot escape the profile directory.

- [ ] Run RED:

```powershell
python verify/test_project_context.py
```

- [ ] Create `bin/project_context.py` with `ProfileError(code)`, `validate_project_slug`, `validate_profile`, and `load_profile`. Use these constants:

```python
MAX_CONTEXT_CHARS = 20000
MAX_MEMORY_TOP_K = 3
MAX_MEMORY_HOPS = 0
MAX_MEMORY_TIMEOUT_SECONDS = 15
PROJECT_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ENV_REF_RE = re.compile(r"^env://([A-Z][A-Z0-9_]{1,63})$")
```

Require an absolute POSIX or Windows working directory. Permit loopback HTTP only when `MYPEOPLE_MEMORY_ALLOW_HTTP=1`; reject all remote HTTP. Recursively reject secret-looking keys except `credentialRef`. Resolve `<profiles>/<slug>.json`, prove it stays under the resolved profile directory, parse UTF-8 JSON, validate it, then enforce filename/body slug equality.

- [ ] Add `examples/project-profile.example.json` with public placeholder URLs, `memory.enabled=false`, and no credential value. Add these process-local override names in `bin/mpcommon.py`:

```python
"PROJECT_PROFILES_DIR", "TASKSPECS_DIR", "MEMORY_GATEWAY_PATH", "MYPEOPLE_MEMORY_ALLOW_HTTP"
```

- [ ] Run GREEN and public-surface checks:

```powershell
python verify/test_project_context.py
python verify/test_public_repository.py
```

- [ ] Commit:

```powershell
git add bin/project_context.py bin/mpcommon.py examples/project-profile.example.json verify/test_project_context.py
git commit -m "Add versioned project profile contract"
```

## Task 3: Compile and persist local-only TaskSpecs

**Files:** `bin/project_context.py`, `verify/test_project_context.py`

- [ ] Add failing tests for `compile_task_spec` and `write_task_spec`. Prove:
  - no context question means the injected recall function is never called and status is `not_requested`;
  - a question with disabled memory never calls recall and status is `disabled`;
  - missing ID/objective/project, profile mismatch, or invalid evidence policy fails with a typed `TaskSpecError`;
  - acceptance criteria and verification commands are never removed to meet a budget;
  - a local-only contract larger than `contextChars` fails;
  - atomic output has mode `0600`, valid JSON, and no surviving temporary file.

- [ ] Run RED:

```powershell
python verify/test_project_context.py
```

- [ ] Implement `TaskSpecError(code)`, `compile_task_spec(task, profile, recall=None, now=time.time)`, and `write_task_spec(directory, task_id, value)`. The required document is:

```python
{
    "schemaVersion": 1,
    "taskId": str(task["id"]),
    "projectSlug": validate_project_slug(task["projectSlug"]),
    "profileRevision": profile["revision"],
    "objective": str(task["text"]).strip(),
    "acceptanceCriteria": str(task.get("doneCondition", "")).strip(),
    "repository": profile["repository"],
    "workingDirectory": profile["workingDirectory"],
    "contextFiles": profile["contextFiles"],
    "verificationCommands": profile["verificationCommands"],
    "allowedActions": profile["allowedActions"],
    "forbiddenActions": profile["forbiddenActions"],
    "evidencePolicy": task.get("evidencePolicy", "optional"),
    "memoryQuestion": str(task.get("contextQuestion", "")).strip(),
    "memoryClaims": [],
    "memoryStatus": "not_requested",
    "compiledAt": now(),
}
```

Serialize deterministically with compact separators for budget calculation. Atomic persistence must open a same-directory temporary file, set `0600`, flush and `fsync`, then use `os.replace`; clean up the temporary path on every exception.

- [ ] Run GREEN and commit:

```powershell
python verify/test_project_context.py
git add bin/project_context.py verify/test_project_context.py
git commit -m "Compile bounded task specifications"
```

## Task 4: Build the read-only official-SDK MCP gateway

**Files:** `memory-gateway/package.json`, `memory-gateway/package-lock.json`, `memory-gateway/memory-gateway.mjs`, `memory-gateway/test/memory-gateway.test.mjs`

- [ ] Create the pinned manifest, then generate only the lockfile:

```json
{
  "name": "mypeople-memory-gateway",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {"test": "node --test test/*.test.mjs"},
  "dependencies": {
    "@modelcontextprotocol/sdk": "1.29.0",
    "zod": "4.4.3"
  }
}
```

```powershell
npm.cmd install --package-lock-only --ignore-scripts --prefix memory-gateway
```

- [ ] Write unit tests first for `validateInput`, `normalizeClaims`, and `executeRecall`. Prove topK is 1-3, hops is exactly 0, question is 1-500 characters, maxChars is 256-20000, timeout is 0.01-15 seconds, unknown input keys fail, remote HTTP fails, missing provenance fails, cross-project claims fail, only `recall` is called, and clients close after success, malformed response, and timeout.

- [ ] Add an actual loopback integration test using these official SDK surfaces:

```javascript
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { createMcpExpressApp } from '@modelcontextprotocol/sdk/server/express.js';
import * as z from 'zod/v4';
```

Create the app, register a POST `/mcp` handler, construct one stateless `StreamableHTTPServerTransport({sessionIdGenerator: undefined})` per request, connect it to an `McpServer`, and register only:

```javascript
server.registerTool('recall', {
  inputSchema: {
    projectSlug: z.string(),
    query: z.string(),
    limit: z.number().int(),
    hops: z.number().int(),
  },
}, async args => {
  received = args;
  const claims = [{
    id: 'fixture-1', projectSlug: 'mypeople', content: 'Synthetic verified constraint.',
    sourceUri: 'task://fixture-1', sourceType: 'verified-task',
    createdAt: 1, updatedAt: 1, status: 'canonical',
  }];
  return {content: [{type: 'text', text: 'synthetic'}], structuredContent: {claims}};
});
```

Listen on `127.0.0.1` port 0, call the real `executeRecall` with `allowHttpLoopback:true`, assert received `{projectSlug:'mypeople', limit:3, hops:0}`, assert one normalized claim, and close the HTTP server in `finally`.

- [ ] Install and verify RED:

```powershell
npm.cmd ci --ignore-scripts --prefix memory-gateway
npm.cmd test --prefix memory-gateway
```

- [ ] Implement `memory-gateway.mjs` with these concrete responsibilities:
  - `GatewayError(code)` exposes only a typed code.
  - `validateInput` rejects unknown keys and enforces the exact bounds above, HTTPS, the project-slug regex, and `^[A-Z][A-Z0-9_]{1,63}$` for `credentialEnv`. Loopback HTTP is accepted only when the explicit test option is true and hostname is `127.0.0.1` or `localhost`.
  - `normalizeClaims` requires an array and the fields `id`, `projectSlug`, `content`, `sourceUri`, and `sourceType`; it rejects mismatched projects, preserves provenance/status/timestamps, truncates only the final content string crossing `maxChars`, and returns `{claims, truncated, responseChars, aiUsage:'not_measured'}`.
  - The real client factory creates `StreamableHTTPClientTransport(new URL(serverUrl), {requestInit:{headers:{Authorization:`Bearer ${token}`}}})` and `new Client({name:'mypeople-memory-gateway', version:'0.1.0'})`.
  - `executeRecall` validates input, gets the token from the injected option or `process.env[credentialEnv]`, connects, races the tool call against a timer, calls exactly the payload below, clears the timer, and closes in `finally`:

```javascript
await client.callTool({
  name: 'recall',
  arguments: {
    projectSlug: request.projectSlug,
    query: request.question,
    limit: request.topK,
    hops: request.hops,
  },
});
```

  - Parse only `result.structuredContent.claims`; prose is never accepted as authoritative data.
  - `main` reads exactly one JSON document from stdin and emits exactly one JSON document to stdout. Top-level errors map only to `unauthorized`, `timeout`, `project_mismatch`, `invalid_response`, `budget_exceeded`, or `unavailable`; no URL, token, response body, or stack is printed.

- [ ] Run GREEN, audit, and commit:

```powershell
npm.cmd test --prefix memory-gateway
npm.cmd audit --omit=dev --prefix memory-gateway
git add memory-gateway
git commit -m "Add bounded read-only MCP memory gateway"
```

## Task 5: Connect bounded recall to TaskSpec compilation

**Files:** `bin/project_context.py`, `verify/test_project_context.py`, `verify/test_memory_gateway.py`

- [ ] Write failing Python boundary tests. Patch `subprocess.run` and prove:
  - request JSON contains `credentialEnv` but never the credential value;
  - the child environment contains the referenced token;
  - command is `node <resolved-memory-gateway.mjs>` with no shell;
  - subprocess timeout is profile timeout plus two seconds;
  - nonzero exit, timeout, malformed JSON, extra stdout, and unexpected error codes become typed `MemoryError` values without stderr/body content;
  - successful requested recall embeds only provenance-complete same-project claims;
  - requested-memory failure becomes `TaskSpecError("memory_<code>")`.

- [ ] Run RED:

```powershell
python verify/test_project_context.py
python verify/test_memory_gateway.py
```

- [ ] Implement `MemoryError(code)` and `call_memory_gateway(profile, question, runner=subprocess.run)`. Resolve `env://NAME`; fail `unauthorized` if absent. Build the validated gateway request with `maxChars` equal to the remaining TaskSpec budget. Run with `shell=False`, `input=json.dumps(request)`, `capture_output=True`, `text=True`, a copied child environment, and `timeout=memoryTimeoutSeconds + 2`. Accept one stripped stdout JSON object only. Map all failures to typed codes and discard raw stderr.

- [ ] Update `compile_task_spec`: when a non-empty question and enabled memory coexist, call the injected recall function or `call_memory_gateway`; validate the envelope again in Python; append claims while preserving the full local contract; set `memoryStatus` to `ok` or `truncated`. If the completed document exceeds `contextChars`, remove or shorten only the last memory claim content. If the local-only document exceeds the limit, fail.

- [ ] After successful `write_task_spec`, append one metadata-only JSON line to `run/taskspec-events.jsonl`: task ID, project slug, profile revision, memory status, claim count, elapsed milliseconds, response characters, and `aiUsage` or `not_measured`. Never log the question, claim content, token, or server URL.

- [ ] Run GREEN and commit:

```powershell
python verify/test_project_context.py
python verify/test_memory_gateway.py
git add bin/project_context.py verify/test_project_context.py verify/test_memory_gateway.py
git commit -m "Integrate bounded MCP recall into task specs"
```

## Task 6: Compile before creating owner workers

**Files:** `bin/mp`, `verify/test_worker_handoff.py`, `verify/test_taskspec_spawn.py`

- [ ] Write failing spawn tests that patch network, roster, and tmux helpers. Record call order and prove compilation occurs before the first window/process operation. Make compilation raise `TaskSpecError("memory_timeout")` and prove tmux/process helpers are never called. Extend handoff tests to prove owner workers receive `MYPEOPLE_TASKSPEC_PATH`, temporary workers do not, and the owner message says `Read the TaskSpec at $MYPEOPLE_TASKSPEC_PATH`.

- [ ] Run RED:

```powershell
python verify/test_taskspec_spawn.py
python verify/test_worker_handoff.py
```

- [ ] Implement `compile_owner_task_spec(task_id)` in `bin/mp`:
  1. GET the authenticated local `/todo/board` endpoint.
  2. Require the task and a non-empty `projectSlug`.
  3. Load `<PROJECT_PROFILES_DIR>/<slug>.json`.
  4. Compile and atomically write under `TASKSPECS_DIR`.
  5. Return the absolute TaskSpec path.

Call it after argument/agent-ID validation and before any host/window branch can create a process. A remote receiving host compiles locally; the sender does not compile twice. On failure, notify Boss only with `[taskspec] task <id> blocked: <typed-code>. Fix the project/profile/context request and retry.`, then exit nonzero without registration or worker creation.

Export `MYPEOPLE_TASKSPEC_PATH` and add non-secret `taskspec_path` to the roster for owner workers. Direct the owner to read TaskSpec before AGENTS.md.

- [ ] Run GREEN and commit:

```powershell
python verify/test_taskspec_spawn.py
python verify/test_worker_handoff.py
python verify/test_codex_boss_switch.py
git add bin/mp verify/test_taskspec_spawn.py verify/test_worker_handoff.py
git commit -m "Compile task specs before owner worker launch"
```

## Task 7: Install, document, and register verification

**Files:** `install.sh`, `verify/verify.sh`, `docs/USER-MANUAL.md`, `verify/test_project_context.py`

- [ ] Add failing text contracts proving `install.sh` contains `npm ci --omit=dev --ignore-scripts` scoped to `memory-gateway`, and the manual contains `ProjectProfile`, `TaskSpec`, `Context question`, `read-only MCP pilot`, and `MYPEOPLE_MEMORY_TOKEN`.

- [ ] Run RED:

```powershell
python verify/test_project_context.py
```

- [ ] Add this locked local installation block after directory setup:

```bash
if [[ -f "$ROOT/memory-gateway/package-lock.json" ]]; then
  npm ci --omit=dev --ignore-scripts --no-audit --no-fund --prefix "$ROOT/memory-gateway"
fi
```

- [ ] Add these commands before `core_verify.py` in `verify/verify.sh`:

```bash
python3 "$VERIFY/test_task_project_fields.py"
python3 "$VERIFY/test_project_context.py"
python3 "$VERIFY/test_memory_gateway.py"
python3 "$VERIFY/test_taskspec_spawn.py"
npm test --prefix "$ROOT/memory-gateway"
```

- [ ] Document profile location and copying the example; project slug/context question usage; compile-before-spawn; disabled/no-question no-network behavior; fail-closed semantics; environment-only credential injection; metadata inspection; and the explicit Phase A boundary: no live Cloudflare deployment, no external memory writes, and no real data.

- [ ] Run GREEN and commit:

```powershell
python verify/test_project_context.py
bash -n install.sh
bash -n verify/verify.sh
git add install.sh verify/verify.sh docs/USER-MANUAL.md verify/test_project_context.py
git commit -m "Document and verify bounded memory setup"
```

## Task 8: Verify in isolation, then update the live container with memory disabled

**Files:** this plan; runtime `/home/mp/mypeople/`

- [ ] Run repository checks before deployment:

```powershell
python verify/test_public_repository.py
python verify/audit_public_history.py
git diff --check
```

- [ ] Verify the full candidate in a disposable, explicitly named container:

```powershell
docker create --name mypeople-phase-a-verify mypeople-node sleep infinity
docker cp . mypeople-phase-a-verify:/home/mp/mypeople
docker start mypeople-phase-a-verify
docker exec mypeople-phase-a-verify bash -lc "cd /home/mp/mypeople && bash install.sh && bash verify/verify.sh"
docker rm -f mypeople-phase-a-verify
```

If any command fails, inspect and fix through a new failing test. Remove only the disposable container created under that exact name.

- [ ] Back up only changed live paths (`bin`, `verify`, `docs`, `examples`, `install.sh`, and `memory-gateway` if present) under `C:\tmp\mypeople-phase-a-live-backup-<UTC timestamp>` and record SHA-256 hashes. Do not copy credentials, recordings, board data, Codex state, or provider profiles into Git.

- [ ] Deploy only verified files without recreating the live container:

```powershell
docker cp bin/. mypeople:/home/mp/mypeople/bin/
docker cp verify/. mypeople:/home/mp/mypeople/verify/
docker cp docs/. mypeople:/home/mp/mypeople/docs/
docker cp examples/. mypeople:/home/mp/mypeople/examples/
docker cp memory-gateway/. mypeople:/home/mp/mypeople/memory-gateway/
docker cp install.sh mypeople:/home/mp/mypeople/install.sh
docker exec mypeople bash -lc "npm ci --omit=dev --ignore-scripts --no-audit --no-fund --prefix /home/mp/mypeople/memory-gateway"
```

Do not configure a memory token and do not enable memory in any live profile.

- [ ] Record health, restart only the TODO service through its current PID contract, then wait for health:

```powershell
(Invoke-WebRequest -UseBasicParsing http://localhost:9933/health).Content
docker exec mypeople bash -lc 'pid=$(cat /home/mp/mypeople/run/todo-server.pid); kill "$pid"; for i in $(seq 1 30); do curl -fsS http://127.0.0.1:9933/health >/dev/null && exit 0; sleep 1; done; exit 1'
(Invoke-WebRequest -UseBasicParsing http://localhost:9933/health).Content
```

Do not kill or restart Boss, Nightwatch, engineers, tmux, Docker, or provider sessions.

- [ ] Run live focused tests and no-memory smoke. Use a temporary profile with `memory.enabled=false`, a temporary card with a project slug and no context question, compile it, and prove there is no gateway invocation. Remove only those test artifacts after saving evidence. Do not run a board-mutating full verifier against active user work.

```powershell
docker exec mypeople python3 /home/mp/mypeople/verify/test_task_project_fields.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_project_context.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_memory_gateway.py
docker exec mypeople python3 /home/mp/mypeople/verify/test_taskspec_spawn.py
docker exec mypeople npm test --prefix /home/mp/mypeople/memory-gateway
(Invoke-WebRequest -UseBasicParsing http://localhost:9900/health).Content
```

- [ ] Run security checks:

```powershell
python verify/audit_public_history.py
git grep -n -I -E "(Bearer [A-Za-z0-9_-]{12,}|AUTH_TOKEN=|MYPEOPLE_MEMORY_TOKEN=.+)" -- .
git diff --check
git status --short
```

- [ ] Request code review with the Phase A base/head SHAs. Fix every Critical and Important finding through a new failing test, then rerun focused, isolated full, and public/security verification.

- [ ] Mark completed checkboxes and commit:

```powershell
git add docs/superpowers/plans/2026-07-14-bounded-memory-mcp-phase-a.md
git commit -m "Complete bounded memory MCP phase A"
```

- [ ] Stop before Phase B external writes. Report evidence and request a separate gate before creating/forking a GitHub repository, pushing, deploying Cloudflare, adding secrets, enabling memory, or importing data.
