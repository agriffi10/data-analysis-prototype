# Spec: Membership Tags from the Registry — the Interim Plane's Missing Half

**ID:** SPEC-203
**Status:** Draft
**Last Updated:** 2026-08-18
**Depends On:** SPEC-196 (the AWS identity layer — the tag set, the trust policy, the per-container credential cache keyed on the whole tag set, and the claim-sourced implementation this spec makes one of two), SPEC-195 (the verified bearer and `Principal.username`), SPEC-197 (the transport contract — route ids, the envelope, the declared-per-route retry rule), SPEC-011 (the identity is a verified claim, never a caller assertion), SPEC-051/053/056/073/075 (the shared-space registry, the membership slots, the propagation contract and the roster), SPEC-113 (no existence oracle), SPEC-123 (an admin-bucket index under ETag CAS — the precedent this spec deliberately does **not** follow, FR-003), SPEC-106 (`toUserMessage`), SPEC-127→137/186 (`cpcommon.observability`, the field rule, `env`/`version`)

## Overview

SPEC-196 builds a user's AWS session tags from the claims of their verified ID token: `username` from
`cognito:username`, and ten `shared_space_k` tags from ten `custom:shared_space_k` Cognito custom
attributes. That is correct, and it is what makes SPEC-196's central claim provable — the API stamps
byte-identically what the Identity Pool stamps, so not one IAM policy is rewritten.

In the successor account those claims do not exist. Under the transition's baseline variant there is
no Cognito at all, and under the fallback the bridge pool ships with no custom attribute schema by
decision (`transition_plan.md` §2 item 1, §3.3). The membership tags have to come from somewhere
else, and the only authoritative somewhere is the **shared-space registry** — which is already the
source of truth and already the authorization input everywhere that matters.

`transition_plan.md` Phase 1 depends on this and no spec owned it. This spec is that half.

**It ships now, against Cognito, and that is the point.** The registry source could be written during
the transition, but it could not be *proved* there: with no claims to compare against, a wrong
implementation would be indistinguishable from a right one, and the failure mode is a session that
silently carries the wrong spaces. Built here, both sources exist at once and the acceptance
criterion is that **they agree for a real user** — a stronger proof than either source alone can
offer, and one that expires the moment the environment moves. This repo's most expensive outage was
instrumented code whose layer attachment was missing while every gate was blind to it (SPEC-137).

## Scope

### In Scope

- **The membership source as a declared choice** — `claims` (today, the default) or `registry` —
  resolved once from configuration, with an unknown value refused at cold start (FR-001).
- **The registry source, scoped to the spaces the request names** (FR-002) — the spec's central
  decision, and the reason it needs no new durable artifact.
- **Why the connections cache is not the source**, asserted rather than assumed (FR-003).
- **The authorization rule** — `is_active_member` against the registry record, never the roster and
  never the join chip (FR-004).
- **Failure semantics: the request fails; it never mints a smaller tag set** (FR-005).
- **The parity assertion**, offline and live, while both sources exist (FR-006).
- **The API-plane grant** the registry read needs, and its scope (FR-007).
- **What the slot cap means once slots are gone** (FR-008).
- **Observability** through `cpcommon.observability`, under the field rule (FR-009).
- **What does not change** — the default source, `useSharedSpaceAccessRecovery`, every IAM policy
  (FR-010).

### Out of Scope

- **Changing the default.** `claims` stays the default through this spec and every spec in Arc B.
  Flipping it is a transition Phase 1 configuration change, made in the successor account against a
  provider that has no such claims. Nothing here ships a behaviour change to the current product.
- **The personal `username` tag.** It comes from the verified claim in both sources and is untouched
  — the username claim's *name* is already configuration (SPEC-195 FR-002).
- **Retiring the Cognito membership slots**, `assign_or_find_slot`, `clear_slot`, the
  `custom:shared_space_*` attribute schema or `var.max_shared_memberships`. They stay live and
  authoritative for the `claims` source, which stays the default. The successor account's Phase 1 is
  where they stop being written; `transition_plan.md` §9 lists them.
