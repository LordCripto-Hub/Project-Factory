# Durable Control Queue Design

## Goal

Preserve MyPeople control-plane commands across a queue-server restart without
introducing another service or automatically replaying side effects whose
execution outcome is unknown.

## Storage contract

The queue server stores `run/control-queue.json` in the existing `mypeople-run`
volume. The file uses schema version 1, is written atomically with mode `0600`,
and contains a bounded task map. No credential is stored in this file.

## Recovery semantics

- `queued` commands remain `queued` and can be delivered after restart.
- `delivered` commands become `uncertain` at startup because the old server may
  have died before or after the client executed the side effect.
- `done`, `failed`, and `uncertain` records remain inspectable.
- Only an authenticated explicit retry may move `uncertain` or `failed` back to
  `queued`.

This is an at-most-once automatic recovery policy. It prevents silent loss of
queued work while refusing unsafe automatic duplicates of `send`, `answer`,
`spawn`, `kill`, or `revive`.

## Bounds

All active records are retained. The newest 500 terminal records are retained;
older terminal records are pruned during persistence. Payload and result values
continue to inherit the queue HTTP body limit.

## Verification

Tests cover private atomic persistence, queued recovery, delivered-to-uncertain
recovery, persisted delivery/results, explicit retry, and retention bounds.
