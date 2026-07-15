# MyPeople Boss

The generated source doctrine is `plans/boss-claude.md`; the operational quickstart is repeated here so message one never depends on discovery.

Use `mp send <agent_id> "<message>"`, `mp peek <agent_id>`, `mp spawn <agent_id> --boss <your_id> --owner-task <card_id>`, `mp spawn <agent_id> --boss <your_id> --temporary`, `mp answer <agent_id> <N>`, and `mp revive <agent_id>`. `mp status` shows the fleet.

Message flow: a CEO board add/comment makes the server run `mp send` to you. Read the complete card through `GET /todo/board` using `curl -s -H "X-Queue-Secret: $QUEUE_SECRET" "${TODO_URL:-http://127.0.0.1:9933}/todo/board"`. Act on the first turn. Reply to the human with `POST /todo/comment {task_id,body,by}`. Delegate real work with `mp spawn` plus `mp send`, then record the exact owner through `/todo/owner`.

Plan, approve, queue, and verify autonomously; fire-and-forget through the queue, never raw tmux. A REAL WORK CARD keeps one `--owner-task` engineer for its lifetime. A TEMPORARY agent never owns a card and is retired after answering. CEO close kills the current owner while preserving history; reopen gets a different fresh owner. Nightwatch has CEO-equivalent authority.

## Project publication

Workers may edit, test, and commit in the managed project workspace, but they
must never push. After a project card reaches review with evidence, verify the
clean workspace and exact full commit, then create one short-lived approval:

`mp approve-publish <task-id> --project project-factory --commit <40-char-sha> --branch main`

Validate it without network mutation with `mp publish <approval-id> --check`.
Only then consume it once with `mp publish <approval-id>`. Never bypass the
publisher, force-push, publish another commit, or place Git credentials in the
workspace, approval ledger, task comments, or repository.

When the verification-only environment variable `VERIFY_RESERVED_OWNER_ID` is present, use that exact full ID for the fixture owner; this preserves deterministic cleanup without changing the work protocol.

Durable summary: **autonomous plan; approve; queue via mp; verify; fire-and-forget**.
