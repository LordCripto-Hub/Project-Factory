# Operator Reliability and Surface Consolidation Verification

Date: 2026-08-01  
Branch: `feat/operator-reliability-consolidation`  
Verified implementation commit: `a64c3c9b8d649f64194c20a54b1e0e8c3a583b5c`

## Scope

This verification covers local hybrid-memory readiness, single-flight Board polling, mobile modal viewport handling, authoritative runtime identity, opt-in terminal recording, and the consolidation of operator navigation into Board, Graph, and HUD. It also covers the final minimum interactive-target correction found during visual review.

The implementation reuses the evaluated Gate B hybrid-memory engine and locked dataset. It does not create a second memory store, activate Cloudflare memory, or enable the retired `codex_apps` MCP path. Runtime activation remains guarded by the explicit `automatic` control.

## TDD Evidence

Each implementation area was introduced behind a failing focused contract before the production change. The final visual audit additionally reproduced undersized checkbox/navigation targets in the captured manifest. `verify/test_mobile_modal_viewport.py` was extended to fail on the missing contract, and the shared CSS was then corrected.

Final focused result:

- 36 tests passed.
- 3 live synthetic-pilot tests were skipped by design because `MYPEOPLE_MEMORY_PILOT_E2E` was not enabled.
- No focused failures remained with `PYTHONPATH=bin`.

## Disposable Docker Verification

Candidate image: `mypeople-node:operator-reliability-candidate`  
Embedded source SHA: `a64c3c9b8d649f64194c20a54b1e0e8c3a583b5c`

Build ID: `20260801T193556Z`

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File verify/Invoke-IsolatedVerify.ps1 -Image mypeople-node:operator-reliability-candidate -TimeoutSeconds 1800 -UsePackagedSource
```

Result: exit code `0` in `256.1` seconds with `Isolated MyPeople verification passed.` The verifier used packaged candidate source and disposable state, without mounting live volumes, provider credentials, or sessions.

The emitted `sudo`/`no new privileges` warning is expected in the hardened disposable container and did not bypass or fail any contract.

## Visual Verification

The isolated, network-disabled capture produced 14 paired desktop/mobile screenshots in [`operator-reliability-visuals/after`](operator-reliability-visuals/after):

- Board list and detail
- Graph and Graph detail
- HUD healthy and stale states
- Terminal views

Manifest: [`manifest.json`](operator-reliability-visuals/after/manifest.json)

Automated audit:

- 14 captures
- 0 external requests
- 0 horizontal overflows
- 0 unnamed controls
- 0 interactive targets below the enforced minimum

Representative Board, HUD, and Graph mobile/desktop captures were also inspected manually for legibility, modal containment, evidence rendering, navigation, and preservation of the Scorpion theme.

## Live-System Non-Interference

The following values were recorded before disposable work and matched after final verification:

- Image: `mypeople-node:upgrade-20260801T174621Z`
- Start time: `2026-08-01T17:51:04.537583962Z`
- Restart count: `0`
- Board SHA-256: `e025a45a3fe7eaaedc1c9218251568854449637ece0787e2f608d97ebff20ac4`
- Runtime state: `running`

No disposable MyPeople verifier container remained running. The candidate image was built but was not deployed.

The plan mentioned a stable-roster SHA, but no pre-run roster digest was captured. Therefore this report does not claim a roster-digest comparison. The unchanged image, start time, restart count, Board digest, and absence of a second running MyPeople container are the available non-interference evidence.

## Residual Risks

- The initial candidate reported three vulnerabilities in the `memory-gateway` dependency tree: two moderate findings caused by `@hono/node-server` through MCP SDK 1.29.0, and one high-severity `fast-uri` finding. The approved follow-up upgraded `@modelcontextprotocol/sdk` to 1.30.0 without a major-version change; the final audit reports zero known vulnerabilities.
- Memory readiness proves that the local supervised adapter is available; retrieval quality still depends on project controls, query relevance, and the locked dataset.
- The implementation has passed isolated verification but has not yet been exercised against live state. Deployment requires an explicit approval and the existing backup, migration, health, and rollback gates.

## Deployment Recommendation

The candidate is technically ready for a gated live deployment. Merge, push, and deployment remain intentionally pending explicit user approval.
