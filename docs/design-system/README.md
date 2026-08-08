# MyPeople Design System Contract

This directory documents the visual contract for MyPeople. It is a documentation
surface, not a second runtime or a second source of truth.

## Runtime source of truth

The canonical runtime stylesheet is:

```text
bin/mypeople-ui.css
```

It owns the Scorpion palette, typography, semantic state colors, shared focus
behavior, and cross-surface component conventions. Pages may keep legacy token
aliases while they are being migrated, but new UI should use the semantic names.

## Semantic token groups

- `--surface-*`: page, panel, elevated panel, and control surfaces.
- `--text-*`: primary, secondary, tertiary, and inverse text.
- `--border-*`: subtle, strong, and keyboard-focus borders.
- `--state-*`: brainstorm, working, review, blocked, done, and cancelled states.
- `--font-*`, `--space-*`, `--radius-*`, `--shadow-*`: shared craft primitives.

## Component mapping

| Design-system concept | MyPeople surface | Existing behavior to preserve |
| --- | --- | --- |
| Task card | `todos.html` / Priorities | state changes, comments, evidence, CEO review |
| Evidence card | task modal and proof viewer | uploads, hashes, metadata, proof links |
| Agent tile | `dashboard.html`, Graph nodes | readiness, provider health, attach and terminal actions |
| Viewbar | shared page navigation | Board, Graph, HUD, Fleet and terminal links |
| Buttons and badges | shared controls | focus behavior, action endpoints and status semantics |

`wall.html` is retained only as a legacy compatibility route for existing
links and smoke tests. It is not an active product surface and is explicitly
out of scope for the next visual migration. Its eventual removal requires a
separate deprecation pass that updates the server, navigation, tests, and
manual together.

The external static gallery may be copied here in a later documentation phase,
but it must consume this stylesheet instead of defining another palette inline.
It must never replace the task server, the Graph canvas, or the existing evidence
and agent behavior.

## Local catalog

Open [`catalog.html`](./catalog.html) to inspect the runtime component contract.
The catalog uses `../../bin/mypeople-ui.css` directly and keeps only layout rules
local to the documentation page. Its examples are representative markup, not
mock state and not an alternate implementation.
