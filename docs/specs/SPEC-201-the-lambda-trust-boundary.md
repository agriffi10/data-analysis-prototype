# Spec: The Lambda Trust Boundary — the Planes Stop Verifying Tokens

**ID:** SPEC-201
**Status:** Draft
**Last Updated:** 2026-08-18
**Depends On:** SPEC-011 (the identity is a verified claim, never a caller assertion — the invariant this spec relocates without weakening), SPEC-107/125/156 (`cpcommon.auth` — the repo's one JWKS path, whose control-plane callers this spec removes), SPEC-126 (the DLQ drain — its recipient and its redaction both change here), SPEC-152 (`NotifyFailure` on every plane, and the fleet-test discipline this spec's enumeration copies), SPEC-164 (the **flat** `actor` field, shaped around the exposure this spec closes), SPEC-187/191 (Arc A's file-ops plane — the eighth queue), SPEC-195 (the API is now the only verifier; `Principal.username`), SPEC-196 (the assumed role carrying the user's identity), **SPEC-200 (writes the nested `{"identity": {actor, delegated_by, assurance}}` block while still forwarding the token, and declares the `assurance` literal both specs pin — this spec is meaningless and destructive if built before it)**

## Overview

Eight control planes each verify a Cognito ID token that arrived inside a queue message. That design was
correct while the browser was the sender: the queue was writable by every signed-in user's credentials, so
the message body proved nothing and only a signature could say who was asking.

SPEC-200 changed the sender. The API now verifies the token at the edge (SPEC-195), writes a nested
`identity` block carrying the verified actor into every message, and — because SPEC-200 also removed the
browser's `sqs:SendMessage` grants — is the only principal that may write to the queues. From that point the
per-plane verification is a second check of something already established — and it is the last reason a raw
JWT travels through eight queues, sits in eight state-machine execution inputs, and lands in CloudWatch
whenever a message dead-letters.

This spec removes it. Every plane stops calling `cpcommon.auth`, reads the verified actor out of
`identity` through one shared reader, and **keeps every authorization check it has**. That distinction is
the whole spec: the token
proved *who is asking*; membership, ownership, containment, the space's active status and the recipient
checks decide *what they may do*. Dropping the first is a transport change. Dropping any of the second
removes the product's isolation.

**The removal is two steps inside this spec, and their order is a requirement (FR-006).** Step one is the
plane side: eight consumers require and read the `identity` block while the API is still writing the token
beside it. Only once that is deployed and exercised does step two land — the API's enqueue writer stops
sending the token, and SPEC-200's `Redacted` wrapper, `RequestContext.bearer` and token tripwire are
deleted with it. Reversed or collapsed into one commit, every plane fails closed on the first request
after deploy: no archive, share, send, table build, quality check, shared-space change or notification
action completes, and each plane's own suite still passes.

It is also the arc's main gift to the target-environment migration. `transition_plan.md` §6.1 names the
`cognito:username` readers as the highest-consequence detail in that move, because federated sign-in makes
the claim a synthetic `identitycenter_<subject>` and every reader silently starts operating on the wrong
identifier. After this spec no control plane reads that claim at all.

### What SPEC-200 found and does not own (added 2026-08-29, on its merge)

Five things the switchover surfaced that belong here rather than there:

1. **`dlq_drain.SOURCES` and `_redacted` lose their subject** when the token stops being sent. Both
   exist to blank a JWT out of a dead-lettered body; after the flip there is none.
2. **Shared-space carries an ADVISORY top-level `actor` username** beside the `idToken` it verifies.
   `_redacted` blanks it too, `validate.py` does not read it, and `identity.actor` now supersedes it.
   Removing it changes the wire for no gain until this spec is doing that anyway.
3. **`notifications_writer._resolve_username` branches on `USER_ACTIONS = {markRead, markAllRead}`.**
   The `create` arm is the trusted-producer path, written by the seven notifying execution roles, and
   carries `username` in the body with **no actor and no token**. It is not an enqueue route and it
   must survive this spec's collapse: a `trusted_actor` applied to every path refuses every
   notification the fleet produces.
4. **The `SenderId` boundary now names a role that cannot write, and not the one that can.**
   SPEC-206's runtime check compares the sender's role-id half against the **portal role's** unique
   id — which no longer holds `sqs:SendMessage` on that queue. The API's execution role, which does,
   is not on the list. There is **no live exposure**: the notifications route's declared `action`
   vocabulary is `markRead`/`markAllRead`, and the contract refuses both an out-of-vocabulary literal
   and any undeclared key at any depth, so `create` reaches no declared route. But the boundary should
   be re-pointed deliberately rather than left naming the wrong principal.
5. **`Redacted`, `RequestContext.bearer` and the single-`reveal()` sweep are this spec's to delete**,
   along with the tripwire asserting the token is still sent — in the same commit that stops sending
   it, which is this spec's second internal step and not its first.

## Scope

### In Scope

- **`cpcommon.actor`** — one reader that takes a queue message and returns a trusted `Actor` from its
  `identity` block, replacing every `auth.verified_username*` call site in `lambdas/` (FR-001).
- **Fail-closed acceptance**: a message with no `identity` block, no `actor` in it, an empty `actor`, or an
  `actor` that is not a catalog-safe username is refused terminally, never defaulted and never coerced —
  and the flat `actor` field beside it is never consulted (FR-002).
- **`assurance` and `delegated_by` semantics** — the accepted set, where it lives, and what a plane does
  with a value outside it (FR-003).
- **The isolation invariant**: every authorization check on every plane is unchanged, asserted per plane
  and by mutation, including `notifications_writer`'s trusted-producer branch (FR-004).
- **Deleting the verification, not disabling it** (FR-005): the two `*_ignoring_expiry` entry points, the
  `COGNITO_*` env vars on eight modules' Lambdas, `cpcommon.config`'s two required vars, the DLQ drain's
  token field and its redaction, and the three timeout doors that read a token out of an execution input.
