# Local-Default Networking and Windows Dictation Design

## Goal

Make the standard MyPeople deployment local-only and independent of Tailscale,
while retaining an explicitly activated Tailscale profile. Remove MyPeople's
browser microphone implementation and use Windows dictation (`Win + H`) as the
only speech-to-text path.

## Default network profile

The default volume-backed Compose file publishes every host port on
`127.0.0.1`. It does not request `/dev/net/tun`, `NET_ADMIN`, an auth key, or a
Tailscale daemon. Starting MyPeople from the Windows launcher therefore never
opens a Tailscale login and never depends on Tailscale availability.

The application daemons may continue listening on the container interface so
Docker's loopback-only port forwarding works. The security boundary is the
host-side bind, not a misleading claim that the in-container listener is
private.

## Optional Tailscale profile

Tailscale remains available in a separate Compose override named
`docker/compose.tailscale.yml`. Applying that override explicitly sets
`MYPEOPLE_TAILSCALE_ENABLED=1`, adds `/dev/net/tun`, and grants `NET_ADMIN`.

`runtime-supervisor.sh` and `queue-client.py` treat Tailscale as disabled unless
that exact opt-in flag is present. Existing Tailscale state may be reused from
the durable runtime volume. Provisioning or OAuth is an operator action and is
never triggered by the default launcher.

Cross-host mode remains transport-agnostic through explicit URLs. It may later
use Tailscale, a LAN, VPN, or authenticated reverse proxy without changing the
local default.

## Windows dictation

MyPeople removes the floating microphone control, recording animation,
`SpeechRecognition` code, terminal-paste voice route, shared Voice Dock asset,
and related browser hooks. No transcription API, model, audio upload, or
microphone permission is requested by MyPeople.

The operator focuses any text field or writable terminal and presses `Win + H`.
Windows owns microphone permission, language selection, transcription, and text
insertion. MyPeople has no dictation state to persist or restore.

## Documentation and compatibility

The user manual documents local URLs, optional remote activation, and the
`Win + H` workflow. Public documentation remains English-only. Removing the
Voice Dock must not remove or alter the Scorpion theme, task composer, evidence
UI, terminal wrapper, HUD, Wall, or Terminal Graph.

## Verification

Automated contracts prove that:

- default Compose ports are bound to `127.0.0.1`;
- default Compose has no TUN device, `NET_ADMIN`, or Tailscale enable flag;
- the optional override contains all required Tailscale capabilities and the
  explicit enable flag;
- runtime code never starts or probes Tailscale when disabled;
- no operator page loads a Voice Dock script or renders its control;
- no production file contains browser `SpeechRecognition` or voice-paste
  routes;
- Scorpion theme, Priorities, HUD, Wall, Terminal Graph, terminal wrapper,
  launcher, and Docker persistence regressions remain green.

Container tests are authoritative for Linux-only locks and permission behavior.
No live container is restarted as part of this feature branch.