- **Per-user Lake Formation and S3 Access Grants entitlements.** That is what replaces tags
  altogether at transition Phase 5 — **SPEC-204**, a different mechanism with a different lifetime.
  This spec keeps the tags and changes only where their values come from.
- **A per-user membership index.** Considered and rejected — FR-003.
- **Any browser change.** No service signature moves, no hook changes, and the SPA cannot tell which
  source is configured.

### What SPEC-196 builds, what this adds, and what stays identical

| | `claims` (SPEC-196, default) | `registry` (this spec) |
|---|---|---|
| `username` tag | Verified claim | **Verified claim — identical** |
| `shared_space_k` values | Ten `custom:shared_space_k` claims | The spaces **this request names**, each verified against its registry record |
| Slots stamped | Every slot the token carries | Only what the request needs — commonly zero or one |
| Authorization for a space | The claim's presence | `registry.is_active_member(record, username)` |
| Propagation delay | SPEC-056's — a token refresh | **None** — the registry is read per mint |
| Cost per credential mint | Zero extra calls | One `GetObject` per **named** space, cached with the credentials |
| Policies, tag names, tag values | — | **Byte-identical.** FR-010 asserts it |

### Premises later specs must honour

1. **The registry record is the authorization input; the roster and the cache are projections.**
   `is_active_member` requires `status == "active"` on the space *and* the user in `members`. A space
   still provisioning, failed or deleting is not a member's to reach — SPEC-073's rule, unchanged.
2. **The tag set is the credential cache key** (SPEC-196 FR-006), and this spec makes that key vary
   per request rather than per user. That is a property of FR-006 as already written; a later spec
   that "optimises" the key back to the username alone breaks this one silently.
3. **A space name reaching this layer has been through `CATALOG_IDENTIFIER_RE`** before it is used to
   build a key. The registry key is `shared-spaces/{name}.json` and the name arrives from the
   request.
4. **No component may read a user-writable object to decide what a session may do.** FR-003 states
   the instance; the rule is general and outlives this spec.

---

## Functional Requirements

### FR-001: The membership source is a declared choice, resolved once

#### Description:

Two implementations, one selected at cold start from configuration. Not a per-request choice, not a
fallback chain, and not a silent default when the value is unrecognised — a misconfigured source that
degrades to the other one produces a working application with the wrong authorization model.

#### Acceptance Criteria:

- [ ] `MEMBERSHIP_TAG_SOURCE` takes exactly `claims` or `registry`. It is read **once**, at module
      import, and resolved to one implementation.
- [ ] **An unset value resolves to `claims`.** Absent configuration is the current environment, and
      every deployed environment today omits the variable.
- [ ] **An unrecognised value raises at import**, failing the container's cold start. It does not
      warn, it does not fall back, and it is not deferred to first use. A typo (`Registry`,
      `registery`) must be a dead container, not a running one on the default — the two sources
      disagree about *what a user may reach*, and the wrong one is invisible in every response.
- [ ] The selection is recorded once per container on the identity layer's own span, under a field
      name that is not a secret (FR-009).
- [ ] A test asserts both implementations satisfy the same interface, taking the verified principal
      and the request's named spaces and returning an ordered tag list — so a call site cannot tell
      them apart, and neither can FR-006's parity test.

### FR-002: The registry source is scoped to the spaces the REQUEST names

#### Description:

This is the spec's central decision, and it is not what `transition_plan.md` implied.

The obvious reading of "compute the tags from the registry" is *enumerate every space this user
belongs to, and stamp them all*. **The registry cannot answer that question cheaply.** It is one
object per space, keyed by space name, in the admin bucket — there is no per-user index, so
enumerating a user's memberships means listing `shared-spaces/` and reading **every** object, on the
credential-minting path, on every request. That cost grows with the number of spaces in the
organization, not with anything about the caller.

So invert it. **A request already names the spaces it touches** — the API's routes take `space` as a
parameter (SPEC-198, SPEC-199) — and a session needs no tag for a space the request does not touch.
Read the registry record for each named space, verify membership, and stamp exactly those.