- **The API-side token drop** — the enqueue writer's token field, SPEC-200's `Redacted` wrapper,
  `RequestContext.bearer` and its tripwire test — which is step two of this spec's own cutover, and
  nothing else under `lambdas/api/` (FR-005, FR-006).
- **The cutover order**, both between the specs and inside this one, and what happens to a message already
  in a queue when it flips (FR-006).

### Out of Scope

- **Any new plane behaviour.** No verb gains, loses or reorders a step; no state machine changes shape; no
  cap, lock, guard, notification or reason code moves. The only behavioural difference a user can observe
  is that a request whose `actor` is malformed now fails at a different line with a different detail
  string — and no legitimate request produces one.
- **Any UI change.** No component, hook, service or route is touched. The SPA already stopped enqueuing
  directly in SPEC-200; it calls the API's routes and knows nothing about message bodies.
- **Any API change beyond the token drop.** SPEC-195 owns verification, SPEC-197 the transport contract,
  SPEC-200 the enqueue routes, the FIFO derivations, the `identity` block and the queue grants. The
  **only** edits this spec makes under `lambdas/api/` are the four named in scope above: the enqueue
  writer stops putting the bearer in the body, `Redacted` and `RequestContext.bearer` are deleted, and
  SPEC-200's token tripwire is deleted in that same commit. No route is added, removed or re-shaped, no
  request or response type changes, no FIFO derivation is touched, and the generated TypeScript does not
  move. A diff under `lambdas/api/` outside those four is a review stop.
- **Queue resource policies.** SPEC-200 FR-008 AC5 settled it for the arc: the identity grant is the only
  path to these queues and no `aws_sqs_queue_policy` is added. See *What the provenance actually rests on*
  below for why a `Deny` here would be the destructive shape rather than the safe one.
- **The SPA's own username derivation.** `auth.service.ts` reads `getCurrentUser().username` from Amplify,
  which still runs in the browser under the re-scope. It is not collapsed here and it is not a control-plane
  reader — see *The reader count, against the code* below.
- **`infra/modules/auth/identity-pool.tf`'s `username → cognito:username` principal-tag mapping.** It is a
  sixth site reading that claim and it is retired with the Identity Pool in **SPEC-202**, not here.
- **The machine-facing door.** `delegated_by` and a non-interactive `assurance` land as a *contract* only.
  Nothing mints them, no plane accepts them, and building the authorizer that would is a later arc.
- **Cognito sign-in.** The User Pool, Managed Login v2, the two trigger Lambdas (`pre-signup`,
  `post-confirmation`) and the Hosted UI round trip are untouched. Those two triggers are Cognito service
  integrations, not queue consumers; they never read `cognito:username` and this spec does not visit them.
- **`cpcommon.auth` itself.** It survives, with one caller: the API. PyJWT stays in the layer.

### The reader count, against the code

The brief and `ARCS.md` both carry "five `cognito:username` readers … plus the SPA". Verified against the
worktree on 2026-08-18, **the count holds at five in Python**, and two of the surrounding claims do not.

| Site | Today | After this spec |
|---|---|---|
| `cpcommon/auth.py:71` — the missing-claim rejection inside `_verify` | Reader 1 | Survives, in the API's verifier only. SPEC-195 FR-002 already made the claim name configuration (`OIDC_USERNAME_CLAIM`) |
| `cpcommon/auth.py:143` — `verified_username` | Reader 2 | **Deleted** (FR-005): its only callers were the four validate-authorize verbs |
| `cpcommon/auth.py:167` — `verified_username_ignoring_expiry` | Reader 3 | **Deleted** (FR-005): the relaxation's whole premise was a late message carrying an expired token |
| `notifications-writer/notifications_writer.py:90` | Reader 4 | **Deleted.** Its wrapper becomes a `cpcommon.actor` call with this handler's exception type |
| `shared-space-common/auth.py:44` | Reader 5 | **Deleted.** Same shape, `AuthorizationError` |
| `infra/modules/auth/identity-pool.tf:85` | A sixth site, Terraform | **SPEC-202.** Named here so a reader who counts six is not left wondering which one this spec missed |
| `apps/portal/src/features/auth/auth.service.ts:28` | Reads `getCurrentUser().username` — the same **value**, never the claim string | **Unchanged.** Amplify still runs in the browser under the arc's re-scope, so there is no BFF to derive it from. The later target-environment arc owns it |

Two upstream statements are stale and should not be repeated:

- **`notifications_writer.py` does not have "its own verification path".** `transition_plan.md` §6.1 says it
  is "not routed through `cpcommon`" and cites line 105. SPEC-156 FR-004 removed that duplication in
  2026-08; the file now calls `auth.verify_id_token` and wraps only the exception type. It is still a claim
  *reader*, so the count is unaffected — but a build session hunting for a second `jwt.decode` will not find
  one, and SPEC-195 FR-001's AST sweep now forbids one existing.
