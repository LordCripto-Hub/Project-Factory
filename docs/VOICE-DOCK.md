# MyPeople Compact Dictation

## Current decision

MyPeople uses one shared 30-pixel dictation control across Priorities, Wall, Terminal Graph, Dashboard, and terminal wrappers. It does not require an OpenAI API key, a paid model, an uploaded audio file, or a server-side transcription route.

Recognition uses the browser's native `SpeechRecognition` implementation. The default locale is configurable and currently set to `es-AR`. Depending on the browser, recognition may use a remote service operated by the browser vendor; native recognition must not be assumed to be offline.

## Use

1. Focus a text box or open a MyPeople terminal wrapper.
2. Click the small microphone or press `Ctrl + Windows`.
3. Confirm that the three animated green bars and the listening state are visible.
4. Speak. Each final phrase is inserted directly into the remembered destination.
5. Click the control or press `Ctrl + Windows` again to stop.

The shortcut works while the MyPeople page has focus and Windows passes the key combination to the browser. If the operating system intercepts it, click the microphone or use Windows dictation with `Win + H`.

## Priorities and forms

The browser inserts text into the last focused `textarea`, `input`, or editable element and dispatches an `input` event. MyPeople never submits the form automatically.

## tmux terminals

The browser sends only final text to `POST /voice/paste`. The backend:

- confirms that the agent belongs to the active roster;
- neutralizes carriage returns, line feeds, and null bytes;
- loads the text into a tmux buffer;
- runs `paste-buffer` against the validated target;
- never sends Enter.

`/terminal?agent=...` provides a same-origin wrapper that combines ttyd with the dictation control. The direct ttyd port remains available for recovery.

## Visible states

- Idle: a small gold microphone with a tooltip.
- Listening: three animated green bars and compact interim text.
- Inserted: confirmation that the phrase was inserted while listening continues.
- Denied or unsupported: a `Win + H` fallback.
- Reduced motion: animation is disabled through `prefers-reduced-motion`.

## Privacy and offline alternative

MyPeople does not store or forward recordings. The browser engine decides whether recognition is local or uses a vendor service.

If fully offline operation becomes mandatory, `whisper.cpp` can be evaluated as an optional profile. It requires a binary, model files, CPU/RAM, and additional maintenance, so it is not part of the minimal runtime.

## Verification

Contracts cover native recognition, configurable locale, the `Ctrl + Windows` latch, compact animation, absence of a paid transcription proxy, and tmux paste without Enter. Browser verification uses a mocked recognizer so automated tests do not request real microphone permission.