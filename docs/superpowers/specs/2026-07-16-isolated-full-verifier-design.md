# Isolated Full Verifier Design

## Goal

Make the full MyPeople verifier incapable of reading or mutating the operator's live board, runtime, provider credentials, or Docker container.

## Architecture

`verify/verify.sh` and `verify/Invoke-IsolatedVerify.ps1` are host orchestrators. Each creates a unique Compose project and temporary evidence directory, then runs one disposable verification container from an explicitly selected runtime image. The Compose service publishes no ports, uses no Docker socket or production volumes, has no external network, drops capabilities, mounts the repository read-only, and masks credential-bearing home directories with tmpfs.

`verify/container-entrypoint.sh` copies the read-only source into disposable storage, creates only synthetic queue credentials and runtime data, starts the runtime inside that container, and invokes `verify/run-suite.sh`. The suite and `core_verify.py` both fail closed unless the isolation marker is present. The existing full checks therefore target only the disposable runtime.

## Lifecycle and evidence

The host enforces a bounded timeout and always tears down its unique Compose project. Exit `0` means success, `1` means the suite failed, `124` means timeout, and `125` means host orchestration or cleanup failed. Successful runs delete their temporary evidence. Failed or timed-out runs retain combined output, Compose state/logs, and in-container runtime logs beneath a printed host path.

## Security boundary

No host `.env`, MyPeople config, named state volume, provider directory, Docker socket, device, capability, or host port enters the container. Known credential variables are explicitly blanked and the suite is launched from a minimal environment. The verifier does not modify production Compose, Tailscale behavior, network defaults, provider authentication, voice/microphone behavior, or UI code.

Provider CLI and Tailnet-dependent checks use local synthetic fixtures. Live provider authentication and remote Tailnet reachability remain separate, read-only operator diagnostics.

## Verification

Contract tests inspect every isolation invariant and exercise fail-closed entrypoints. A disposable smoke uses a harmless command override first, followed by the real suite when the selected local image contains its runtime dependencies.
