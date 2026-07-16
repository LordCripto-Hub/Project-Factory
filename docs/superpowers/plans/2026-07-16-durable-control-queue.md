# Durable Control Queue Implementation Plan

1. Add failing persistence and recovery tests around queue-server state helpers.
2. Implement a schema-validated atomic queue store in `mypeople-run`.
3. Persist submit, delivery, result, and explicit retry transitions.
4. Initialize recovery before the HTTP server accepts requests.
5. Add the focused test to `verify.sh` and document operator semantics.
6. Run focused Linux and integrated Docker regressions.
