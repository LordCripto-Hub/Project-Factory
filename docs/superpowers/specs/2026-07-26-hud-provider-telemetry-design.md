# HUD Provider Telemetry Design

## Goal

Give the operator an immediate, trustworthy view of each active agent's
provider health, model, profile, session alias, and measured token usage without
turning the HUD into a second control plane or exposing credentials.

## Scope

This phase changes only the authenticated HUD and its read-only data projection.
It does not add provider switching, lifecycle controls, account management,
background provider probes, paid API calls, or a second telemetry store.

## Data authority

The HUD projection joins existing authoritative records:

- `run/roster.json` supplies agent identity, backend, model, provider profile,
  lifecycle, and captured Codex session metadata.
- `run/provider-health/*.json` supplies bounded health receipts and staleness.
- validated Codex rollout events supply cumulative input and output token
  counters when the recorded session and session file match.

`todo-server.py` performs the join behind browser authentication and returns a
bounded projection. The browser does not read runtime files or infer health.
Missing or unverifiable data is reported as `not_measured` or `unknown`; it is
never estimated.

## Projection contract

`GET /todo/operator-telemetry` returns:

```json
{
  "ok": true,
  "observedAt": 1785082000.0,
  "agents": [
    {
      "agentId": "node-1/main:Boss",
      "role": "boss",
      "provider": "codex",
      "model": "gpt-5.6-sol",
      "profile": "codex-primary",
      "sessionAlias": "codex:f62a0cc6",
      "health": {
        "state": "authenticated",
        "reasonCode": "session_active",
        "stale": false,
        "observedAt": 1785081990.0
      },
      "usage": {
        "measurement": "measured",
        "inputTokens": 12400,
        "outputTokens": 2100
      }
    }
  ]
}
```

The endpoint includes only non-retired roster entries. It sorts Boss first,
Nightwatch second, then other agents by `agentId`. Session aliases reveal only
the provider and the final eight safe identifier characters. No email, full
session identifier, filesystem path, diagnostic body, secret, or credential
reference is returned.

If a receipt is absent, malformed, or older than the configured threshold,
health is `unknown` and stale. A `process_dead` receipt takes visual precedence
over session metadata. Usage is measured only when the validated session file
belongs to the same provider and session. Otherwise the exact JSON value is:

```json
{"measurement":"not_measured"}
```

The endpoint caps the result at 100 agents and its serialized body at 128 KiB.

## Interface

The existing Scorpion palette remains authoritative. A compact `Combat Status`
strip sits above the agents table:

- charcoal cards use quiet yellow borders and square-technical radii;
- the agent role and shortened agent name lead the hierarchy;
- provider, model, profile, session alias, and token counters use monospace;
- a restrained live dot pulses only when the process is alive and the health
  receipt is current;
- green means authenticated, yellow means unknown/stale, orange means quota
  exhausted, and red means expired, unreachable, or process dead;
- selecting a card highlights and scrolls to the matching table row;
- the table gains `MODEL` and `HEALTH` columns for durable scanability;
- narrow screens use horizontal card scrolling instead of wrapping into a tall
  metric dashboard.

The browser retains the last successful projection if polling fails, marks the
strip `STALE`, stops all live animation, and never replaces the last state with
false `LIVE` data. Empty state copy is `No active provider telemetry`.

## Token semantics

Measured counters are cumulative for the active captured provider session, not
per-task cost. The HUD renders them as `<input> in / <output> out` using compact
decimal notation. It labels missing counters `not measured`. Estimated values
are not part of this phase.

## Error handling and privacy

- The endpoint requires the existing browser session authentication.
- Invalid receipts and rollout events are ignored rather than exposed.
- A single malformed agent record cannot fail the whole response.
- Client rendering uses `textContent`; telemetry never becomes HTML.
- Diagnostic references remain server-side.
- Polling is read-only and performs no provider network request.
- The UI announces stale/live changes through a compact textual label, not
  color alone.

## Verification

TDD must cover:

1. authentication precedes the telemetry route;
2. roster, receipt, session alias, and validated usage join correctly;
3. missing, mismatched, malformed, and stale inputs fail closed;
4. the projection contains no forbidden private fields or full session IDs;
5. ordering and 100-agent bounds are deterministic;
6. the HUD renders every health state, measured and unmeasured usage, empty
   state, row selection, and stale polling behavior;
7. existing provider-health, dashboard, browser, public-repository, and full
   isolated Docker verification remain green.

## Deferred work

Kill, revive, switch-model, relaunch, provider account selection, per-task cost,
and historical token charts remain separate phases. The card structure reserves
space for later controls but this phase adds no mutating action.
