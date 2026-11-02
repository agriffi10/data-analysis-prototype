---
type: Decision
title: "A role that cannot list a bucket cannot be told an object is absent"
description: "**A role that cannot LIST a bucket cannot be told an object is ABSENT** — S3 answers `NoSuchKey` only to a caller holding `s3:ListBucket`, so every `except NoSuchKey: return None` needs a covering grant or its absence branch fails as a fault. Found live: an unregistered space raised `AccessDenied` out of `cpcommon.registry.load` instead of refusing. **A CONDITIONED grant is sufficient — having no statement is what breaks**, and the simulate misleads here, returning `implicitDeny` with no `s3:prefix` supplied because it answers what IAM decides given your context, never what the service supplies. So scope the condition to the keys read; do **not** widen to an unconditioned admin-bucket list (that discloses every space name, then every roster), and do **not** read `AccessDenied` as absence, which makes a real denial look like a fresh request. The population is swept from the AST, never listed."
---

S3 answers `NoSuchKey` for a missing object only to a caller holding `s3:ListBucket` on that
bucket. To a caller without it, the same missing object is `AccessDenied`. So any code shaped
`except NoSuchKey: return None` has a branch that is reachable only if the execution role behind
it can list — and where it cannot, the absence path fails as a fault, at exactly the moment the
absence is the answer the caller wanted.

**Found in production.** On 2026-08-17 a file send naming an unregistered space raised
`AccessDenied` out of `cpcommon/registry.py:30` under `dat-prod-file-send-execution-role`. That
function returns None for "no such space" and every plane's authorize step is written around the
None; the role held no `s3:ListBucket` statement on the admin bucket at all, so instead of the
`unknown_space` refusal the user got a failed run. Archive, data-quality, table-builder and
table-share had the identical gap, and file-ops hit the same rule on its plan read.

**A conditioned grant is sufficient; having no statement is what breaks.** This is the part worth
writing down, because the intuition runs the other way and an IAM simulate appears to confirm the
wrong answer: `simulate-principal-policy` returns `implicitDeny` for a prefix-conditioned
`ListBucket` when no `s3:prefix` is supplied, which reads as "a `GetObject` carries no prefix, so
the condition fails closed." Production says otherwise. `dat-prod-notifications-writer-role` holds
exactly one list grant, conditioned on `*/user_settings/notifications.json`, and no unconditioned
list anywhere; `load_inbox` returns `[]` only through its `NoSuchKey` branch, and the structured
logs carried, when this was measured on 2026-08-30, thirteen writes at `notifications=1` across
eleven recipients, with the cap at 200 and
every other user's inbox climbing 1→64. Those are eleven first-ever inboxes read as absent. The
one other path to an empty list is a document that exists and is corrupt, and it is ruled out in
the right place: that warning is a **stdlib** logger call, so it reaches CloudWatch rather than the
structured-log corpus, and CloudWatch for that function carries neither it nor an `AccessDenied`
for the life of the grant, which has been conditioned since the day it was written. **A simulate answers what IAM
decides given the context you supply; it cannot tell you what the service supplies**, and that
gap is the same shape as the two traps `deploy-role-iam.md` already records.

So the rule is about the statement, not the condition: **every role must hold a `ListBucket`
statement on each bucket whose absence it reads, scoped by condition to the keys it actually
reads.** Do **NOT** widen to an unconditioned list to be safe — on the admin bucket that hands a
plane every shared space's name and then every roster, which is the disclosure the project
declines by publishing no shared-space directory; the space name is the only thing gating that
read. And do **NOT** fix this by treating `AccessDenied` as absence in code: that makes a real
denial look like a fresh request, and on a create-and-copy path it plans over work already in
flight. Where a denial genuinely must be tolerated it is because the write that follows is
create-only, and `shared-space-common/cache.py` is the one site that earns it.

The population is derived, not listed. `lambdas/test_absence_is_answerable.py` walks the AST of
every production module to find each read whose handler decides absence — resolving codes hidden
behind module constants, behind predicate helpers, and behind a reader one call below the `try`,
each of which hid a real site while the sweep was being written — and requires every one to carry
a disposition. The planes held to the registry grant are derived from their imports, counting
`from cpcommon import registry as reg` as well as the submodule path, so a new plane joins the
population by existing.

Two holes in that claim were found by review and closed, and both are worth knowing because they
are the shape this kind of guard fails in. **A derived population still needs a total mapping:**
the first version resolved a directory to a policy through a list of the six control planes, so
adding a registry read to the DLQ drain — whose policy has no `ListBucket` at all — left the suite
green. An unmapped directory is now a hard failure, which is what makes "cannot be added without
meeting it" true rather than aspirational. **And the plane that OWNS the data was pinned by
nothing:** shared-spaces reads the registry back through its own module rather than through
`cpcommon`, so the import sweep could not see it, and deleting its `AdminRegistryList` left the
whole suite green. It has its own assertion now.

## History

### 2026-08-30

- **Settled:** entered the register.
