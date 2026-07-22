# Memory Gate B Experiment

This provider-neutral experiment verifies that Project Factory can add a small,
grounded, read-only memory result to a real MyPeople TaskSpec without weakening
the local task contract or changing the live runtime.

## What It Proves

- relevant recall returns at most three grounded claims;
- irrelevant recall returns no claims;
- no memory question causes no memory call;
- the locked Project Factory history dataset is bound to source commit
  `80dce6f866329b79061bb1ed6b0594f9fdf2dd45`;
- the disposable fixture has no external network, production volume, Docker
  socket, provider key, or write tool;
- actual provider tokens are `not_measured`; 236 tokens is only the estimated
  TaskSpec memory-context delta.

## Run On Windows

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\experiments\memory-gate-b\windows\Invoke-IsolatedTaskSpecMemory.ps1 -Image mypeople-node:upgrade-20260719T150005Z
```

The launcher requires Docker Desktop and an already reviewed MyPeople image. It
verifies that the live `mypeople` container is unchanged and cleans up its
unique disposable Compose project.

## Run Focused Tests

```powershell
$env:PYTHONPATH = 'experiments\memory-gate-b\src'
python -m unittest discover -s experiments\memory-gate-b\tests -v
```

## Runtime Boundary

This directory is not activated by `install.sh`, the default Compose deployment,
the normal Windows launcher, or the runtime supervisor. The explicitly invoked
`Start-MyPeopleMemoryCanary.ps1` launcher may mount it read-only for one local
canary. This is not general production memory. Cloudflare and other hosted
providers are inactive and are not dependencies of this experiment.

The dataset is public. Because Boss and workers share the `mp` Linux identity,
the canary is not a private-memory isolation boundary and must not receive
private project material. One canary proves bounded activation and rollback;
it does not provide statistical evidence of improved quality or token cost.

## Promotion

Promotion requires a separate approved design, controlled live canaries,
measured task-quality improvement, honest token/cost attribution, secure
project isolation, and rollback evidence.

## Active Live Canary

The first active live canary passed with bounded retrieval, normal Codex owner
routing, evidence, and complete rollback. See
[`artifacts/live-canary-report.md`](artifacts/live-canary-report.md) and
[`artifacts/live-canary-receipt.json`](artifacts/live-canary-receipt.json).

This single useful result validates activation and reversibility. It does not
replace the controlled multi-task comparison required for promotion.

## Controlled Comparison

The controlled comparison locks six public Project Factory history cases. All
six are qualified offline; three aliases are then eligible for paired live
baseline and memory arms in the approved counterbalanced order. The comparison
uses one model for every arm and creates a fresh worker, card, and provider
conversation each time.

Run the offline qualification from the repository root:

```powershell
python experiments\memory-gate-b\scripts\run_memory_comparison_offline.py `
  --dataset experiments\memory-gate-b\datasets\project-factory-history-80dce6f86632 `
  --cases experiments\memory-gate-b\comparison\cases.json `
  --output comparison-offline.json
```

Two executions must have the same `logical_digest`, fixture hash, pass status,
selected evidence identifiers, and escalation decisions. Whole-file hashes are
expected to differ because retrieval latency is an actual observation. The
committed report records one canonical observed run. Memory-context tokens are
estimated, retrieval latency is actual, and provider tokens are
`not_measured` unless the provider exposes attributable counters.

### Stop conditions

Do not begin paired execution if the dataset/source binding, fixture hash,
logical digest, six-of-six result, Docker health, feature flag, project binding,
or zero-resource preflight fails. During paired execution, stop on harmful
output, wrong-project evidence, provider failure, timeout, score refusal,
resource reuse, cleanup failure, or a container restart.

Offline qualification demonstrates deterministic retrieval and scoring over a
locked public fixture. It does not prove production benefit, lower provider
cost, better Boss decisions, or improved real-agent coordination.

### Paired live status

The paired live run is intentionally not recorded yet. Its preflight stopped
before creating any synthetic card or worker because the durable Project
Factory workspace no longer matched the dataset source commit. The typed stop
reason is `workspace_source_mismatch`. A future run must either use a reviewed
workspace pinned to the locked source or qualify a new locked dataset; it must
not reuse these results against a different source revision.
