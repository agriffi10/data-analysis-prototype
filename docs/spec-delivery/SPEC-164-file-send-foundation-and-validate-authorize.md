# Completed Spec — SPEC-164: Send Files — Foundation Infrastructure, Request Contract & validate-authorize

## What was completed?

The fifth control plane, and its front door. A user still cannot send a file — nothing is listed
or copied yet — but the privileged path exists, and a request that reaches it is proved
legitimate or refused with a sentence the sender can act on.

- **`infra/modules/file-send/`** — FIFO request queue + DLQ (content dedup **off**), an
  EventBridge Pipe at batch size 1, a Standard state machine, three roles (execution, sfn, pipe),
  two placeholder-zip Lambdas, and the portal role's enqueue policy.
- **`fscommon`** — `config` (the caps and the layout constants, no env reads), `authz` (the source
  question), `paths` (containment), `messages`, `notify`. `cpcommon` supplies every algorithm.
- **`file-send-validate-authorize`** — parses, verifies the token, authorizes the source, checks
  every key, enforces the caps, annotates recipients. **`file-send-notify-failure`** — SPEC-152's
  notification of last resort.
- **Browser** — `enqueueFileSend`, `sqs:SendMessage` on the new queue only,
  `VITE_FILE_SEND_QUEUE_URL` through `.env.example` / `env.ts` / `deploy-app.yml` / the repo
  variable.
- **Three PRs**, in the order the recorded traps require: deploy-role grants (#417) applied before
  the module's resources (#418), which existed before the code and matrix rows (#419).

## Required reading for the next plane that touches Bucket 1

**FR-006: the user-space bucket policy's principal allowlist is hand-maintained, and an explicit
resource-policy Deny beats an identity-policy Allow.** A plane whose execution role is missing
from it is denied by the bucket however correct its own grants are — and for a send the failure is
asymmetric enough to read as a code bug: every `space` recipient succeeds (the shared-space bucket
has no bucket policy) and every `user` recipient fails `AccessDenied`. The change is three parts —
a variable in `modules/data`, the `templatefile()` argument, and root wiring with the ARN as a
**constructed string** (an unknown-at-plan ARN inside a list silently drops the change).

`lambdas/test_user_space_bucket_allowlist.py` now pins it three ways, and was verified against a
deliberate omission rather than trusted.

## Deliberate deviations

- **The envelope is flat: `actor` is the raw token at the top level**, not the spec's original
  `actor.idToken`. SPEC-126's shared drain reads `body.get(token_field)` and `_redacted` replaces
  top-level keys only — a nested token would have notified nobody on every dead-lettered send and
  written the raw JWT to CloudWatch. One envelope shape across five planes beat teaching a shared
  security path a second one.
- **FR-003 AC4's "active member" is the SPACE's status, not the member's join chip** (asked and
  confirmed). `leaving` is not a status in this repo, and reading `pending` as the chip would have
  reversed SPEC-073 — denying a send for files the same user can already browse, download and
  table-share.
- **Two caps, not one.** `SEND_MAX_ITEMS` (200) bounds the per-item work; `SEND_MAX_ITEM_BYTES`
  (96 KiB) bounds the serialised selection. See the decision entry — the count cap cannot bound
  bytes, and the byte cap had to be measured against the Pipe's re-escaped record rather than the
  state.
- **`user_exists` moved up to `cpcommon.cognito`** rather than becoming a third copy; `tscommon`
  re-exports it. **`cognito-idp:ListUsers` was not copied over** — nothing calls it, and this role
  is on the user-space bucket allowlist.
- **No `TimeoutSeconds`, no `TIMED_OUT` rule, no LF-admin designation, no S3 grant on the data
  buckets.** Each is a scope statement recorded in place. SPEC-166 adds the first three together —
  including the deploy-role `events:` grant, which must land and apply *before* the rule.
- **A `NoDataObjectDelete` Deny ships from the first apply.** A send never deletes and never
  overwrites, so making that a property of the role costs nothing today.

## What the three review rounds caught

Every round found something real; two rounds found defects the previous round's *fix* introduced.
Recorded because the shapes recur:

1. **The `athenaresults/` refusal was bypassable by selecting an ancestor.** The rule covered the
   folder and everything under it, but selecting the space root passed both containment rules —
   and SPEC-165 expands a folder by listing its prefix. In a shared space that is other members'
   query results leaving with the send.
2. **`NotifyFailure` could never notify anyone.** The only catch routed through a seed hard-coding
   `actor: null`, so every failure took the no-recipient branch — SPEC-152 satisfied on paper and
   silent in practice, on exactly the cold-start failures it exists for.
3. **The first fix for (2) doubled the state.** Threading the request through `$.raw` kept the
   Pipe's record — which carries the same selection again as an escaped string — beside the
   validated output. The request now comes from `$$.Execution.Input`, which costs nothing until it
   is needed.
4. **The caps model certified a bound it never checked** — twice. First measuring key *characters*
   against the state; then measuring the serialised selection against the state while missing that
   the Pipe re-escapes it into the execution input.
5. **The ASL cross-check missed the two mutations that kill every execution.** It matched a
   hard-coded path prefix, so deleting the `ResultSelector` or renaming the `ResultPath` left the
   suite green. It now derives the chain from the machine; re-verified by mutation, five edits,
   five failures.

## Owed live check

**`docs/testing/e2e.md` §4.9 Send files.** Nothing here has run against AWS. A shared
layer's import-time failure only appears at **cold start**, which no test and no deploy can see
(PR #196), so this must be a real invocation.

## Help & guides

**No change, and that is deliberate.** Nothing user-facing shipped — there is no Send control yet
(SPEC-167). Documenting it now would break SPEC-074 FR-005, which says document only what is
shipped and wired end to end.
