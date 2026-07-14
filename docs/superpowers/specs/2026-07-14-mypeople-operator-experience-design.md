# MyPeople operator experience design

Date: 2026-07-14
Status: approved for implementation

## Outcome

MyPeople remains a compact execution plane. This change adds a global Voice Dock, first-class task evidence, a Scorpion-inspired dark/gold visual system, and a one-click Windows launcher without importing ObsidianBrain, Engram, Canvas, or another memory runtime.

## Constraints

- Reuse the existing task comments/proofs timeline and runtime processes.
- Do not persist microphone recordings by default.
- Never commit API keys or credentials.
- Voice insertion never submits a form or presses Enter.
- Require visual or executable evidence only for implementation and bug-fix tasks.
- Preserve existing board data and container state.
- Use original visual tokens; do not copy Mortal Kombat assets, logos, or character art.

## Task evidence

Extend the existing `proofs` array rather than adding a second artifact store. Every proof can carry kind, URL/body, author, timestamp, original filename, MIME type, byte size, and SHA-256. Supported kinds are text, link, image, video, and downloadable file.

The task modal exposes an Evidence action beside the comment composer. It supports file selection, drag/drop, clipboard images, URLs, and text/log evidence. Evidence appears chronologically in the same thread as comments, with preview for images/video and a download card for other artifacts.

`mp complete` keeps `--proof` and adds repeatable `--proof-file` and `--proof-url`. The worker handoff moves a task to review, never directly to done. A minimal `evidencePolicy` field acts as the TaskSpec contract: `required` for build/fix work and `optional` for analysis. A task requiring evidence cannot enter done unless it has proof and is marked verified by the CEO/Boss review path.

## Voice Dock

A reusable same-origin dictation control is present on Priorities, Wall, Terminal Graph, Dashboard wrapper surfaces, and the MyPeople terminal wrapper. It uses the browser's native `SpeechRecognition` implementation with Spanish `es-AR` by default, so MyPeople needs no OpenAI API key, paid transcription model, uploaded audio file, or transcription proxy.

The control is a small 30-pixel microphone that can be toggled by clicking or pressing `Ctrl + Windows`. While listening, three green bars animate and a compact live status displays interim text. Final phrases are inserted directly into the last focused text field. For a terminal target, the existing server endpoint validates the live agent and pastes through a tmux buffer. It never sends Enter.

If native browser recognition is missing or microphone permission is denied, the control recommends the Windows `Win + H` fallback. Browser recognition may use the browser vendor's remote speech service; a fully offline Whisper runtime remains optional and is not part of this minimal implementation.

## Terminal wrapper

`/terminal?agent=...` is a same-origin wrapper containing the ttyd terminal and Voice Dock. Existing terminal links point to this wrapper. The direct ttyd endpoint remains available for recovery.

## Visual system

The interface uses original tactical-industrial styling:

- soot black `#080807`
- charcoal `#12110e`
- armor `#1c1a14`
- Scorpion gold `#f2c230`
- ember `#ff8a1f` for activity/warnings
- bone `#f4f0df` for primary text
- muted crimson for errors and muted jade for verified success

The signature element is a narrow gold mission rail and clipped-corner evidence cards. Depth comes from borders and surface shifts, not large gradients or ornamental shadows. Green terminal styling is replaced across Priorities, Wall, Graph, Dashboard, modal, badges, and Voice Dock.

## One-click Windows launcher

The repository includes `windows/Start-MyPeople.ps1` plus an installer that creates a desktop shortcut. The launcher:

1. starts Docker Desktop when the Docker engine is unavailable;
2. waits with a bounded timeout;
3. starts the existing `mypeople` container;
4. runs `/home/mp/mypeople/bin/mypeople up --detach` idempotently;
5. verifies `/health`, the queue health, and the writable terminal port;
6. opens `http://localhost:9933/` only after readiness;
7. writes a local log and shows an actionable Windows dialog on failure.

It must never delete or recreate the container automatically. If the container is missing, it reports that recovery/bootstrap is required so existing state is not put at risk.

## Verification

- Unit/contract tests cover evidence metadata, closure gates, native recognition, shortcut latching, safe terminal paste, route wrappers, visual tokens, and launcher behavior.
- Browser journeys cover upload/render, microphone states with mocked SpeechRecognition events, focus insertion, and terminal wrapper navigation.
- Existing focal and full verification suites remain green.
- A real launcher smoke verifies idempotent restart against the current `mypeople` container.

