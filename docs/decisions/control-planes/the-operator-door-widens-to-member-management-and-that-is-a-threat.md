---
type: Decision
title: "The operator door widens to member management, and that is a threat-model decision (SPEC-217)"
description: "`OPERATOR_ACTIONS` also admits `add_members` and `remove_members`, so whoever can write the operator inbox can grant a stranger live access to a space, and `SenderId` is no fence against them; a requester's refusal is one sentence that distinguishes nothing."
---

`OPERATOR_ACTIONS` was `{transfer_ownership}` and is now `{transfer_ownership, add_members,
remove_members}`. `shared-space-common/config.py` asked that widening it "be a decision rather than
an oversight"; this is the decision, and what makes it one is that the door changes kind rather than
size.

**What changed about the risk.** Under SPEC-208 a row could only move ownership *between people who
were already members*: it granted access to nobody. A row now grants a stranger live S3, Glue and
Lake Formation access to a space's data. What stands in front of that is **who can write the
inbox** — the `SenderId` comparison is not a second fence against them, only against a forged
message from somewhere else, because a file placed in the inbox is enqueued by the reader role and
therefore carries exactly the sender the boundary accepts.

**That write set is wider than "an operator", and the residual is recorded rather than closed.** The
deploy role holds `s3:*` on the admin bucket (`base/policies/github-actions-deploy.json.tftpl`) and
its trust policy admits `repo:<repo>:pull_request` (`github-actions-trust.json.tftpl`), while
`deploy-infra.yml` runs on `pull_request` under that role. So a PR-triggered job can place a file in
the operator inbox. **Pre-existing and unwidened here** — the same path could already move a space's
ownership — but the consequence is larger now, and a doc that described the door as narrower than it
is would be the more dangerous artifact.

**The authorization opens one PR BEFORE the producer, deliberately.** The plane admits the two
actions while the reader still emits `transfer_ownership` only, so the widening is inert: the only
message that can carry the reader's `SenderId` is one the reader sent. The reverse order would put
messages on the queue that the plane refuses. This is the one place the repo's "grants land before
the resources that need them" rule reads backwards, and it reads backwards for the same reason.

**The owner check moved rather than went.** `add_members` and `remove_members` left
`OWNER_ONLY_ACTIONS` for `auth.member_refusal`, which returns a `(code, message)` pair instead of
raising — a raise in the validator loses the actor and the space, so the refusal reaches nobody, and
until this spec a member change that refused was a request the user watched disappear. `authorize`
gained one explicit `return` covering both and a **terminal `raise`**: two actions are now deliberately
allowed there and gated elsewhere, so the fall-through that used to be unreachable became the
failure mode, and losing the predicate call would be an open door rather than a refusal.

**`requester=None` is the operator skip, and it cannot be a flag.** The validator records an operator
request's `actor` as the space's own current owner, so an owner check written against that field
passes for an operator without any skip — and the skip could then be deleted with every test green.
`None` compares equal to no owner, so removing the guard makes every operator request refuse,
loudly. The same trap one action over is already recorded under SPEC-208.

**Four refusals, one sentence, distinct codes.** Unknown space, emptied, not-active and not-owner are
each true and each answers "does this space exist and who owns it" for any name a signed-in user
cares to try — delivered into their own notification inbox. That is the disclosure this project
declined when it refused to publish a shared-space directory. So a **requester** gets one sentence
that distinguishes nothing while the reason **code** stays distinct on `$.error`, and an **operator**
keeps the detail, because the space's owner is who their refusal reaches and is entitled to it.

> **The same oracle is still open on `transfer_ownership`, and is a named follow-up.**
> `transfer_refusal` composes without the collapse, so `TransferNotOwner` and
> `TransferSpaceUnknown` are byte-distinguishable to a non-owner over any space name. Pre-existing;
> SPEC-217 deliberately did not inherit it into two more actions and deliberately did not smuggle
> its fix in here. `_refusal` already takes the `wording=` argument the narrowing would need.

**Two replay residuals, in both directions.** The schedule is hourly and the FIFO deduplication
window is five minutes, so no two sweeps fall inside one, and replay safety rests on the verbs'
idempotency. What that does not cover is a change made in between: a replayed `remove` removes a
member who was legitimately re-added, and a replayed `add` **re-grants** access to someone the owner
removed. The second is the worse one. Recorded, not solved — the fix is a request ledger the plane
does not have.

**The prefix move was gated on the old prefix being empty, and the gate was run.**
`aws s3api list-objects-v2 --bucket <admin-bucket> --prefix 'ownership-transfers/'` returned no
contents — all three sub-prefixes, not just the inbox — immediately before each of the two merges
that depended on it: the one that re-pointed the reader's code, and the one that narrowed its IAM
and deleted the old lifecycle rules. That order matters in both directions. Once the reader points
at `operator-requests/*`, a file under the old inbox is unreadable by the only thing that could
drain it, in a prefix that deliberately has no expiry; and removing an expiring rule while objects
sit under it leaves them with no expiry at all. Neither hazard had a reaper other than the check.

**A removal does not revoke a live session.** The principal tag is stamped when credentials are
vended, nothing in the fleet revokes a token, and the pool client sets no token validity, so the ID
token's one-hour Cognito default is the window plus the life of any presigned URL already minted.
Revocation is what this door is for, so the reader's own module docstring says it where an operator
reads it.

## History

### 2026-09-02

- **Settled:** SPEC-217.
