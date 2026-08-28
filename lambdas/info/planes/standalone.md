# Standalone functions

Not part of a control plane: no Step Function, no request queue, no domain layer. Each is triggered
directly — by Cognito, by a schedule, or by its own queue. They still use `cpcommon`.

| Function | Trigger | What it does |
|---|---|---|
| `pre-signup/` | Cognito pre-signup | username validation and a disposable-email blocklist |
| `post-confirmation/` | Cognito post-confirmation | provisions the new user's Glue database and prefix; `backfill.py` does the same for an already-confirmed user |
| `notifications-writer/` | its own FIFO queue | the **single writer** to a user's notification feed |
| `control-plane-dlq-drain/` | schedule | drains every plane's request DLQ into the notification the user already reads |
| `log-sweep/` | schedule | sweeps the structured-logging queue into one NDJSON object per service per day |
| `user-directory-build/` | schedule | publishes the username directory from the user-space bucket |

## The fences

- **The notifications `create` boundary is a RUNTIME check**, because no SQS condition key reaches a
  message body. It compares the **role-id half** of the `SenderId`, and a refusal **logs and drops,
  never raises** — dead-lettering per forged request would drown the one undrained DLQ.
- **The DLQ drain notifies from the VERIFIED token, never the untrusted body.** The notifications
  DLQ itself stays undrained, deliberately: draining it is circular.
- **The request envelope is FLAT** — `actor` is the raw token at the top level — because the drain
  reads and **redacts** that field flatly. Nested, a dead-lettered request notifies nobody *and*
  writes the JWT to CloudWatch.
- **The username directory is built from S3, not Cognito.** Today Cognito is complete and S3 is not,
  and the client transition reverses exactly that. It is readable by every authenticated user,
  accepted deliberately: usernames only, never emails.
- **One string is four things** — username = S3 prefix = principal tag = Glue database name — so it
  is catalog-safe by construction (`^[a-z][a-z0-9_]{2,62}$`). `pre-signup` is where that is enforced.
- **Structured logging goes through `cpcommon.observability` only.** The logs queue is FIFO, swept on
  a schedule, appended under ETag CAS, retained forever. Messages are literals.

Back to [`../INDEX.md`](../INDEX.md).
