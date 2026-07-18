# Adaptive Routing Live Canary

Use this procedure only after the reviewed image passes focused and isolated
verification. It exercises the live board, TaskSpec compiler, private routing
policy, roster, provider profile, and one disposable Codex owner worker. It
does not prove provider capacity, model quality, or automatic cross-model
replacement.

## Preconditions

1. Retain the backup transaction and rollback tag created by the Docker image
   upgrade.
2. Confirm the control plane and provider are ready:

   ```bash
   mp status
   mp providers-status
   test -s /home/mp/mypeople/run/routing-policy.json
   ```

3. Review the private policy. The task's ProjectProfile slug must have an
   explicit matching entry under `projects`, its allowed models must agree
   with the active provider profile, and its ceiling must permit the expected
   tier. Startup creates the example only when no policy exists; it never
   silently authorizes a new project or overwrites operator policy.
4. Run the installed routing contracts:

   ```bash
   python3 /home/mp/mypeople/verify/test_task_routing.py
   python3 /home/mp/mypeople/verify/test_adaptive_owner_routing.py
   ```

## Execute one disposable route

Create a disposable Priorities task for an authorized project. Give it a
bounded documentation objective, one harmless verification command, and no
critical terms such as production, security, migration, data loss, or
rollback. Keep evidence required and record its `CARD_ID`.

Derive fully qualified IDs from the live roster and spawn without `--model`:

```bash
CARD_ID=<disposable-card-id>
BOSS_ID=$(mp status | awk '$1 ~ /\/main:Boss$/ && $2 == "[alive]" { print $1; exit }')
test -n "$BOSS_ID" || { echo "live Boss not found" >&2; exit 1; }
HOST_ID=${BOSS_ID%%/*}
CANARY_ID="$HOST_ID/main:adaptive-routing-canary"
CANARY_AGENT=$(mp spawn "$CANARY_ID" --backend codex --boss "$BOSS_ID" --owner-task "$CARD_ID")
test "$CANARY_AGENT" = "$CANARY_ID" || { echo "unexpected worker ID" >&2; exit 1; }
export CARD_ID CANARY_AGENT
```

Passing `--model` tests manual allowlist validation rather than adaptive
routing. Reusing an existing owner or using `mp revive` tests receipt reuse
rather than a new classification.

## Expected evidence

The card receives one bounded comment containing:

```text
[routing:<12 hex>] class=simple risk=low tier=economy model=gpt-5.6-luna selection=automatic reasons=... aiUsage=none
```

Reason codes can vary with structural signals. The required observations are
`selection=automatic`, `aiUsage=none`, and the policy-selected tier/model.
Verify the private receipt, roster binding, permissions, and worker:

```bash
python3 - <<'PY'
import hashlib, json, os, pathlib

card = os.environ["CARD_ID"]
agent = os.environ["CANARY_AGENT"]
roster = json.loads(pathlib.Path("/home/mp/mypeople/run/roster.json").read_text())
record = next(item for item in roster if item.get("agent_id") == agent)
receipt_path = pathlib.Path(record["routing_path"])
raw = receipt_path.read_bytes()
decision = json.loads(raw)
assert decision["taskId"] == card
assert decision["selection"] == "automatic"
assert decision["aiUsage"] == "none"
assert decision["model"] == record["model"]
assert decision["tier"] == record["routing_tier"]
assert hashlib.sha256(raw).hexdigest() == record["routing_sha256"]
assert receipt_path.stat().st_mode & 0o777 == 0o600
print(json.dumps({"agent": agent, "tier": decision["tier"], "model": decision["model"]}, sort_keys=True))
PY
mp status
```

Confirm the card contains exactly one comment with the receipt marker. Attach
the sanitized command output and routing comment to the rollout record, then
retire only the disposable worker:

```bash
mp kill "$CANARY_AGENT" --reason adaptive-routing-canary-complete
```

Leave the card and receipt available until review finishes.

## Failure handling

If spawn returns a typed `routing_*` error, no worker should exist. Preserve
the sanitized error, card, policy hash, and logs; verify there is no partial
roster entry, tmux window, receipt, or routing comment. Correct the TaskSpec or
policy offline and rerun focused tests. Never weaken an allowlist merely to
make the canary pass.

If a worker exists but a receipt, hash, permission, model, or comment check
fails, kill only the canary, pause launches with
`mp providers-pause --reason adaptive-routing-canary-failed`, and preserve
the evidence. Do not hand-edit the receipt or roster. Roll back through the
backup-first Docker transaction; never use `docker compose down -v`.

Authentication, quota, infrastructure, and missing-context failures are not
routing escalations. This release calculates a bounded next tier for eligible
typed implementation failures but does not automatically replace the worker.
