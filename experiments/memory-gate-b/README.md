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

This directory is not imported by `install.sh`, the default Compose deployment,
the Windows launcher, or the runtime supervisor. It is evaluation evidence, not
production memory. Cloudflare and other hosted providers are optional future
adapters to the same recall contract, not dependencies of this experiment.

## Promotion

Promotion requires a separate approved design, controlled live canaries,
measured task-quality improvement, honest token/cost attribution, secure
project isolation, and rollback evidence.
