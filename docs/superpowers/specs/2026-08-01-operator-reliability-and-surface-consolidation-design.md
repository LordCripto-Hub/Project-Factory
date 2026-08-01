# Operator Reliability and Surface Consolidation Design

**Status:** Approved design awaiting written-spec review  
**Date:** 2026-08-01  
**Repository:** `LordCripto-Hub/Project-Factory`  
**Scope:** MyPeople Board, Graph, HUD, runtime identity, recording lifecycle, and local hybrid-memory health

## Objective

Make the MyPeople operator experience reliable across polling, mobile keyboards, runtime upgrades, recordings, and navigation while preserving the current Scorpion presentation system and all established orchestration, memory, provider, publication, evidence, and recovery contracts.

Development occurs on an isolated worktree from the current public `main`. The live MyPeople container, active authentication, provider sessions, and user data remain untouched until the complete disposable-Docker verification is reviewed and deployment is explicitly approved.

## Delivery Strategy

The changes use one integration branch with small, independently reviewable commits. Board, Graph, HUD, `/health`, browser journeys, and the shared theme overlap heavily; one branch avoids repeated conflict resolution while per-feature tests and commits preserve rollback boundaries.

The sequence is:

1. Diagnose and repair the local hybrid-memory availability contract.
2. Eliminate undersized mobile controls as part of the mobile viewport work.
3. Make Board polling monotonic and single-flight.
4. Make Board and Graph modals virtual-keyboard aware.
5. Expose one authoritative runtime build identity.
6. Make terminal recording explicitly opt-in.
7. Retire Wall and standardize Board / Graph / HUD navigation.
8. Run integrated desktop, mobile, restart, persistence, and disposable-Docker verification.

## 1. Local Hybrid-Memory Availability

### Current observation

The HUD can report automatic memory mode while the latest retrieval status is `memory_unavailable`. The status is valid fail-open behavior, but an enabled local mode must not silently depend on a stopped or missing adapter. Cloudflare memory and `codex_apps` remain disabled; this work concerns only MyPeople's existing local hybrid Gate B path.

### Implementation diagnosis

The automatic control file and ProjectProfile are valid, but the profile still targets the experimental hostname `http://memory-gate-b:18443/mcp`. The only implementation providing that hostname is the opt-in live-canary Compose project. It is stopped and belongs to a separate internal Docker network, while the production container belongs only to `mypeople_default`. The Windows launcher rehydrates the legacy Cloudflare pilot module, whose persistent activation intentionally fails closed, and therefore cannot make the local Gate B adapter ready. The UI is accurately reporting the resulting transport failure.

The repair will promote the already-tested local hybrid adapter into the main runtime supervisor as an opt-in, loopback-only child process. This keeps normal MyPeople operation to one container, uses the immutable dataset shipped in the runtime image, generates only an ephemeral internal bearer capability, and does not activate Cloudflare, `codex_apps`, or a second memory store. Disabled mode starts no adapter. Automatic mode reconciles the local ProjectProfile to a loopback URL and exposes adapter readiness separately from the last retrieval outcome.

### Design

- Trace availability from the Windows launcher and Docker deployment configuration through the memory gateway transport and TaskSpec compilation.
- Keep `memory_unavailable` as a typed runtime outcome for genuine adapter failures.
- When local automatic memory is configured, launch or reconnect only the approved loopback local adapter under the existing runtime supervisor and expose its readiness independently from the last retrieval result.
- Never start Cloudflare, `codex_apps`, or another memory store as a fallback.
- Fail open for task execution, but make the reason visible and actionable in HUD health.
- Preserve bounded top-k retrieval, provenance, deep escalation, exhaustive fallback limits, and all existing token budgets.

### Acceptance

- An isolated runtime configured for local automatic memory reaches a ready local adapter and completes a known retrieval.
- A deliberately absent adapter produces typed `memory_unavailable` without blocking task dispatch.
- Disabled mode launches no memory sidecar or remote MCP.
- No credential, private path, or retrieved content is exposed by health endpoints.

## 2. Monotonic Single-Flight Board Polling

### Current problem

Board refreshes can overlap because the one-second timer calls an async refresh without awaiting the previous request. A slower older response can replace a newer board snapshot and briefly hide a freshly posted comment or evidence item.

### Design

Board polling uses a small client-side coordinator with:

- at most one board request in flight;
- a monotonic request sequence and applied sequence;
- one coalesced follow-up refresh when an update is requested during an active request;
- rejection of any response older than the last applied response;
- preservation of filters, view mode, open modal identity, thread scroll position, sticky-bottom intent, comments, and proofs;
- the existing polling interval, with no higher request frequency.

Mutations request an immediate coalesced refresh. The UI does not optimistically invent server state; it keeps the last confirmed snapshot visible until the mutation response and subsequent authoritative board snapshot arrive.

### Failure handling

Network failures set the existing offline indication and release the single-flight lock. A queued refresh runs afterward. A failed response never clears the current board.

## 3. Mobile Virtual-Keyboard Modals

### Design

Board and Graph share a minimal viewport adapter implemented with existing JavaScript and CSS:

- `window.visualViewport.height` and `.offsetTop` populate scoped CSS variables when available;
- `resize` and `scroll` listeners update those variables through one animation-frame-coalesced callback;
- fallback variables use `100dvh`, with `100vh` as the legacy fallback;
- modal shells are positioned within the visible viewport rather than the layout viewport;
- timeline/thread regions use flex/grid minimums that allow shrinking and internal scrolling;
- the comment composer remains visible above the virtual keyboard;
- form controls use at least `16px` text on mobile to prevent iOS focus zoom;
- all interactive controls meet a minimum 24-by-24 CSS-pixel target, resolving the two undersized controls found by visual audit;
- listeners are removed or remain singleton-safe across page lifecycle changes.