Three things fall out, and all three are improvements:

- **The cost is bounded by the request**, not by the organization. Commonly one `GetObject`; often
  zero.
- **The session is least-privilege per request.** A session that reaches one space carries one
  space's tag, where the claims source carries all ten on every call.
- **The ten-slot ceiling stops binding on the number of spaces a user belongs to** and starts
  binding on the number a single request names — which is one, everywhere in the product today.
  FR-008 states what that does and does not mean.

#### Acceptance Criteria:

- [ ] The router resolves the request's **named spaces** — zero or more — before the credential mint,
      and passes them to the identity layer. The set is derived from the route's declared parameters,
      never by scanning the body for anything space-shaped.
- [ ] For each named space, the source reads `shared-spaces/{name}.json` from the admin bucket and
      stamps a `shared_space_k` tag **only if** `registry.is_active_member(record, username)` returns
      true (FR-004).
- [ ] **A named space the caller is not an active member of contributes no tag, and is not an
      error.** The session is minted without it and the downstream AWS call fails on IAM — which is
      the same shape as today's unstamped slot, and is what keeps SPEC-113 intact: the route must not
      learn from the identity layer whether a space it was refused actually exists.
- [ ] **A request naming zero spaces mints a session with the `username` tag alone.** Asserted,
      because "no tags at all" and "username only" are one keystroke apart and the second is correct.
- [ ] Slot indices are assigned **deterministically from the sorted named-space list**, starting at
      1. A test asserts that two requests naming the same spaces in different orders produce the same
      ordered tag list — which is what makes SPEC-196 FR-006's cache key stable rather than
      order-sensitive.
- [ ] **The slot index carries no meaning and a test says so**: the shared-space policy templates one
      identical statement pair per slot, so the union a session receives is independent of which
      slots were used. Assert by minting the same space into slot 1 and slot 3 and comparing the
      resolved resource sets.
- [ ] **SPEC-196 FR-006's credential cache needs no change, and one of its criteria changes meaning.**
      The key is already the whole tag set, so a key that varies per request is that FR working as
      written — assert it with two requests from one user naming *different* spaces and a second
      `AssumeRole`. Its fourth criterion (a refreshed token whose `custom:shared_space_k` claim
      differs issues a third assume) is **claims-specific**: under this source membership changes take
      effect on the next request with no refresh at all, which is the propagation delay disappearing.
      Assert the equivalent — a registry record edited between two requests changes the tag set — and
      state that the two criteria test the same property through different mechanisms.
- [ ] **This does not violate SPEC-196 Premise 3, and the test proves the distinction.** That premise
      forbids a parameter that *chooses an identity*; a named space *scopes* the identity the token
      established. The proof is the one from SPEC-196 FR-002, re-run against this source: a request
      whose body, query and headers all say `mallory` while the verified token says `alice`, naming a
      space `mallory` belongs to and `alice` does not, mints **no** `shared_space` tag. The fixture
      must disagree; one where they agree passes over the defect.

### FR-003: The registry is the only source, and the connections cache is not

#### Description:

