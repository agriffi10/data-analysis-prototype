---
type: Decision
title: "The membership index is an authorization input, where the username directory is not (SPEC-203)"
description: "**The tag VALUES have two sources, chosen at COLD START, no fallback** — `MEMBERSHIP_SOURCE`, default `claims`, in no Terraform. The other is `memberships/{username}.json`, **admin** bucket: an authorization input, unlike the username directory, safe only because it is **user-unreachable, plane-written, CAS-written**. The user's own `shared-connections.json` is the same shape and **user-writable** — reading it is a bypass. Absence needs a **`s3:prefix`-conditioned `ListBucket`** or it reads as denial."
---

**The registry cannot answer "which spaces is this user in" cheaply.** It is one object per space,
keyed by space name, so the question costs a full listing plus a read per space — on the
credential-minting path, on every request. `s3://{admin-bucket}/memberships/{username}.json` answers
it in one `GetObject`, written under ETag CAS by the six verbs that move a Cognito membership slot
— **amended 2026-09-15: beside the Cognito slot rather than beside the roster fan-out, so a GRANT
lands before the registry commit and a REVOCATION after it** ([the group id
entry](../control-planes/a-group-id-orders-the-starts-not-the-runs-and-what-overlap-costs-on.md)).

**It ships against Cognito, and that is the point.** The index could be built during the transition
but could not be *proved* there: with no claims to compare against, a wrong implementation is
indistinguishable from a right one and the failure mode is a session silently carrying the wrong
spaces. Built here, the same user's membership is knowable two ways — an assertion that expires the
moment the environment moves.

**The rule it inverts, deliberately.** SPEC-146's username directory is *advisory*, and a tripwire
forbids it being an authorization input. This index decides what a session may reach. Three
properties carry that inversion, each asserted: it is **user-unreachable** (admin bucket, not the
user's own prefix), it is written **only** by the plane that owns membership, and it is written
**under CAS, ordered against the registry commit so that no write of it can outlive a revocation**
— which is the amended form of the third property: it used to say "at the registry's own
consistency point", and writing a grant there is what let a delete's revocation land between an
add's commit and its index write.

**The object it is NOT, and the reason that is a sweep rather than a review note.** There is already
an object listing a user's spaces, one `GetObject` away, keyed by username:
`{username}/user_settings/shared-connections.json`. It is in the user's own prefix and the portal
role grants `PutObject` on that whole prefix with no Deny under `user_settings/` — the folder is
hidden client-side only. Reading it would be a complete authorization bypass through a file the
product invites the user to own. A test drives the bypass with the cache seeded under the key
production code would really ask for; a stub deriving the username from whatever key it is handed
answers "absent" to every other key, and the test then passes against an implementation that read
the cache.

**Why per-request scoping cannot work, recorded because it will be re-proposed.** The first draft
scoped the tags to the spaces a request *names* — bounded cost, least privilege, no new artifact.
The query route takes `{sql, database?}` and every base table is fully qualified, so
`SELECT * FROM finance_space.sales` names no space and no database anywhere the API can see, and
the SQL is opaque to the API by design. Every shared-space query would have failed. The copy route
names *two* spaces, which the rule also mishandled.

**The residual is a staleness window, and it is smaller than the one it replaces.** A removal whose
index write is lost leaves a member holding a tag. The claims source has exactly that property and
worse: clearing the Cognito attribute does not reach the user's *existing token* until it refreshes.
The index is read per request, so the window closes on the next request rather than the next
refresh. A second residual is stated rather than found: a stored `status` is stamped at write time
and refreshed by nothing, so a status change with no membership change can leave an entry reading
`active`. The registry stays the authority on status; the sweep in `transition_plan.md` §3.11 reconciles
both.

**Three fences the implementation added because the spec's ACs were wrong about them:**

- **The `ListBucket` is required and its CONDITION is the load-bearing half.** "GetObject and
  nothing else" cannot stand: S3 answers `NoSuchKey` only to a caller holding `s3:ListBucket`, so a
  read-only grant makes an **absent** index — the correct state for every user in no shared space —
  arrive as `AccessDenied`. Conditioned to `memberships/*` on both roles, and asserted by **pattern**
  rather than by presence: `s3:prefix: "*"` is a bucket-wide list wearing a condition.
- **The read cannot be cached with the credentials.** The credential cache is keyed on the whole tag
  set, which is what the read *produces*, so nothing can consult it before the read. One `GetObject`
  per authenticated request and no second cache — a username-keyed one would freeze membership for
  the container's life, which is the defect that key exists to prevent.
- **The name and the username are checked against the catalog rule here — the last check before a
  name becomes an entitlement, and the only one on this path.** A space name becomes a principal
  tag *value* the portal role interpolates into a resource ARN — so a name of `*` would be a
  wildcard grant over every shared space. It was format-checked
  nowhere at all when a space was created; the create path holds the rule now
  ([control-planes](../control-planes/a-spaces-name-is-held-to-the-catalog-rule-where-it-is-chosen-and-the.md)),
  and this check is still the last one before a name becomes an entitlement — the only one for a
  space named BEFORE then, of which `live0922 odd` is a live example. **It fails the WHOLE request,
  not the entry**, so one such space costs its member every credential the day this source is
  chosen. The claims source cannot check either
  without rewriting the byte-equivalence it exists to preserve, so the two sources legitimately
  diverge on a name the rule refuses.

**Two orderings, each asserted by ORDER rather than by end state**, because the end state is
identical either way. `create` writes after the record reaches `active` and **inside** the
provisioning guard: after, because a provisioning space yields no tag; inside, because outside it a
failure leaves an active space whose owner holds no entry and can therefore neither reach it nor
delete it. `delete` and `forget`'s teardown drop **before** `reg.delete`, because the record is the
name lock and an index naming a space whose name is free is an entitlement to whatever is created
next.

**`MEMBERSHIP_SOURCE` is a cold-start choice with no fallback**, and it is in no Terraform. An
unrecognised value raises at import; an empty one is an unset one. A typo that degraded to the
default would produce a working application with the wrong authorization model, invisible in every
response.

`MEMBERSHIP_SOURCE` defaults to `claims`; the other source is this index.

## History

### 2026-09-15

- **Changed:** Index writes moved beside the Cognito slot rather than the roster fan-out, so a grant lands before the registry commit and a revocation after it.

### 2026-08-18

- **Settled:** SPEC-203.
