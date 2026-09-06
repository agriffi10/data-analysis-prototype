# Project ground rules that shape the process


- **Greenfield, no production users yet** — low blast radius for auth/infra changes; don't
  over-engineer migration/rollback for users who don't exist.
- **There IS a backend now, and it is two shapes.** "No backend" was true through the first
  hundred-odd specs and is not any more: an **HTTP API** verifies bearer tokens and serves routes,
  and **eight control planes** run privileged async work. What survives of the old rule is the
  boundary — a feature does not get its own service. The browser's direct AWS surface is now
  presigned S3 bytes, Cognito, and the control-plane `sqs:SendMessage` enqueues; the object surface
  and the catalog went behind the API. The two live rules are **no second API** and **no new
  browser-side AWS SDK call on a path an API route already serves**.
- **Don't add dependencies** without first noting them in CLAUDE.md's Tech Stack.