The Scorpion palette, typography, clipped corners, state rails, and focus treatment remain unchanged.

## 4. Authoritative Runtime Build Identity

### Source of truth

The runtime image contains a sanitized build manifest generated during image construction. It includes:

- short Project Factory commit SHA;
- stable build/version identifier;
- safe image reference or digest when supplied by the deployment transaction;
- build timestamp or reproducible build identifier;
- schema version.

The manifest contains no host path, user name, token, credential, remote URL with embedded credentials, or Docker inspection dump.

### Runtime contract

The control plane exposes the same normalized identity through `/health`. Board, Graph, and HUD render one compact build indicator sourced from that response. The indicator status is:

- `live` when the response is current and valid;
- `stale` when the last valid identity is retained after health age exceeds its bound;
- `unknown` when metadata is absent or invalid.

Missing metadata never causes an HTTP failure or blocks the UI. Build-change reload logic compares the normalized runtime identity, not host checkout state or file modification time. No placeholder values are rendered.

## 5. Opt-In Terminal Recording

### Configuration

Recording is disabled by default. It can be enabled only by an explicit runtime setting or assigned agent/provider profile. Resolution is deterministic:

1. explicit agent/profile setting;
2. approved runtime default;
3. `off`.

### Lifecycle

- Normal spawn and revive create no `asciinema` process when recording is off.
- Enabled agents get exactly one recorder attached to the expected tmux target.
- Respawn and exact recovery detect and reuse or safely replace the owned recorder without duplication.
- Kill and retirement stop and reap the recorder before completing lifecycle cleanup.
- Existing cast files and the recordings volume are preserved; no automatic deletion or truncation is introduced.
- Recorder failure does not kill tmux or the agent, but produces visible typed health.
- HUD projects `recording`, `off`, or `unknown` without exposing filesystem paths.

Read-only ttyd, attach behavior, provider switching, exact session recovery, and revive semantics remain unchanged.

## 6. Board / Graph / HUD Product Surfaces

### Navigation

The global operator navigation becomes exactly:

- `Board` → `/`
- `Graph` → `/terminal-graph`
- `HUD` → `/dashboard`

`Priorities` may remain the Board page's visual title. Navigation labels such as `TODO`, `Dashboard`, and `Wall` are removed.

### Wall retirement

- `/wall` returns a temporary safe redirect to Board.
- Wall navigation links and product-surface rendering are removed.
- No standalone Wall polling process or route remains after compatibility handling.
- Any Wall-only behavior is mapped before removal: terminal attach and read-only views remain available through Graph and HUD; agent filters and status remain available through Graph/HUD; ownership remains Board/Graph data.
- The `/todo/wall` compatibility API is removed only after tests prove no retained feature consumes it.
- Shared CSS loses Wall-specific selectors only when Graph/HUD equivalents are covered.

## Cross-Feature Interactions

- Build identity polling must use its own bounded health cadence and must not reintroduce overlapping board requests.
- Mobile viewport updates must not reset modal state, thread scroll, or Board polling state.
- HUD recording and memory health extend existing unified agent cards rather than creating parallel panels or data sources.
- Removing Wall must not remove the iframe/attach URL helpers used by Graph or HUD.
- Runtime identity must be copied into the candidate image by the reproducible image build, not read from the developer worktree at request time.
- No feature may activate remote memory, modify active provider credentials, or change the Boss publisher contract.

## Test Strategy

Each feature follows strict red-green-refactor discipline and gets a focused contract test before production changes.

### Focused tests

- Out-of-order board responses demonstrate the stale overwrite before the fix, then prove rejection and bounded single-flight behavior.
- Mutation/comment journeys prove new comments and proofs remain visible.
- VisualViewport tests cover `resize`, `scroll`, CSS height/offset variables, fallback behavior, composer visibility, scrolling, 16px inputs, and 24px controls.
- Build identity tests verify identical Board/Graph/HUD projection, invalidation, `unknown` fallback, sanitization, and runtime-image provenance.
- Recording tests cover default-off, explicit-on, single recorder, respawn, kill, retirement, retained casts, and HUD states.
- Navigation tests verify identical links, `/wall` redirect, absence of visible Wall references, and retained attach/filter/ownership functionality.
- Memory tests cover enabled local readiness, disabled isolation, typed unavailable behavior, and absence of remote MCP activation.

### Integrated verification

- Run all focused regression suites after each feature commit.
- Build a candidate runtime image from the isolated branch.
- Run the full verifier in disposable Docker with no live volumes, credentials, or network route to live state.
- Execute Chromium and WebKit journeys for Board → Graph → HUD on desktop and mobile viewports.
- Exercise virtual-keyboard geometry using synthetic VisualViewport fixtures and browser-level mobile dimensions.
- Restart the disposable runtime and verify cards, comments, proofs, ownership, recording metadata, and build identity persist without duplication.
- Confirm the live container image, start time, board hash, and roster remain unchanged.

## Security and Privacy

- Public code and documentation remain English-only.
- No new dependency is added when existing Python, JavaScript, CSS, and Playwright infrastructure suffices.
- Health output is allow-listed and sanitized.
- Recording paths stay server-side and cast files remain in the existing persistent volume.
- Engineers receive no new GitHub or provider credentials.
- No active authentication, Codex session, Claude session, provider profile, or secret reference is modified during development or disposable verification.

## Deployment Gate

Completion of implementation does not authorize deployment. The final report must provide, for every feature:

- reproduced bug or missing contract;
- observed failing test;
- minimal implementation summary;
- focused and integrated green-test evidence;
- desktop/mobile visual evidence where applicable;
- interactions and residual risks.

Merge, GitHub publication, and live deployment require a separate explicit approval after that report.
