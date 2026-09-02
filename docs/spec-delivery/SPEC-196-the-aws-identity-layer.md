# Completed Spec — SPEC-196: The AWS Identity Layer

## What was completed?

The API can act as its caller. It assumes **the existing portal role** with **the same tag set**
read from **the same claims of the same token** the Identity Pool reads today — so **not one IAM
policy, bucket policy or Lake Formation grant was rewritten**, and that is checked artefact by
artefact rather than asserted. Both credential paths run side by side: the browser still holds
Identity Pool credentials and still calls AWS directly for everything. **No feature is ported.**

- **`apicommon/identity.py`** — `UserIdentity`, the tag set, the session name, `assume_user_role`
  with its per-container cache, the two doors (`user_client` / `api_client`), and the single
  expiry retry that replaces `lib/credentialRetry.ts` server-side.
- **`apicommon/planes.py`** — `Plane`, `ROUTE_PLANES`, and a runtime guard that fails closed.
- **`apicommon/errors.py`** — three AWS-side conditions kept apart: 403 `AccessDenied`,
  500 `IdentityUnavailable`, and the 401 this layer never mints.
- **`routes/identity_self.py`** — `GET /_identity/self`, the isolation probe **and its negative
  control**. Scaffolding; SPEC-197 deletes it beside `/_auth/whoami`, on the condition that §D and
  §E have been run.
- **One trust statement** on the portal role, **one STS statement** on the API's execution role,
  three environment values, and `validation` blocks on the two variables that size the tag set.
- **`errorMessages.ts`** — one rule, `IdentityUnavailable`, worded so it reads as neither a
  permission problem nor a stale session.

## Two spec defects, both found by building rather than by reading

**FR-004's arithmetic was off by one.** The spec said "63 + any non-empty prefix exceeds 64". It
does not: the longest catalog-safe username is 63 and STS admits 64, so the **prefix budget is
exactly one character**. Computing the bound instead of asserting it is what surfaced it. The
requirement is unchanged — the session name is the username verbatim — and the reason is corrected
in place: one character is not a namespace, so any prefix worth having overflows, and truncating to
fit collapses two usernames onto one identity.

**FR-009's stack criterion asked for a mechanism SPEC-195 never built.** It cites SPEC-195 FR-007 as
having "settled the mechanism" *and* asks that a record not **contain** a credential written into an
exception message. SPEC-195's mechanism is **preventative** — an interpolation sweep plus a sentinel
test — and `log-foundry` 0.6.0 still offers no way to turn stack capture off. Written literally the
test is red by construction. Settled with Andrew: **prevent, and record the residual.** The sweep
now covers four session-material names, the sentinel test drives a path that genuinely raises
through the span while holding a real assumed session, and the residual is a row in `owed.md`.

## What was measured rather than argued

- **Mutation-tested, thirteen times.** Every guard was broken and watched to redden. One did **not**:
  swapping the failure classifier's two branches changed no outcome, which made the docstring's
  claim about ordering false. The real mechanism is the **wrap** in `_assume` — removing that
  changes two tests — and the comment now says so.
- **The set-equality guard earned itself immediately**, refusing a route declared before its
  handler existed.
- **The prefix budget, the tag-count bound and the credential margin are computed**, each naming
  the budget that sizes it and the schedulable unit.

## Two deviations from the spec as written, both forced, both recorded

**The `sts:AssumeRole` call goes through the API plane's *credentials* but not through its
*door*.** FR-001 asks that STS be reached "through the API plane" and Phase 3 says
`assume_user_role` over `api_client("sts")`. Built, it uses the private constructor. It cannot be
otherwise: `api_client` refuses any route that has not declared the plane, no route declares one,
and assuming happens for *every* route — including the ones that must never reach the execution
role. The plane is right; the declaration mechanism ships with **no live subject** and is exercised
by tests alone until SPEC-200's queue writes, which are the route-declared use it was built for.

**The portal role's trust policy names a principal, so it needed a real dependency edge.** Every
other cross-module role ARN in the composition is a constructed string, because they all feed
bucket-policy *conditions* — `aws:PrincipalArn` comparisons, which are string matches needing no
principal to exist. A trust policy's `Principal.AWS` is **validated by IAM**, so the first draft
(a constructed string, matching the local convention) would have been green on every existing
deployment and would have failed a from-scratch apply with `MalformedPolicyDocument`. It is a
module output reference now, and the reasoning that justified the string is corrected in place.

## What this layer deliberately does not do

**No redactor**, **no `ForAnyValue` floor on `sts:TagKeys`** (a ceiling cannot require the username
tag was stamped, and an unverifiable IAM condition on a role every request depends on is not worth
adding in a spec with no live verification — it goes to SPEC-198), **no presigning** and **no
pagination** — the last two carry tripwires so the spec that first needs them revisits the credential
margin rather than inheriting a silently wrong one. All four are in `owed.md` with their reasons.

## Verification: written, not run

`arc-b-api-container-e2e.md` **§E** is complete and runnable. **None of it has been run** — Arc B's
live verification happens once, at SPEC-202.

> **Read this beside the ledger, not on its own (2026-09-02).** The arc script was deleted when Arc B closed; its durable checks are `docs/testing/e2e.md` §4.18 and its results are in `docs/testing/sessions.md`. **[`owed.md`](../testing/owed.md) is authoritative for what has since been run** — several of the items below have been discharged, and this doc is a record of the day it shipped rather than a live status.
 Every item is a row in `owed.md`. Two mechanisms were
verified **by reading** and are recorded as mechanism only, so a later reader can tell the proof
from a coincidence.

Two items this spec **cannot** discharge are passed on rather than fudged: the **ten slot tags** are
invisible to everything it ships (`spaceCount` comes from the claims and reads the same with every
slot tag dropped) → **SPEC-198**; **Lake Formation** needs an Athena query on the user plane and
there is no route → **SPEC-199**.

## Component inventory: no row, and that is checked

`apps/portal/info/component-inventory/` has no API area file — SPEC-193's ritual did not create one, and every
existing area file covers `apps/portal/`. Nothing here belongs in one of those, so no row was added.

## Help & guides: nothing user-facing, verified and skipped

No route is ported, no screen moves, no wording changes. The only browser-side edit is one rule in
`errorMessages.ts` for a code no shipped surface can yet produce. `helpContent.ts` is untouched and
nothing in it became untrue.