- **"After this arc the BFF derives `actor` once."** There is no BFF (the arc's 2026-08-18 re-scope). The
  API derives it, from the bearer token, which is the same collapse by a different mechanism.

### What each plane's envelope carries today, and what it carries after

`parse_sqs_request` is already shared (SPEC-156), so there is one parser and eight *contracts*. They do not
agree, and the disagreement is the trap in FR-002.

| Plane | Token field today | After SPEC-200 | After this spec |
|---|---|---|---|
| shared-space | `idToken` | `idToken`, **plus** a nested `identity` block nothing reads | `identity` only; `idToken` gone |
| table-builder | `idToken` | as above | as above |
| data-quality | `idToken` | as above | as above |
| notifications | `idToken` | as above | as above |
| table-share | **flat `actor` — the raw JWT** | `actor` stays the JWT; `identity.actor` is the username, beside it | `identity` only; the flat `actor` is **gone**, not repurposed |
| file-send | flat `actor` — the raw JWT | as above | as above |
| archive (both modes) | flat `actor` — the raw JWT | as above | as above |
| file-ops (SPEC-187 FR-003) | flat `actor` — the raw JWT | as above | as above |

The block is nested for the reason SPEC-200 FR-004 gives — a flat verified `actor` would overwrite the
field four planes verify — and it **stays** nested: this spec deletes the flat field rather than moving
into it, so at no point is one plane's `actor` a username while another's is still a JWT.

**The bottom four rows are where a wrong implementation is silent, and the window is SPEC-200's deploy to
this spec's second step.** During it, every message carries *both* — `identity.actor`, a username, and a
flat `actor`, a 900-character JWT. A raw JWT and a username are both non-empty strings, so any reader of
the form "take `identity.actor`, and fall back to `actor` if it is missing" passes every test written with
a well-formed fixture and, on a message from before the cutover, builds an S3 prefix, a Glue database name
and a notification recipient out of a JWT. FR-002's criteria are therefore the *shape* of the value **and**
the absence of any fallback — neither is checkable by presence.

### What the provenance actually rests on

Trusting a body field is sound only because the queue is unwritable by anyone but the API. That property
arrives with **SPEC-200 FR-008**: the API's execution role gains `sqs:SendMessage` on exactly the eight
request-queue ARNs, the portal role's eight `Enqueue*` statements are removed in the same change, and an
enumerated `.tftpl` sweep — derived from the modules on the filesystem, not from a list — fails if any
policy attached to the portal role grants `sqs:SendMessage` on a request queue again. This spec adds
nothing to that and **must not**.

The shape a reader reaches for here is a queue resource policy with an explicit `Deny` and a
`StringNotEquals` on the API role's ARN, on the argument that an absent identity grant is a fact about one
document while a resource policy is structural. It is the wrong instrument, and on one queue it is
destructive: the **notifications request queue has eight writers**, of which SPEC-200 removes exactly one.
The other seven are execution roles that notify — the shared-spaces orchestrator, table-builder,
table-share, data-quality, file-send, archive and the DLQ drain — with Arc A's file-ops plane an eighth. A
blanket `Deny` denies all of them, and it presents as nothing at all: SPEC-172's producer runs with
`ResultPath: null` and a `Catch` leading onward and deliberately cannot fail its run, and every other plane
notifies best-effort. Archives, shares and sends would complete and users would simply never be told.
Enumerating the seven exceptions is the hand-maintained allowlist whose failure mode SPEC-164 FR-006
already records — a missing principal half-works — arriving before the policy shipped.

### Premises SPEC-202 must honour

1. **The queues are the API's, and the browser has no path to them.** SPEC-200 FR-008's grant removal and
   its enumerated `.tftpl` sweep are what make every acceptance criterion below sound. SPEC-202 retires
   the Identity Pool and with it the portal role, and **the sweep must survive that deletion** rather than
   be tidied away as vacuous: it is enumerated over the modules, so it keeps catching a re-added grant on
   whatever role a later spec attaches to the browser's successor. Adding a queue resource policy instead
   is not the safe substitute it looks like — see *What the provenance actually rests on* above.
2. **`cognito:username` is read in exactly one place in `lambdas/` after this spec, and it is
   configuration-driven.** SPEC-202's sweep of the claim should find the API's `OIDC_USERNAME_CLAIM` value
   and `identity-pool.tf` line 85, and nothing else.
3. **`assurance` is the extension point.** A later arc's machine-facing door widens the accepted set in one
   module (FR-003). It must not add a parallel field, and it must not reach the widening by making an
   unknown value permissive.

---

## Functional Requirements

### FR-001: One trusted-actor reader

#### Description:

Five claim readers and eleven `auth.verified_username*` call sites collapse into one function. It takes the
parsed request body and returns the trusted actor; it does no cryptography, makes no network call, and reads
no environment variable. Every plane calls it, including the three that reach it through their own exception
type — using `parse_sqs_request`'s established `exc=` factory pattern rather than forking.

#### Acceptance Criteria:

- [ ] `cpcommon/actor.py` exposes `trusted_actor(req: Any, *, exc: Callable[[str], Exception] | None = None)
      -> Actor`, returning a frozen `Actor(username, delegated_by, assurance)` built from **`req["identity"]`
      and nothing else**. It raises `TerminalError("unauthorized", detail)` by default, or `exc(detail)`
      when supplied.
- [ ] The four validate-authorize verbs (shared-space, table-builder, data-quality, file-send), the
      table-share and archive validate verbs, `notifications_writer`, and file-ops' validate verb all obtain
      their actor through it. `shared-space-common/auth.py::verified_username` and
      `notifications_writer.py::verified_username` are **deleted**, their call sites passing
      `exc=AuthorizationError` — so both planes' `Catch` behaviour and every pinned message string are
      reached by the same exception type as today.
- [ ] An AST sweep over `lambdas/` finds **zero** calls to `cpcommon.auth`'s entry points outside
      `lambdas/api/`, and **zero** occurrences of the literal `cognito:username` outside `cpcommon/auth.py`.
      It fails if a new one appears. (This is the same sweep shape SPEC-195 FR-001 introduced for
      `jwt.decode`; extend that test rather than writing a second.)
- [ ] `trusted_actor` makes no boto3 call and imports neither `jwt` nor `cpcommon.auth`, asserted by an
      import sweep of the module — a reader that could verify is a reader that will grow a second verifier.

### FR-002: Fail closed, enumerated over every consumer

#### Description:

A message whose `identity` block is absent or malformed, or whose `identity.actor` is empty or not a
catalog-safe username, is refused. There is no default, no fallback to the flat `actor` field beside it, no
fallback to a body-asserted `username`, and no coercion. The enumeration proving every consumer does this
must be **derived**, because a hand-maintained list of planes rots — a ninth plane would be added to the
fleet and not to the list, and the test would keep passing.

#### Acceptance Criteria:

- [ ] `trusted_actor` refuses, with reason `unauthorized` (or the caller's `exc`), when `identity` is
      absent, `None`, or not a mapping; and when `identity["actor"]` is: absent; `None`; a non-string; a
      blank or whitespace string; or a string not matching `config.CATALOG_IDENTIFIER_RE`
      (`^[a-z][a-z0-9_]{2,62}$`).
- [ ] **The flat top-level `actor` is never read, and that is the criterion that can fail.** A message
      shaped exactly like the pre-cutover envelope on table-share, file-send, archive and file-ops — a flat
      `actor` holding a real three-segment JWT string and **no** `identity` block — is refused, and the
      refusal names the missing `identity` block rather than anything about a token. Every reader that
      falls back to the flat field passes a presence check, passes every well-formed fixture, and builds an
      S3 prefix out of a 900-character JWT on the first stale message. Asserted with the flat field present
      *and* absent, so the fallback cannot hide behind an incomplete fixture.
- [ ] **A JWT-shaped `identity.actor` is refused by the shape rule**, asserted with the same real token
      string. Nothing the API mints can produce it; the criterion exists so the shape rule is the guard
      rather than a comment, and it fails against an implementation that only checks presence.
- [ ] A body carrying `username`, `user`, `owner`, `sub` or a flat `actor` alongside a missing or malformed
      `identity` is still refused — the refusal names the missing field and no other field is consulted.
      Asserted per name, because the failure mode is a well-meaning fallback added later.
- [ ] **The enumeration is derived from two facts neither of which a spec author writes down:** the deploy
      matrix rows in `.github/workflows/deploy-lambdas.yml` (already read as data by
      `lambdas/test_deploy_matrix.py`), intersected with the modules whose AST contains a call to
      `events.parse_sqs_request`. Every module in that intersection must obtain its actor through
      `cpcommon.actor.trusted_actor`. A new plane that does not deploy does not exist; a new plane that
      deploys and parses a queue message is in the set automatically.
- [ ] A **guard-the-guard** test asserts the intersection is non-empty and has the expected cardinality at
      the time of the build, and fails if the parse-call detection goes trivial (matching zero modules, or
      every module) — the failure SPEC-153 records for its own copy-list parse.
- [ ] Each module in the enumeration has a test invoking its handler with an `identity`-less message and
      asserting a terminal refusal with **no** S3, Glue, Athena, SQS or Step Functions call made. The
      no-call half is load-bearing: a plane that refuses *after* listing a prefix has already used the
      caller's non-identity as an existence oracle.

### FR-003: `assurance` and `delegated_by`

#### Description:

`assurance` says how strongly the API established the actor. Today it has exactly one minted value. The
point of shipping the field now — rather than with the machine-facing door — is that the alternative
re-opens eight message contracts, eight parsers, SPEC-126's redaction and eight log-record shapes later.

The decision that makes it worth shipping is **fail-closed on an unknown value**. A plane presented with an
`assurance` it does not accept refuses the message terminally. It does not downgrade it, ignore it, or treat
an unrecognised value as the default. Nothing mints anything but the accepted value today, so the refusal is
unreachable in production — and that is precisely its purpose: when a later arc mints `delegated`, every
plane refuses it until that plane is deliberately widened, rather than silently treating a machine principal
as a human at a keyboard.

#### Acceptance Criteria:

- [ ] `cpcommon.actor` declares `ASSURANCE_INTERACTIVE = "interactive"` and
      `ACCEPTED_ASSURANCE = frozenset({ASSURANCE_INTERACTIVE})` — **one** definition, in the shared layer.
      No plane declares its own accepted set, asserted by a sweep for a second `frozenset` of assurance
      values anywhere in `lambdas/`.
- [ ] **The literal agrees with the one SPEC-200 mints, by import rather than by restatement.** A test
      asserts `ASSURANCE_INTERACTIVE` equals the value in `apicommon/identity_block.py` — `conftest.py`
      puts every layer on `sys.path`, so one test imports both. Two hand-written copies of one string in
      two suites is exactly the shape that let this contract disagree across the two specs while both
      suites passed.
- [ ] `interactive` means: the API verified an OIDC ID token presented by an interactive browser session
      (SPEC-195 FR-001) and took the username from the verified claim. It is the only value SPEC-200's
      enqueue routes mint. It names the assurance **kind**, not the mechanism, so a provider swap or a
      later machine-facing `delegated` needs no rename.
- [ ] An `identity.assurance` outside `ACCEPTED_ASSURANCE` — including the reserved-but-unminted
      `delegated`, an empty string, a non-string, and an absent field — is refused with a registered reason
      `unsupported_assurance`, distinct from `unauthorized`. The absent case is refused too: a missing
      `assurance` must not read as `interactive`, or the field's fail-closed property is decorative.
- [ ] `identity.delegated_by` is `None` for every message this arc produces, and is required to be
      **present** — SPEC-200 FR-004 stamps an explicit `null` rather than omitting the key, so an absent
      one is a malformed block. A non-`None` `delegated_by` is refused
      with the same `unsupported_assurance` reason while `ACCEPTED_ASSURANCE` holds only `interactive` —
      the two fields cannot disagree, and a delegated actor arriving under an interactive assurance is the
      exact confusion the pair exists to prevent.
- [ ] `assurance` and `delegated_by` appear on every span the eight planes emit, through
      `cpcommon.observability`, beside the existing `actor` field. They are user metadata and carry no
      token, so the SPEC-130 field rule permits them; `env` and `version` are already populated
      (SPEC-186 FR-005) and this must not regress.
- [ ] `unsupported_assurance` is registered in `cpcommon.messages` with a user-facing sentence that says the
      request could not be started and does not mention assurance, tokens or delegation (SPEC-106) — the
      operator detail carries the value.

### FR-004: Every authorization check stays

#### Description:

**Dropping a verification is not dropping an authorization.** The verification answered "is this really
alice?"; the authorization answers "may alice do this?". The API answers the first now. Nothing answers the
second but the plane, and a spec — or a build — that treats the two as one removes the product's isolation
while every legitimate user's experience stays identical.

The checks that must survive, per plane, enumerated so no build session has to infer the list:

- **shared-space** — `auth.authorize`'s whole matrix: create-any, owner-only for add/remove/delete, the
  owner-cannot-leave rule, member-only for leave and acknowledge, the missing-space refusal.
- **table-builder / table-share / data-quality** — the actor's own prefix or an **active** membership of the
  named space; containment of every source and destination key within the authorized root.
- **file-send** — `authz.authorize_source` on the space's active status (never the member's join chip,
  which reverses SPEC-073), the three containment rules, the per-recipient guard, and the recipient
  existence check through `admin_get_user`.
- **archive / restore** — the same source authorization, the reserved-name and reserved-root refusals, and
  the absolute destination guard.
- **file-ops** (SPEC-187 FR-005/FR-006) — both-sided authorization, both-sided containment, the
  protected-location refusals.
- **notifications** — two branches, and only one of them has an actor at all. `_resolve_username` tests the
  action against `USER_ACTIONS = {markRead, markAllRead}`: those are user-originated, and for them the
  inbox is keyed by the trusted actor while any body-supplied `username` is ignored (SPEC-058) — now *more*
  important, not less, because the field it ignores sits beside one it trusts. The `create` branch is the
  **trusted-producer** path: it is written by the seven control-plane execution roles, never by a browser
  and never through the API, and it carries `username` in the body with **no actor and no token**. It has
  never had one to verify and this spec does not give it one.

#### Acceptance Criteria:

- [ ] For each plane, a test constructs a message with a **well-formed, accepted** `actor` naming a user who
      is not authorized, and asserts the same terminal reason code and the same operator detail string as
      the equivalent test asserts today. A JWT-based negative test that only proved "the token was bad"
      would pass vacuously here, because there is no token — so every such test is re-expressed as an
      authorization negative, not deleted.
- [ ] Every plane's existing authorization test file changes **only** in how the message is constructed. The
      assertions — reason codes, message strings, call counts — are byte-identical. A diff touching an
      assertion in an authorization test is a review stop.
- [ ] **Verified against a deliberate violation, per plane, not read from the diff:** deleting any single
      authorization branch reddens at least one test in that plane's suite. Run it and record the count in
      the delivery doc; this repo's history is that a fork whose two operands always agree passes forever.
- [ ] `notifications_writer` still ignores a body `username` on a **user action** when the `identity` block
      is present and valid, asserted with both set to different users and the inbox written to
      `identity.actor`'s.
- [ ] **SPEC-206's sender check survives this rewrite, and every `create` fixture here must carry a
      service `SenderId`.** SPEC-206 added a guard in `process` — ABOVE the `_resolve_username` call,
      because that call runs before any branch — refusing a `create` whose SQS-stamped `SenderId` names
      the portal role, and refusing one that carries no `SenderId` at all. Two consequences for this
      spec, and the second is the one that bites: the guard must not be collapsed into
      `trusted_actor` (it is not an actor decision — it asks whether the SENDER was entitled to be a
      trusted producer, and the `create` body still carries no token), **and the criterion below is
      false as written unless its fixture supplies a service sender**, since a record with no
      `attributes` is now a refusal rather than a write. A fixture that gets refused and is then
      "fixed" by deleting the guard is the failure mode this line exists to prevent.
- [ ] **`_resolve_username`'s branch survives, and the `create` path keeps taking its username from the
      body.** `trusted_actor` replaces the `verified_username(req.get("idToken"))` call on the
      `USER_ACTIONS` arm **only**; the `create` arm is untouched, still refusing a missing or non-string
      `username` with `ValidationError("create requires a username")`. Asserted three ways, because this is
      the criterion whose omission is silent and total: a `create` with a `username` and **no** `identity`
      block writes the inbox and succeeds; a `create` whose body also carries an `identity` block is
      written to the body's `username`, not the block's actor; and a `markRead` with a `username` and no
      `identity` block is still refused. A `trusted_actor` hoisted above the branch — the obvious
      simplification, and the shape a "one reader, every call site" sweep pushes toward — refuses **every
      notification the fleet produces**, which is the same silent outcome as an over-broad queue policy and
      is reachable independently of it.
- [ ] The fleet enumeration of FR-002 therefore asserts `notifications_writer` obtains its actor through
      `trusted_actor` on **at least one** path rather than on every path, and names the exemption. A rule
      of "every `parse_sqs_request` module calls it unconditionally" is the one that breaks `create`.
- [ ] The `authorize` / `authorize_source` functions themselves have **zero** diff. Their inputs already
      took a plain username string; only where that string came from changes.

### FR-005: The verification is deleted, not disabled

#### Description:

Leaving the verification path wired but unreached is the outcome that looks finished and is not: the env
vars stay required, the tokens keep flowing until someone notices, and the exposure this spec exists to
close stays open. Seven things come out together, and the last four are the ones a build session forgets
because they are not in `auth.py`. The last of them — the API's own write — is **step two** of FR-006's
order and does not land in the same commit as the first six.

#### Acceptance Criteria:

- [ ] `cpcommon.auth.verify_id_token_ignoring_expiry` and `verified_username_ignoring_expiry` are
      **deleted**. Their entire premise — a dead-lettered or timed-out message is old by construction while
      an ID token lives an hour — describes a token that no longer travels. SPEC-195's Premise 3 ("for the
      DLQ drain and nothing else") is superseded in place: it is for nothing, and both functions are gone.
- [ ] `COGNITO_USER_POOL_ID` and `COGNITO_APP_CLIENT_ID` are removed from every control-plane Lambda's
      environment in Terraform, and `USER_POOL_ID` / `APP_CLIENT_ID` are removed from
      `cpcommon.config._REQUIRED_VARS`. That map is a fleet-wide contract (SPEC-168's decision), so the two
      removals happen there and not by per-plane override. The API sets its own `OIDC_*` variables
      (SPEC-195) and is unaffected.
- [ ] **The env removal and the code removal ship in one change.** Removing the variable while a function
      still reads it is a `RuntimeError` at first use — the cold-start class this repo has been bitten by
      (PR #196, SPEC-137). Removing the read while the variable stays is harmless and is the safe ordering
      if the two must split; say which was done in the delivery doc.
- [ ] **SPEC-126's DLQ drain takes its recipient from `identity.actor`**, trusted because SPEC-200 FR-008
      made the API the only writer, rather than by cryptography. `Source.token_field` and the per-source
      `idToken`/`actor` disagreement are deleted — the field is the same on every source, so the
      per-source column goes rather than being set to one value. **`SOURCES` holds six rows, not eight**
      (data-quality, table-builder, table-share, shared-space, file-send, archive), becoming seven with
      Arc A's file-ops: **notifications is deliberately absent**, in `UNDRAINED_QUEUES` by SPEC-126's
      circularity decision, and a spec or a build that counts eight here will try to add it back. The
      drain's every-message-is-total property, its delete-what-it-reads behaviour, and the undrained
      notifications DLQ are unchanged.
- [ ] **The drain's redaction changes shape and does not disappear.** There is no token to redact, so
      `_redacted` no longer strips the flat `actor` — and it must not be pointed at `identity` instead: the
      replacement is **top-level only**, so it would blank the block the drain has just taken its recipient
      from while leaving nothing sensitive removed. It must still bound and redact the logged body, because
      a dead-lettered request body still carries user paths and space names. A test asserts a real
      dead-lettered body reaches `logs/service=dlq-drain/` with **no** field longer than the existing
      `_MAX_BODY_CHARS` bound, with no substring matching a JWT's three-segment shape, and with
      `identity.actor` still readable.
- [ ] The three timeout doors — `fs_notify_failure`, `ts_notify_failure`, `ar_notify_failure` — read the
      actor out of the execution input as a plain string through `trusted_actor`, with the same
      unattributable-event degradation as today (a logged no-op, never a guessed inbox). SPEC-161's
      recorded reasoning that "by construction that token is expired" is superseded in place at every doc
      site stating it.
- [ ] **The API stops writing the token, and this is the change that closes the exposure.** In the commit
      that does it: the enqueue writer drops the token field from every message body, SPEC-200's
      `Redacted` wrapper, `RequestContext.bearer` and its single `reveal()` sweep are deleted,
      SPEC-197 Premise 6's superseded marker is reverted to the un-narrowed claim, and **SPEC-200 FR-005
      AC2's tripwire — "the token is still being sent" — is deleted in the same commit**, because it is
      written to fail on exactly this edit. Nothing else under `lambdas/api/` is touched.
- [ ] **The exposure is closed, asserted rather than argued:** a message dead-lettered on each of the eight
      queues is read back from CloudWatch and from `logs/`, and neither carries a three-segment JWT-shaped
      string. This is the observation the whole spec is for, it cannot be made offline, and it is only
      meaningful **after** the criterion above — run before it, it fails for the right reason.

### FR-006: The cutover, and the message already in the queue

#### Description:

SPEC-200 wrote the `identity` block **while still forwarding the token**, precisely so this flip can happen
on the consumer side with the producer already correct. The reverse order — stripping the token first —
breaks all eight planes the instant it deploys, because every one of them still requires it.

**There are therefore two orders, and the inner one is this spec's own.** Step one: the eight consumers
start requiring `identity` and stop calling `cpcommon.auth`, while the API is still writing the token
beside the block. Step two, and only once step one is deployed and exercised: the API stops writing the
token (FR-005). Collapsing them into one merge re-creates exactly the failure the outer order exists to
prevent, with the added property that both suites still pass — the planes' tests are written against
`identity` and the API's against its own output, and nothing in either sees the other's envelope.

There is still one window, and it is between step one's deploy and the queue draining. A message enqueued
before carries the old envelope; a message enqueued after carries the new one. The old one has a flat
`actor` and **no `identity` block at all**, so FR-002 refuses it — correctly, and with **no notification**,
because there is no trusted recipient to send one to and nothing in the message may be believed. That is
the honest outcome and it is preferable to the alternative. Between step one and step two the envelope
carries both fields and every plane reads only the block, which is why that stretch is safe to sit in.

#### Acceptance Criteria:

- [ ] The deploy order is stated in the delivery doc and followed: SPEC-200's API and producer changes are
      live and exercised **before** any Lambda in this spec deploys.
- [ ] **The inner order is a merge boundary, not a commit boundary within one PR.** Step one's Lambdas are
      deployed and step one's per-plane live check (Phase 5) has run before the step-two change is merged.
      A test cannot assert this; the delivery doc records the two deploy timestamps and the check between
      them, and SPEC-200's tripwire is what fails CI if the two are attempted together.
- [ ] The eight request queues are confirmed empty (`ApproximateNumberOfMessages` and
      `ApproximateNumberOfMessagesNotVisible` both zero) immediately before the Lambda deploy, and the
      figures are recorded. They are almost always empty — SPEC-126 replaced four event-source mappings
      with a sweep for exactly that reason — so this is a cheap confirmation, not a drain procedure.
- [ ] A deliberately-staged pre-cutover message (old envelope: a flat `actor` holding a raw JWT, no
      `identity` block) on one plane is refused terminally with `unauthorized`, produces **no**
      notification, and dead-letters. Its body in `logs/` is bounded and carries no JWT (FR-005). Staged on
      purpose, because it is the one failure this cutover can produce and reasoning about it is not the
      same as seeing it.
- [ ] **The allowed-field sets are not tightened, and the staged message is why.** SPEC-200 added
      `"identity"` to file-send's, both of archive's and file-ops'; this spec leaves the flat token field
      in place there. Removing it makes the staged message a `malformed_event` before `trusted_actor` ever
      sees it, which is a different reason code, a different notification decision and a criterion above
      that silently stops testing what it names. A test asserts the four sets are byte-identical to
      SPEC-200's.
- [ ] Rollback is stated, and it has a shape rather than a direction: after **step one**, reverting this
      spec's Lambdas restores token verification while SPEC-200's producer is still sending the token, so
      the revert is clean. After **step two** it is not — the producer no longer sends a token for a
      reverted plane to verify, so the recovery is forward (re-deploy step one's Lambdas), not backward.
      The delivery doc says which side of that line each deploy landed on, and the step-two merge is
      identified as the one that cannot be rolled back.

---

## Data Model

```python
# lambdas/control-plane-common/cpcommon/actor.py

ASSURANCE_INTERACTIVE = "interactive"
ACCEPTED_ASSURANCE = frozenset({ASSURANCE_INTERACTIVE})

@dataclass(frozen=True)
class Actor:
    username: str                 # catalog-safe; matches config.CATALOG_IDENTIFIER_RE
    delegated_by: str | None      # None for every message this arc produces
    assurance: str                # a member of ACCEPTED_ASSURANCE, always

def trusted_actor(req: Any, *, exc: Callable[[str], Exception] | None = None) -> Actor: ...
```

The wire envelope every plane receives after step two — the plane-specific fields are unchanged and
omitted. The block is SPEC-200's, nested and unchanged in shape; what this spec removes is the field
*beside* it:

```jsonc
{
  "requestId": "…",                  // SPEC-167's per-submit mint, unchanged
  "identity": {
    "actor": "alice",                // the API's verified username. NOT a token.
    "delegated_by": null,            // reserved; non-null is refused today
    "assurance": "interactive"       // the only minted value; an unknown one is refused
  }
  // NO idToken field, and NO flat `actor`, on any plane.
}
```

Between step one and step two the same envelope also carries the plane's flat token field — `idToken` or
`actor` — which every consumer ignores. It is `identity` that is read, in both stretches.

The TypeScript half is generated from these types by SPEC-197's agreement mechanism; this spec adds no
hand-written TS shape and no second copy.

## API / Interface Contract

```python
# Every plane, in place of `auth.verified_username(req.get("idToken"))`
# or `auth.verified_username(req.get("actor"), missing_token_detail=…)`:

from cpcommon import actor as actor_mod

who = actor_mod.trusted_actor(req)                      # TerminalError("unauthorized", …)
who = actor_mod.trusted_actor(req, exc=AuthorizationError)  # shared-space, notifications-writer

# notifications-writer keeps its branch — the `create` arm is a trusted producer with no actor:
def _resolve_username(req):
    if req["action"] in USER_ACTIONS:                   # markRead, markAllRead
        return actor_mod.trusted_actor(req, exc=AuthorizationError).username
    username = req.get("username")                      # create: the seven execution roles' path
    ...
```

## Environment Variables

No new variable. Two are **removed** from eight modules' Lambda environments and from
`cpcommon.config._REQUIRED_VARS`:

```
COGNITO_USER_POOL_ID     # removed from the control planes; the API keeps its own OIDC_* set
COGNITO_APP_CLIENT_ID    # as above
```

## File & Folder Structure

```
lambdas/control-plane-common/cpcommon/
├── actor.py                    # NEW — the one reader
├── auth.py                     # survives; two entry points deleted; one caller left (the API)
├── config.py                   # two entries out of _REQUIRED_VARS
└── test_actor_cpcommon.py      # NEW

lambdas/
├── test_actor_fleet.py         # NEW — FR-002's derived enumeration + its guard-the-guard
├── shared-space-common/auth.py                 # verified_username deleted
├── notifications-writer/notifications_writer.py# verified_username deleted
├── control-plane-dlq-drain/dlq_drain.py        # Source.token_field deleted; recipient from identity.actor
├── {file-send,table-share,archive}-notify-failure/  # the three timeout doors
└── {shared-space-validate, table-builder-validate-authorize,
     data-quality-validate-authorize, table-share-validate-authorize,
     file-send-validate-authorize, archive-validate-authorize,
     file-ops-validate-authorize}/              # one call site each

lambdas/api/apicommon/                          # STEP TWO ONLY, and nothing else here
├── enqueue.py                                  # the token field stops being written
└── context.py                                  # Redacted and RequestContext.bearer deleted

infra/modules/
└── {shared-spaces,notifications,table-builder,table-share,data-quality,
    file-send,archive,file-ops}/lambda.tf       # COGNITO_* env removed
                               /variables.tf    # user_pool_id / app_client_id removed
```

**No `sqs.tf` and no `base/policies/`.** This spec adds no queue resource policy (SPEC-200 FR-008 AC5) and
therefore needs no deploy-role expansion — it introduces no AWS resource type. The two env removals are
edits to Lambda environments the deploy role already manages.

## Implementation Phases

### Phase 1: The reader and its semantics

- `cpcommon/actor.py`: `Actor`, `trusted_actor`, the assurance set, the `unsupported_assurance` reason
  registered in `cpcommon.messages`.
- FR-002's shape rules, including the JWT fixture, and FR-003's refusals in both directions.
- The import sweep proving the reader cannot verify.

### Phase 2: The fleet enumeration

- `test_actor_fleet.py`: the deploy-matrix × `parse_sqs_request` intersection, the per-module
  `identity`-less-message test, the no-AWS-call assertion, the `notifications_writer` exemption, and the
  guard-the-guard.
- Written **before** the call sites move, so it fails for the right reason first and its cardinality is a
  measurement rather than a restatement of what was built.

### Phase 3: The eight call sites

- One `trusted_actor` call per plane; `shared-space-common/auth.py` and `notifications_writer.py` lose their
  wrappers and pass `exc=` — `notifications_writer` keeping its `USER_ACTIONS` branch, with the `create`
  arm untouched.
- FR-004's authorization tests re-expressed, and the per-plane deliberate-violation run.
- The three timeout doors and the DLQ drain's recipient and redaction.

### Phase 4: The env removal, and the two `*_ignoring_expiry` entry points

- `COGNITO_*` out of eight modules and out of `_REQUIRED_VARS`, in the same change as the code removal.
- `cpcommon/auth.py`'s two `*_ignoring_expiry` entry points deleted; the superseded markers at SPEC-161's,
  SPEC-126's and SPEC-195's doc sites.
- No `sqs.tf` and no deploy-role change: there is no queue resource policy and no new resource type.

**Phases 1–4 and Phase 5's first four items are step one.** Step two is its own merge, after they are
deployed and run.

### Phase 5: Verification

Nothing offline settles this spec. A shared layer's import-time failure shows only at **cold start**
(PR #196), and SPEC-137 shipped instrumented code whose layer attachment was missing while `pytest`, the
deploy job and the instrumentation harness all went green — for nine days, on a Cognito trigger. This spec
*removes* an import and two required env vars from eight functions at once, which is the same class of
change pointed the other way: `conftest.py` puts every layer on `sys.path`, so a module that still reads a
deleted `config` attribute imports fine under test and raises on its first real invocation.

A new section of `docs/testing/arc-b-api-container-e2e.md`, in two passes because the spec deploys
twice. **Steps 1–5 run after step one's deploy, with the token still travelling; steps 6–7 run after step
two's.** Running the whole list once, after both, loses the only observation that distinguishes "the
planes read the block" from "the planes still read the token".

- **One real request per plane, all eight**, submitted through the API, reaching its normal terminal state
  and producing its normal notification. Eight cold starts — invoke each after a deploy, not after a warm
  neighbour, or the import is never exercised.
- **The load-bearing negative, per plane:** a request whose actor names a user who is *not* authorized
  (a non-member's space, a foreign prefix, an out-of-root key) is refused with the reason it is refused
  with today. Send it through the API as that unauthorized user, so the API writes a genuine verified
  `identity.actor` — a hand-crafted body cannot reach the queue any more, which is SPEC-200 FR-008 working.
- **Notifications' both branches, in one pass:** mark a notification read from the UI (the user path,
  refused if the block is missing) *and* confirm that the notification a control plane produced for the
  request above arrived at all. The second is the `create` branch, has no actor, and is what a
  `trusted_actor` hoisted above `_resolve_username`'s test silently kills — a run that only checks
  mark-read reports success over an inbox nothing can write to.
- **`assurance` refused live:** enqueue one message carrying `identity.assurance: "delegated"` and one
  carrying `identity.delegated_by: "svc-x"`, and confirm both are refused with `unsupported_assurance`
  while a neighbouring `interactive` message on the same queue succeeds. Without the neighbour the refusal
  proves only that the plane is broken. **The enqueue needs a principal holding the grant** — after
  SPEC-200 that is the API's execution role alone, so this goes through a temporary API route or an
  assumed session of that role, never a laptop identity.
- **The staged pre-cutover message** (FR-006) — a flat `actor` holding a JWT, no `identity` block: refused,
  no notification, and its logged body bounded and JWT-free.
- **The exposure closed** (after step two): dead-letter one message on each of the eight queues, then read
  the drain's CloudWatch log group and `logs/service=dlq-drain/` and confirm no JWT-shaped string in
  either, and that the user was notified with the recipient taken from `identity.actor`.
- **One request per plane again after step two**, because that deploy changes the body every plane
  receives and nothing offline sees both sides of it.
- **What nothing offline can prove, and nothing here proves either:** that a *future* provider's token
  yields the same username. This spec removes the claim reader from the planes, which is what makes that
  migration a configuration change — but the assertion belongs to the arc that performs it.

### Phase 6: Completion ritual

- `Status: Completed`; the `INDEX.md` row; the delivery doc, carrying the measured enumeration cardinality,
  the per-plane deliberate-violation counts, the queue-depth figures from FR-006, the two deploy
  timestamps, and which side of the rollback line each landed on.
- **`decisions/` entries**, then one line each in CLAUDE.md's Key Decisions:
  1. *The planes trust a field because of who may write it* — the verification/authorization split stated
     in those words, with SPEC-200 FR-008's identity grant and its enumerated `.tftpl` sweep as the
     provenance. **This entry does not re-open the resource-policy question**: SPEC-200 owns that decision
     for the arc, and this one cites it and records why a `Deny` on the notifications queue would have
     silenced seven notifying execution roles.
  2. *`assurance` fails closed on an unknown value* — including the reserved-but-unminted `delegated`, and
     why refusing today is the point rather than an inconvenience.
  3. *The five-reader collapse* — what it cost, what it did not reach (the SPA, `identity-pool.tf`,
     `notifications_writer`'s `create` branch, which never had a token to read), and
     the correction that `notifications_writer` had already lost its independent verification path in
     SPEC-156.
  4. *The trust flip is two deploys, not one* — the planes require the block before the API stops sending
     the token, because a single merge fails all eight closed while both suites pass.
- **Superseded markers, in place, at every site still stating the old claim:** SPEC-195's Premise 3
  (`verify_id_token_ignoring_expiry` is for the DLQ drain — it is for nothing now); SPEC-126's decisions
  entry on the verified-`cognito:username` recipient and the expiry relaxation; SPEC-161's timeout-door
  entry ("by construction that token is expired"); SPEC-164's flat-`actor` reasoning, which is not wrong
  but is no longer about a token; `transition_plan.md` §6.1's count and its
  `notifications_writer`-has-its-own-path sentence; `ARCS.md`'s "the BFF derives `actor` once"; and
  SPEC-197 Premise 6, whose narrowing SPEC-200 added for `apicommon/enqueue.py`'s single `reveal()` — with
  both gone, the premise returns to its original form and the marker is removed rather than re-worded.
- **Component inventory:** no row. `cpcommon.actor` is a Lambda layer module, and the inventory covers
  `apps/portal/`; the layer's own documentation is its docstring plus `lambdas/info/shared-layer.md`, which gains an
  entry for why the reader may not verify.
- **Help sweep: nothing user-facing changed.** No component, copy, label or flow is touched, and the only
  new user-visible string is `unsupported_assurance`'s sentence, which no legitimate request can reach.
  Recorded explicitly and skipped, rather than left ambiguous.