There is an object that already lists a user's spaces, one `GetObject` away, keyed by username:
`{username}/user_settings/shared-connections.json` (SPEC-075's roster fan-out). It is exactly the
shape FR-002 says the registry lacks, and reaching for it would be the natural implementation.

**It lives in the user's own S3 prefix, and the user can write it.** The portal role grants
`PutObject` under `${aws:PrincipalTag/username}/`, which is what lets the app write user settings at
all. A user who edits that file to name a space they do not belong to would be handed a session tag
granting them that space. It is a complete authorization bypass through a file the product invites
the user to own.

A per-user **index in the admin bucket** would be safe — SPEC-123's runs index and SPEC-146's
username directory are both precedents, both under ETag CAS, both user-unreachable. It is rejected
anyway: it is a new durable artifact written by five verbs, with its own drift, rebuild and
CAS-contention story, to answer a question FR-002 no longer asks.

#### Acceptance Criteria:

- [ ] The identity layer reads **only** `shared-spaces/{name}.json` from the admin bucket. A test
      asserts its modules name neither the connections-cache key nor `user_settings`.
- [ ] A **repo sweep** fails if any module under `lambdas/api/` reads an object under the user-space
      bucket to make an authorization decision. Written as a sweep and not a review note, because the
      cache is the obvious answer and will be proposed again.
- [ ] The rejection of a per-user index is recorded in `decisions.md` with FR-002's reasoning, so it
      is not re-proposed as an optimisation.
- [ ] A test drives the bypass directly: a connections cache naming `finance-space`, a registry
      record that does not list the caller, and an assertion that **no** tag is stamped. It fails
      loudly against an implementation that read the cache.

### FR-004: Membership is `is_active_member`, and nothing else

#### Description:

The rule already exists and is already reused by four planes (`table-share-validate-authorize`,
`table-builder-validate-authorize`, `fscommon.authz`, `arcommon.authz`). This spec is the fifth
caller and must not restate it.

#### Acceptance Criteria:

- [ ] Membership is decided by `cpcommon.registry.is_active_member(record, username)` — the existing
      function, imported, not reimplemented.
- [ ] A space whose `status` is not `active` yields **no** tag, whatever the member list says. A test
      drives `provisioning`, `failed` and `deleting` and asserts no tag for each. This is SPEC-073's
      reversal risk: the join chip is display-only and access is granted at add time, so a spec that
      reached for `acknowledged` here would deny active members and grant nothing extra.
- [ ] A missing registry object yields no tag and is **not** distinguished from a non-membership on
      the wire (SPEC-113).
- [ ] A malformed registry object is a **failure** (FR-005), not an absence. An unparseable record is
      not evidence that the caller is not a member.

### FR-005: The request fails; it never mints a smaller tag set

#### Description:

The tempting failure mode is to swallow a registry read error and mint whatever tags were resolved.
It fails *closed* in the permissions sense, which reads as safe — and it is the worst option
available. A session missing a tag produces `AccessDenied` on a space the user is genuinely a member
of, which is indistinguishable from a real refusal, arrives as a permissions message the user cannot
act on, and is invisible to every gate. SPEC-196's second half exists because a wrong credential
*succeeds*; this is the same defect with the sign flipped.

#### Acceptance Criteria:

- [ ] Any error resolving a named space other than "absent" or "not a member" — a throttle, a
      timeout, a 5xx, a parse failure, a denied read — **fails the request**. No credential is
      minted and no partial tag set is used.
- [ ] The failure maps to SPEC-196 FR-007's `IdentityUnavailable` condition and its status, and to a
      SPEC-106 code. It is **not** mapped to a permission denial, which is what a user would be told
      by a partial mint.
- [ ] Nothing is cached on this path. A failed resolution must not populate SPEC-196's credential
      cache under any key — asserted, because a cached partial tag set outlives the fault that
      caused it.
- [ ] Retry is the caller's, under SPEC-197's declared-per-route policy. This layer retries nothing:
      it sits inside the request and a retry here multiplies the latency of a fault it cannot fix.
- [ ] A test drives a registry `GetObject` raising a throttle and asserts (1) no `AssumeRole` was
      issued, (2) the response is the identity-unavailable shape, (3) the cache is empty afterwards.

### FR-006: The two sources agree — the assertion that expires

#### Description:

The reason this spec ships now. While Cognito slots and the registry both exist, the same user's
membership is knowable two ways, and they must agree. In the successor account only one way survives,
and this assertion becomes unwritable.

#### Acceptance Criteria:

- [ ] An offline test resolves the tag set for a fixture user under **both** sources and asserts the
      resulting tag **sets are equal**, compared order-independently — because FR-002 orders by
      sorted space name and the claims source orders by slot index, and they will differ in order for
      the same correct answer.
- [ ] The comparison is over the spaces the request names, since that is the only overlap the two
      sources have. A claims-source tag for a space the request does not name is **expected** and is
      excluded from the comparison rather than treated as a disagreement — stated explicitly, because
      a naive set-equality test fails permanently on a correct implementation.
- [ ] The fixture includes a user in **more than one** space, at least one space that is **not**
      `active`, and one space the user was removed from whose Cognito slot has been cleared. A
      single-space fixture agrees under almost any implementation.
- [ ] **A live check, and it is the deliverable a later session will care about most.** Against the
      deployed API with `MEMBERSHIP_TAG_SOURCE=registry` in a non-production environment: a real user
      in at least two spaces reaches each one, is refused a space they are not in, and the `logs/`
      record for each mint names the resolved space count. Written as a runnable script under
      `docs/testing/`, with the fixture, the exact labels and the expected numbers.
- [ ] The live check states, in the script, that it **cannot be re-run after the environment moves**,
      and that a later reader should treat it as evidence rather than as a repeatable gate.

### FR-007: The registry read is an API-plane call, and its grant is narrow

#### Description:

The tags are computed **before** the user's credentials exist, so the read is made with the API
Lambda's own execution role — SPEC-196's API plane. That is a privilege the API holds unconditionally
on behalf of every caller, so its scope is the whole of its safety.

#### Acceptance Criteria:

- [ ] The read is declared `Plane.API` at its call site under SPEC-196 FR-005's registry, and is
      covered by that FR's sweep.
- [ ] The grant is `s3:GetObject` on `arn:{admin-bucket}/shared-spaces/*` and **nothing else** — no
      `ListBucket`, no other prefix of the admin bucket, no write. A test reads the rendered policy
      back and asserts the action and resource set exactly.
- [ ] **No `ListBucket` is the load-bearing half.** FR-002 needs no listing, and a `ListBucket` grant
      here would make the admin bucket enumerable by the one role every request runs through.
- [ ] A deployed-role IAM simulation covers it, on SPEC-186's discipline: each denial paired with an
      `allowed` control, because an `implicitDeny` alone cannot distinguish an ungranted action from
      a wrong ARN.
- [ ] The deploy role's own policy is **verified as already sufficient** rather than assumed — no new
      resource type is created by this spec.

### FR-008: The slot cap, and what it now bounds

#### Description:

`transition_plan.md` §6.4 records that the ten-slot ceiling lives in
`infra/modules/shared-spaces/policies/portal-role-shared-space.json.tftpl`, which loops over
`max_shared_memberships` and emits `${aws:PrincipalTag/shared_space_${k}}` into the S3 resources, the
`ListBucket` prefix condition and the Glue ARNs. An eleventh tag matches no resource whatever wrote
it. FR-002 does not remove that; it changes what it bounds.

#### Acceptance Criteria:

- [ ] The registry source stamps at most `MAX_SHARED_MEMBERSHIPS` tags, read from the same Tofu
      variable that sizes the policy templates (SPEC-196 FR-002's rule, unchanged).
- [ ] **A request naming more spaces than there are slots is a failure, not a truncation** — FR-005's
      shape and reasoning: silently dropping a named space produces an `AccessDenied` on a space the
      user is a member of and named explicitly.
- [ ] The cap is documented as bounding **spaces named by one request**, not spaces a user belongs
      to, with the observation that every route in the product today names exactly one. A test
      asserts no route's declared parameters can name more than one space, so the failure above is
      currently unreachable — and would become reachable the day a cross-space route is added, which
      is the point of asserting it.
- [ ] **This spec does not raise `max_shared_memberships`.** Under the `claims` source the old
      ceiling still binds on a user's total memberships, and raising it means re-rendering the policy
      — out of scope here, and named in `transition_plan.md` §8 as a transition Phase 0 question.

### FR-009: Observability

#### Description:

One span per credential mint, through `cpcommon.observability` — the only door (SPEC-127→137) — under
the field rule.

#### Acceptance Criteria:

- [ ] The span carries the configured source, the count of named spaces, the count of tags stamped,
      and the resolved space **names**. Space names are user metadata and are permitted by the field
      rule; the token, its claims and any registry body are not.
- [ ] **`stamped < named` is recorded at `warn` with a stable reason token.** It is the signal that a
      user is being refused a space they asked for, and it is otherwise invisible — the request
      succeeds and the denial happens later, in IAM, in a different service.
- [ ] `env` and `version` are populated on every record (SPEC-186 FR-005).
- [ ] Messages are literals; `echo=` is prohibited repo-wide.
- [ ] The `error.stack` treatment is SPEC-195 FR-007's scrub, inherited — this layer handles a
      registry body and must not put one in a stack.

### FR-010: What does not change

#### Description:

Stated as requirements because each is a thing a careless implementation would take with it.

#### Acceptance Criteria:

- [ ] **The default is `claims`**, and every deployed environment omits `MEMBERSHIP_TAG_SOURCE`. A
      test asserts the resolved default. No user in the current environment can observe this spec.
- [ ] **Not one IAM policy, bucket policy or Lake Formation grant is edited.** SPEC-196 FR-008's
      no-change guard is re-run and must stay green — the tag *names* and *values* are identical
      across sources, which is the entire reason a source swap is possible at all.
- [ ] **`useSharedSpaceAccessRecovery` stays.** Under `claims` it papers over SPEC-056's propagation
      delay, which is unchanged. Under `registry` the delay is gone and the affordance is inert but
      harmless; removing it is a browser change in a spec that has none, and it would have to be
      restored if the source were ever flipped back.
- [ ] **The Cognito slot machinery stays live** — `assign_or_find_slot`, `clear_slot`, the attribute
      schema. Under `claims` they are authoritative; a spec that removed them here would break the
      default source.
- [ ] No `*.service.ts`, hook or component changes. The SPA cannot determine the configured source
      from any response.

---

## Data Model

No new persisted shape. The registry record is read as it exists today:

```
s3://{admin-bucket}/shared-spaces/{name}.json
  { version, name, owner, members[], status, createdAt, lastRequestId, ... }
```

The resolved value handed to `sts:AssumeRole` is SPEC-196's existing `Tags` list, unchanged in shape:

```
[ {Key: "username",       Value: "<verified claim>"},
  {Key: "shared_space_1", Value: "<sorted named space 1>"},
  ... ]
```

## Environment Variables

| Name | Values | Default | Notes |
|---|---|---|---|
| `MEMBERSHIP_TAG_SOURCE` | `claims` \| `registry` | `claims` | Unrecognised value raises at import (FR-001) |

`ADMIN_BUCKET` and `MAX_SHARED_MEMBERSHIPS` are already delivered to the API Lambda and are reused.

## File & Folder Structure

Inside `lambdas/api/`, beside SPEC-196's identity layer — one module holding both sources behind the
common interface, and its tests. No new layer, no new package, and nothing in `lambdas/api/` outside
the identity layer learns that a source exists.

## Implementation Phases

### Phase 1: The interface and the claims source behind it

Extract SPEC-196's claim reading behind the interface of FR-001, with no behaviour change. The
existing SPEC-196 tests must pass untouched — if any needs editing, the extraction changed behaviour.

### Phase 2: The registry source

FR-002, FR-003, FR-004, FR-005 and FR-008, with the bypass test (FR-003) and the disagreeing-fixture
test (FR-002) written **before** the implementation.

### Phase 3: The grant, the config and the observability

FR-001's cold-start refusal, FR-007's grant and its deployed-role simulation, FR-009's span.

### Phase 4: Parity

FR-006's offline test, then the live check script under `docs/testing/`.

### Phase 5: Verification

Formatter, linter, `ruff`, the blocking `mypy` over the shared layers, `pytest lambdas/`, the portal
suite and `npm run build`. Then the FR-006 live check in a non-production environment with
`MEMBERSHIP_TAG_SOURCE=registry`, and the deployed-role IAM simulation for FR-007.

### Phase 6: Completion ritual

Per `CLAUDE.md`. The `decisions.md` entry is FR-003's rejection of the per-user index together with
FR-002's per-request scoping — one entry, because the second is why the first was possible.
