# scheduled-function

One Lambda that runs on a schedule: its execution role and inline policies, the function (a call to
[`../docker-lambda`](../docker-lambda/README.md)), and the EventBridge rule, target and permission
that start it. The caller passes every name, the policies already rendered, and the schedule.

**Every input exists because a caller's value differs.** Its inputs were sized against all four
functions built this shape — shared spaces' transfer reader, the user-directory build, the DLQ drain
and the logs sweep — whose permission statement ids, inline policy names, rule names and role
names do not share a rule, and one of which carries two inline policies and its own trust document.

- **The permission binds to `function_arn`, never the name.** A name is known at plan and lets a
  replaced function take the permission while the plan shows no diff.
- **A policy naming the function's own log group takes that ARN as a constructed string**, so no
  policy waits on the function it permits and nothing cycles.
- **The function waits on every inline policy**, so it never starts under a role that cannot yet
  do its job.
- **A rule with no permission applies green and fails every invoke silently** — the permission is
  part of the module for that reason, not left to each caller.
