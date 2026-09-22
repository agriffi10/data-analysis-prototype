# Identity, access and the name that ties them together

Part of the **Key Decisions register** — [`INDEX.md`](INDEX.md) is the router, and `CLAUDE.md`
carries a table pointing at each area's Fences. This file opens with those fences — the traps that
apply green and fail later — and holds the reasoning, the constraints and the explicit "do NOT
build" fences for one area beneath them. **Read the Fences before working in the area, then the
entry you need, not the file.**

## Contents

- [Fences](#fences)
- [Auth](#auth)
- [Hosted UI = Managed Login v2](#hosted-ui--managed-login-v2)
- [No backend](#no-backend)
- [Usernames](#usernames)
- [Bucket 2 (shared-space)](#bucket-2-shared-space)
- [Member join status (SPEC-073)](#member-join-status-spec-073)
- [Member roster for members (SPEC-075)](#member-roster-for-members-spec-075)
- [Dev-unauth path](#dev-unauth-path)
- [The username directory is built from S3, not Cognito (SPEC-146)](#the-username-directory-is-built-from-s3-not-cognito-spec-146)
- [Every authenticated user can read the username directory (SPEC-146)](#every-authenticated-user-can-read-the-username-directory-spec-146)
- [No shared-space directory is published; suggestions come from your own cache (SPEC-158)](#no-shared-space-directory-is-published-suggestions-come-from-your-own-cache-spec-158)
- [A feature flag is presentation, never authorization — and it lives beside the username directory (SPEC-162)](#a-feature-flag-is-presentation-never-authorization--and-it-lives-beside-the-username-directory-spec-162)
- [Gating is by REGISTRY, not per-component opt-in (SPEC-163)](#gating-is-by-registry-not-per-component-opt-in-spec-163)
- [The roster contradicted the connections list because a fan-out list was missing one verb](#the-roster-contradicted-the-connections-list-because-a-fan-out-list-was-missing-one-verb)
- [A verification principal is read-only, or it is a back door](#a-verification-principal-is-read-only-or-it-is-a-back-door)
- [The identity block is nested, and it stays nested (SPEC-200)](#the-identity-block-is-nested-and-it-stays-nested-spec-200)
- [The browser's queue grants come off with the switchover, not with the trust flip (SPEC-200)](#the-browsers-queue-grants-come-off-with-the-switchover-not-with-the-trust-flip-spec-200)
- [Table-share's dedup id is keyed on the verified actor, not the token (SPEC-200)](#table-shares-dedup-id-is-keyed-on-the-verified-actor-not-the-token-spec-200)
- [The identity grant is the only path to a request queue; no resource policy (SPEC-200)](#the-identity-grant-is-the-only-path-to-a-request-queue-no-resource-policy-spec-200)
- [The planes trust a body field because of who may WRITE it, not because of cryptography (SPEC-201)](#the-planes-trust-a-body-field-because-of-who-may-write-it-not-because-of-cryptography-spec-201)
- [`assurance` fails closed on an unknown value, including an absent one (SPEC-201)](#assurance-fails-closed-on-an-unknown-value-including-an-absent-one-spec-201)
- [Collapsing five claim readers cost four things the spec did not list (SPEC-201)](#collapsing-five-claim-readers-cost-four-things-the-spec-did-not-list-spec-201)
- [The trust flip is two deploys, and the second cannot be rolled back (SPEC-201)](#the-trust-flip-is-two-deploys-and-the-second-cannot-be-rolled-back-spec-201)
- [The provider block is the API's verifier configuration, and it is server-side (SPEC-192)](#the-provider-block-is-the-apis-verifier-configuration-and-it-is-server-side-spec-192)
- [Authorization lives in the router, not in an API Gateway authorizer (SPEC-193)](#authorization-lives-in-the-router-not-in-an-api-gateway-authorizer-spec-193)
- [The API is a verifier, not an OIDC client (SPEC-195)](#the-api-is-a-verifier-not-an-oidc-client-spec-195)
- [The API reads the same claims and assumes the same role with the same tag set (SPEC-196)](#the-api-reads-the-same-claims-and-assumes-the-same-role-with-the-same-tag-set-spec-196)
- [Two credential planes, declared per route, defaulting to the user plane (SPEC-196)](#two-credential-planes-declared-per-route-defaulting-to-the-user-plane-spec-196)
- [The credential cache is keyed on the whole tag set (SPEC-196)](#the-credential-cache-is-keyed-on-the-whole-tag-set-spec-196)
- [The error shape: a machine code, and operator text nobody renders (SPEC-197)](#the-error-shape-a-machine-code-and-operator-text-nobody-renders-spec-197)
- [The contract is declared in Python and the TypeScript is generated (SPEC-197)](#the-contract-is-declared-in-python-and-the-typescript-is-generated-spec-197)
- [`apiRequest` retries nothing, and idempotency is declared per route (SPEC-197)](#apirequest-retries-nothing-and-idempotency-is-declared-per-route-spec-197)
- [Cognito tokens are held per TAB, not per browser (2026-08-27)](#cognito-tokens-are-held-per-tab-not-per-browser-2026-08-27)
- [A presigned URL is a bearer token (SPEC-198)](#a-presigned-url-is-a-bearer-token-spec-198)
- [The dev-unauth path is retired (SPEC-198, supersedes SPEC-002)](#the-dev-unauth-path-is-retired-spec-198-supersedes-spec-002)
- [The API makes exactly ONE AWS call per request, and every loop stays in the browser (SPEC-199)](#the-api-makes-exactly-one-aws-call-per-request-and-every-loop-stays-in-the-browser-spec-199)
- [A route may carry PATH parameters, and a value that is not one segment is refused in the browser (SPEC-199)](#a-route-may-carry-path-parameters-and-a-value-that-is-not-one-segment-is-refused-in-the-browser-spec-199)
- [The membership index is an authorization input, where the username directory is not (SPEC-203)](#the-membership-index-is-an-authorization-input-where-the-username-directory-is-not-spec-203)
- [The role's Lake Formation grants and the principal tag are ONE mechanism (2026-09-01)](#the-roles-lake-formation-grants-and-the-principal-tag-are-one-mechanism-2026-09-01)
- [The Identity Pool is retired, and no one's sign-in changed (SPEC-202)](#the-identity-pool-is-retired-and-no-ones-sign-in-changed-spec-202)
- [An execution id is a claim, and every route that names one proves it first (SPEC-232)](#an-execution-id-is-a-claim-and-every-route-that-names-one-proves-it-first-spec-232)

## Fences

Cognito **User Pool**, ABAC — the Identity Pool is RETIRED (SPEC-202) and the API is the only thing
that turns a token into credentials; retiring it changed **nobody's sign-in**, which is the
conflation to head off. The `username` principal tag is stamped **server-side from
the verified claim**, so it cannot be spoofed; one shared role, isolation by
`${aws:PrincipalTag/username}`; a SHARED space adds a per-space role-level LF grant, retired
**with** the tag scoping or not at all. Hosted UI is **Managed Login v2** — the classic one broke the
post-signup redirect. The API verifies the browser's bearer and assumes that same role for it.

- **The API VERIFIES a bearer, and is not an OIDC client.** No cookie → no CSRF surface; CORS still
  required. **A key-retrieval fault is 5xx, never 401**; refusals are byte-identical and **expiry is
  not disclosed**, because the browser refreshes once on any 401.
- **It assumes the SAME role with the SAME tags from the SAME claims** — one computation over one
  input, which is why no policy is rewritten. The role is **reused, never minted**
  (`aws:PrincipalArn` resolves to the *role's* ARN, so the hand-maintained bucket-policy allowlist
  stays correct), `DurationSeconds` 3600 is a ceiling **both ways** — shorter caps every presigned
  link, longer is refused as role chaining — and tag-key agreement is
  **asserted, not structural** — the trust statement's `sts:TagKeys` is a ceiling that **cannot
  require a tag was stamped**.
- **Two credential planes, user by default, declared ON THE ROUTE — the failure fails OPEN.** A wrong
  client *succeeds* against the wrong identity. The plane is a **required field** on the contract's
  `Route`, a value that is neither of the two **raises**, and the route is set on the way **IN**: a
  warm container has no fresh context, so cleanup-on-exit alone lets the next request inherit a
  declaration. **An assume failure is a FAULT, never a denial** — STS says `AccessDenied` for a wrong
  trust policy, so the layer *wraps* it.
- **The credential cache is keyed on the WHOLE tag set** — never the username alone, which freezes
  membership until the next cold start, and never nothing, which serves B the session of A. **A
  presigned URL is not a request** and takes `signing_client(covering=…)`, forcing a fresh session
  rather than clamping against a near-dead one. A short window is *correctly clamped*, so no clamp
  test can see it.
- **The API's remaining fences live beside it** — `@lambdas/info/planes/api.md` for the plane, the
  entries below for the rest — and they are traps rather than reference: **no route waits, sleeps or
  paginates** and no call count grows with the user's data (a small fixed number is fine); the error shape is a
  machine **CODE** whose wording is chosen client-side; the wire is declared in **Python** and the
  TypeScript is **generated** from a **closed** vocabulary
  that never falls back; **`$default` matches OPTIONS**, so the router answers a preflight **before
  authentication** and only a browser can see that fail; and **no route waits**, every poll and page
  walk staying in the browser against a **non-raisable** 30-second integration ceiling.
- **Browser-side, `apiRequest` retries NOTHING**, with one exception: a 401 takes one forced refresh
  and one retry — the browser's only refresh path, so deleting it signs everyone out at the hour mark
  with a green suite. Idempotency is declared **per route**, never derived from the method, and a
  path parameter that is not **one segment** is **refused in the browser** — either spelling would
  otherwise reach a **sibling route answering 200 with the wrong shape**.
- **An execution id is a CLAIM, not an authorization.** Athena authorizes by workgroup and there
  is one, so every route that names an execution proves it is the caller's **first** (its recorded
  output location under the caller's own `user_results_prefix`) before it answers or acts. Results
  is included, because S3 guards the rows but not the state. An unknown id and a foreign one get
  **one 404 body**, and the span says which. A route that skips the proof passes every test that
  drives only the caller's own execution, which is why the guard is derived from the contract.
  **A workgroup that enforces its own result location makes every one of them 404** for every
  user's own queries, so the proof moves with the location.
- **The tag VALUES have two sources, chosen at COLD START, no fallback** — `MEMBERSHIP_SOURCE`,
  default `claims`, in no Terraform. The other is `memberships/{username}.json`, **admin** bucket:
  an authorization input, unlike the username directory, safe only because it is
  **user-unreachable, plane-written, CAS-written**. The user's own `shared-connections.json` is the
  same shape and **user-writable** — reading it is a bypass. Absence needs a
  **`s3:prefix`-conditioned `ListBucket`** or it reads as denial.

**One string is four things:** username = S3 prefix = principal tag = Glue database name, so it is
catalog-safe by construction (`^[a-z][a-z0-9_]{2,62}$`) — pre-signup applies the rule, which is what
"by construction" rests on. **A shared space's NAME is the same four things and one more**, the
table-build and table-share `MessageGroupId`, and it was catalog-safe by nothing until the create
path took the rule: the browser's create dialog held it and no server path did, so a space could be
created that can never build a table
([control-planes](control-planes.md#a-spaces-name-is-held-to-the-catalog-rule-where-it-is-chosen-and-the-refusal-is-create-only-2026-09-22)).
The username directory is built from **S3,
not Cognito** — today Cognito is complete and S3 is not, and the client transition reverses exactly
that. It is readable by every authenticated user, accepted deliberately: usernames only, never
emails.

- **A feature flag is presentation, never authorization** — and the flag document lives beside the
  username directory in the **user-space** bucket, not the admin one: the admin bucket was specced
  first, and its grant would not have worked. Gating is by **registry**, not
  per-component opt-in, and one test walks every gated surface in **both** states.
- **No shared-space directory is published** — the share dialog suggests only spaces you belong to.
  A full list would be more useful and is declined as a disclosure with no equivalent.
- **A presigned URL is a BEARER TOKEN** — minted only after exactly the authorization the direct call
  would have had, signed by the **caller's own assumed session**, and in **no emitted record** (the
  span carries the key's *length*). Its lifetime is clamped to the **credential that signed**, read
  in the same call — never to `DurationSeconds`, which agrees today and will not under Access
  Grants, and never by assuming a second time.
- **The dev-unauth path is RETIRED** — it worked by calling S3 unsigned from the browser, and no
  unsigned call is left. The `VITE_` allowlist is now `lib/env.ts` alone; local dev points the SPA at
  an API.
- **A document that belongs to no user has no space, so it gets its OWN route** — `_config/` and
  `_directory/` are not prefixes any caller's claims authorize, and leaving one on the object
  surface makes every read a 403 that falls back to defaults, which looks exactly like health.

## Auth

Cognito User Pool, ABAC: the `username` principal tag is stamped from the verified token claim
**server-side** (unspoofable; never client-asserted). One shared IAM role for all users; per-user
isolation via `${aws:PrincipalTag/username}`. (SPEC-011; reversed the earlier "no Identity Pool".)

**What stamps it changed in SPEC-202; the model did not.** The Identity Pool stamped it from
SPEC-011 until 2026-08-31, exchanging the ID token for credentials in the browser. The API now reads
the same claims out of the same token and assumes the same role with the same tags — one computation
over one input, which is why no policy was rewritten and why the role is reused rather than minted.
The pool is deleted and the browser holds no AWS credentials at all. Full entry:
[The Identity Pool is retired, and no one's sign-in changed](#the-identity-pool-is-retired-and-no-ones-sign-in-changed-spec-202).

## Hosted UI = Managed Login v2

The domain runs Cognito **Managed Login** (`managed_login_version = 2`); the classic Hosted UI didn't complete the OAuth redirect after self-service signup confirmation (user landed confirmed-but-signed-out). Sign-in and signup both route through Amplify `signInWithRedirect`. The branding resource is provider-6.x-only (repo pins `~> 5.0`), so CI ensures Cognito's default branding post-apply (`deploy-infra.yml`); revisit when the provider is bumped.

## No backend

Browser → AWS direct. Cognito **trigger Lambdas** are allowed (service config, not an API).

> **Superseded (2026-08-28).** This premise no longer describes the system. Privileged work moved onto
> seven **control planes** (SPEC-051 onward), and SPEC-192→197 added an **HTTP API** that verifies a
> bearer and serves routes. What survives is the boundary, not the absence, and the two live rules are
> **no second API** and **no new browser-side AWS SDK call on a path an API route already serves**.
> (Updated 2026-08-29: this marker used to say the browser still called S3, Athena and Glue directly
> for most reads. SPEC-198 and SPEC-199 ported both surfaces; what the browser reaches without the API
> is presigned S3 bytes, Cognito, and the control-plane `sqs:SendMessage` enqueues. **Updated again
> for SPEC-202 (2026-09-02):** the enqueues went with SPEC-200's grant removal and the Identity Pool
> went with SPEC-202, so the browser holds **no AWS credentials and no AWS grant at all** — what it
> reaches without the API is presigned S3 bytes and Cognito through Amplify, and nothing else.) Full
> entries: [`control-planes.md`](control-planes.md) and the API entries below. Shape:
> `docs/architecture.md` → *The control planes* and *The API layer*.

## Usernames

Usernames are the S3 prefix = principal tag = Glue DB name → validated at signup by the pre-signup Lambda; SPEC-033 tightens to catalog-safe `^[a-z][a-z0-9_]{2,62}$`.

## Bucket 2 (shared-space)

User-created shared connections via a privileged async control plane (FIFO SQS → EventBridge Pipe → Standard Step Function) — reverses "no backend" for shared-space mutations only; access = a membership principal tag (SPEC-056). **The tag set is ten slots PER USER** — Cognito `custom:shared_space_1..10`, each holding one space name — because a session tag holds exactly **one value** and IAM cannot iterate a list inside a `Resource` ARN. (The Identity Pool's one-claim-to-one-tag mapping was the original statement of that constraint; SPEC-202 retired the pool and the constraint is unchanged, because the API stamps one tag per claim for the same reason.) A space's own member count is unbounded; what is capped is how many spaces one person can be in. The Step Function **orchestrates single-task verb Lambdas** (`validate-authorize → Choice(action) → create-space | add-members | remove-members | leave | delete-space`) sharing a **`shared-space-common` Lambda layer** — **not** one monolithic provisioner (SPEC-062 refactor; the 050→054 monolith is decomposed). The six Lambdas + the Step Function keep **one shared `orchestrator` role** (per-verb roles were descoped — user decision, SPEC-062 FR-005); ~~the layer is CI-built/published (deploy-lambdas) with TF `ignore_changes=[layers]`~~ **— superseded by SPEC-213:** every function is container-packaged, declares no `layers` at all, and gets its shared code from the image; `ignore_changes` names `image_uri`. The one-shared-`orchestrator`-role decision is unchanged. **Create is creator-only** (members added later via add-members from the Connections tab). Decision record: `lambdas/info/planes/shared-spaces.md`; Lambda rules: `lambdas/info/best-practices/lambdas/lambdas.md`. Do NOT build the old daily-IAM-pipeline / user-managed-keys models.

## Member join status (SPEC-073)

The owner projection carries a per-member `pending`/`active` chip. Membership stays `members: string[]` (source of truth in the registry); join status is a separate `acknowledged: string[]` list — a legacy record without it reads as all-active (back-compat). A **seventh verb `acknowledge-membership`** (member-only, idempotent, same shared `orchestrator` role) flips pending→active; the browser enqueues it once/session when a member resolves a shared space (`useAcknowledgeMembership` from `FilesPage`). Display + bookkeeping only — access is still granted at add time.

## Member roster for members (SPEC-075)

SPEC-053's member-privacy stance is **reversed** — every member sees a **read-only** roster (owner tagged + first, same `Member[]` join-status projection the owner sees), via "View members" on their Connections card. `cache.write_roster_to_all` fans the roster out to the owner + every member on add/remove/leave (best-effort per member, CAS-safe); member entries now carry `members` too. No management power for non-owners; no new IAM (orchestrator already writes every user's cache). Legacy member entries backfill on the next membership change.

## Dev-unauth path

`VITE_S3_DEV_UNAUTH=true` browses a test bucket read-only without auth (local only); production `/files` always uses the authenticated user-space bucket (SPEC-013).

> **SUPERSEDED 2026-08-29 by SPEC-198 FR-012.** The path is gone. It worked by calling S3 unsigned
> from the browser, and after the object surface moved behind the API there is no unsigned call left
> to make. Full entry below: *The dev-unauth path is retired*.

## The username directory is built from S3, not Cognito (SPEC-146)

The daily builder enumerates the user-space bucket's **top-level common prefixes**. It makes **no
Cognito call**, and a test asserts the module never names `cognito` in any import, attribute or call.

**The reasoning inverts the obvious answer, which is why it is written down.** *Today* Cognito is the
complete record of who exists and S3 is not: the personal prefix is created **by the browser**, by
`ensurePrefixMarker` on the first visit to `/files` (SPEC-014, a deliberate no-backend decision), so a
confirmed user who has never opened the file browser has no prefix. On that reading Cognito wins.

*After the client transition it reverses.* `transition_plan.md` §2 item 7 settles that **sign-in
provisions nothing** — and §3.12 (2026-09-04) settles what provisions instead: a **portal-owned
provisioner** creates every known user's space **before anyone signs in**, and `ensurePrefixMarker`
is deleted outright (§6.3), its write moving to that provisioner. *This paragraph previously said the
sync pre-creates the spaces and the client's own automation creates them for new users; the
conclusion below is unchanged and strengthened — S3 becomes complete for **every** known user rather
than for everyone who has been synced.* At the same
time federated login makes `cognito:username` a **synthetic `identitycenter_<subject>` value** rather
than the catalog-safe username (§6.1), and users appear in the User Pool only after their first
sign-in. So S3 becomes complete and Cognito becomes both incomplete **and wrong-keyed**.

Choosing the source that is right on the far side of a migration already in flight beats the one that
is right today, particularly when today's gap is bounded: pre-production, no production users, and the
failure mode is a name missing from a suggestion list that still accepts free text.

**Do NOT add Cognito as a union "to be safe."** A second source with different completeness properties
is a second thing to reason about every time the directory looks wrong.

**The directory is advisory and is never an authorization input.** No control plane reads it; every
existence check stays `admin_get_user` against the User Pool (`shared-space-common/membership.py`,
`tscommon/cognito.py`), and an unknown name is still reported to the user as a notification. A
tripwire test fails if any Lambda outside `user-directory-build` references the path, the prefix or
the key constants.

Full account: `docs/spec-delivery/SPEC-146-username-directory-daily-builder.md`.

## Every authenticated user can read the username directory (SPEC-146)

`_directory/usernames.json` is readable by **every authenticated portal user**, through one
`s3:GetObject` statement on the portal role. That disclosure is **intended and accepted**, not
incidental, and it is recorded here rather than left implicit because the object is a single file
listing everyone in the organisation.

What makes it acceptable is that the set is already disclosed several ways: a username **is** the S3
prefix, the `username` principal tag and the Glue database name (SPEC-033); it is visible on every
shared-space roster to every member (SPEC-075); and a prefix-search feature discloses the set by
construction — a typeahead that would not confirm whether `bob` exists is not a typeahead. The
document holds **usernames and nothing else**: no display names, no email addresses. An email is not
metadata under this repo's field rule and has no place in a document every user can read.

**What was deliberately NOT granted:** ~~no `ListBucket` widening (the portal role's grant stays
conditioned on the caller's own prefix, so `_directory/` is invisible to the file browser and the file
browser needed no change),~~ no `PutObject`, no `DeleteObject`. The user reads; the daily builder is the
only writer. **— Superseded in part (2026-08-30, #555):** the portal role may now list `_directory/*`
and `_config/*`; what keeps both out of the file browser is the API, which lists only a space the
caller's claims authorize.

**The accepted POPULATION changes at the transition, and the acceptance above is weakest for exactly
the people it adds.** `transition_plan.md` §3.12 provisions every known user's prefix ahead of use,
so the document stops listing "everyone who has used the portal" and starts listing everyone the
client has. Two of the three arguments above still hold for a never-signed-in user — the username is
still the prefix, and a typeahead still discloses the set by construction — but the shared-space
roster one does not, because they are on no roster. The decision is recorded there as deliberate;
what would retire it is a liveness rule in the builder, not a change to this grant.

**The builder's own `s3:ListBucket` is unconditioned**, and what that grants is stated rather than
minimised: `Delimiter="/"` is a property of the *code*, not the grant, so the role can enumerate every
object key under every user's prefix. Accepted because it holds **no `s3:GetObject` anywhere** (it can
list names and read nothing), because key names are metadata under the field rule, and because it is a
Lambda role with no user-assumable path. The obvious tightening — an `s3:prefix` condition on the
empty string — is **rejected, not overlooked**: whether botocore serialises an empty `Prefix` into a
condition key at all is an implementation detail, and if it does not the grant fails closed and the
builder's only listing call breaks. `simulate-custom-policy` would agree with whatever context key the
author supplied, so it would confirm the assumption rather than test it. If the grant ever becomes
uncomfortable, the sound fix is a separate bucket, not an unverifiable condition key.

## No shared-space directory is published; suggestions come from your own cache (SPEC-158)

`TableShareDialog`'s space entry suggests only the shared spaces the signed-in user belongs to,
read from the connections cache `useConnections` already fetches. **A complete list of every space
in the organisation would be strictly more useful, and it was declined.**

Strictly more useful because sharing a table to a space does **not** require membership —
`test_recipient_space_membership_not_required` pins that a space the sender does not belong to is a
valid target — so the suggestions cover less than the field accepts, on purpose. Membership is the
only thing that is waived: an emptied space keeps `status: "active"` and is still refused, because
`may_receive_share` wants an owner as well as a status. The cost of closing that gap is a **bulk**
disclosure, and the argument is about the bulk rather than about secrecy: a non-member can already
learn whether one named space exists by attempting a share and reading the refusal, which is the
existence oracle `control-planes.md` records as open on the transfer path and deliberately not
inherited. That is per-name, authenticated, logged, and it copies a table; a directory is every
space name in the organisation, free, to every signed-in user, and space names are user-chosen and
often descriptive (`acme_merger`, `q4_layoffs`). The username directory is not a precedent — a
username is already the S3 prefix, the principal tag and the Glue database name (see the entry
above). The trade was put to the user on 2026-08-05 and **declined in favour of suggesting only what
the user can already see.**

**Do NOT add a space directory "for symmetry with SPEC-146."** The absence is the decision. What
holds the line in the UI is that a space the user does not belong to **stays typeable and still
commits**, with a note that says it may exist and simply not be one of yours — worded that way
because this note is the one place a user could be misled into thinking the target was invalid.

Two consequences worth carrying:

- **The suggestion source is a prop, not a hook call** (`SuggestionSource = {status, search}`).
  `UsernameCombobox` reaching for `useUserDirectory` itself was the right reading with one source
  and the wrong one with two; a near-duplicate component would have been the alternative. A second
  source is the trigger to revisit that kind of deviation, not to fork.
- **A second source costs no request.** The space list is a query the app already makes for the
  Connections page and the Query rail, and the ranking is SPEC-147's `buildIndex`/`search`, which
  were never username-specific. No Lambda, no published document, no IAM, no env var, no new AWS
  call — a test asserts the space path issues none.

## A feature flag is presentation, never authorization — and it lives beside the username directory (SPEC-162)

**The document is `_config/feature-flags.json` in the USER-SPACE bucket**, published by
`.github/workflows/deploy-config.yml` from `config/feature-flags.json` in git. Four flags — `files`,
`query`, `sharedWorkspaces`, `dataQuality` — a total `defaults` block and per-environment partial
overrides, resolved in the browser against ~~`VITE_ENVIRONMENT`~~ **— superseded by SPEC-192:**
`/config.json`'s `environment`, since a production bundle reads no `VITE_` name. Since SPEC-198 the
browser reads the document through `GET /v1/feature-flags`, not from S3.

**A FLAG HIDES A SURFACE AND REVOKES NOTHING.** Turning Query off hides the tab and its entry points;
the portal role's Athena, Glue and S3 grants are byte-identical either way. This is SPEC-146's
advisory rule for the username directory applied to a second document, for the same reason: the
moment someone treats an advisory document as a boundary, it becomes one, badly. The fence is not a
convention — `featureFlags.service.test.ts` enumerates every `*.service.ts` under `features/` and
every module under `lib/` and fails if one imports the flags module. It was verified against a
deliberate violation rather than trusted; the sweep named the offending file. The realistic failure
it forbids is not exotic: `if (flags.query) return` inside a service reads like a guard and is a
client-side access control, which is no control at all.

**The document was specced into the ADMIN bucket first and moved before any code was written.** That
would have given the portal role its first grant on a bucket admin-only since SPEC-032 — and the
grant would not have worked. The admin bucket carries an explicit "never read by the browser" comment
in place of a CORS configuration, and its host is absent from the enforcing CSP `connect-src`. Two
infra gates on the exact surface SPEC-140 records breaking fresh sign-in for a day, for nothing
`_config/` beside `_directory/` does not already have. **The generalisation is the useful part: for a
browser-read advisory document, the bucket that already serves one is the cheap answer** — and it is
`_config/*`, one `s3:GetObject`, ~~no `ListBucket` widening,~~ no write, no deploy-role change, no
CORS, CSP or bucket-policy change. This is now the precedent for a third such document. **—
superseded in part (2026-08-30, #555):** the portal role may now list `_config/*`, which is what lets
the API report a never-published document as absent rather than denied.

**"It already works" is a claim about three files this spec does not touch, so all three are
asserted.** `lambdas/test_feature_flags_config.py` checks the user-space CORS rule still allows `GET`
from the app origin, that the bucket host is still in `csp_connect_src`, and that the portal role is
still on the bucket policy's hand-maintained principal allowlist — plus the deploy role's existing
`s3:*` on `${user_space_bucket_arn}/*`, which is why the publish adds no IAM. If one of these ever
fails it is a **finding to raise, not a licence to widen infra inside this spec**. **— Superseded:**
those assertions were cut on 2026-08-28 (#540), and since SPEC-198 the read goes through the API,
so the bucket's CORS rule and its CSP entry are no longer on its path.

**AN UNUSABLE DOCUMENT FALLS BACK TO ALL-ON, AND THE FALLBACK IS SILENT.** Missing, unreadable,
unparseable or a version this build has no reader for: the compiled-in defaults take over and the
hook reports `'fallback'`. No banner, no toast — the user is not the audience for that failure.
Failing closed was the alternative and is worse: one S3 blip would strip the app to Files for
everyone. **The accepted cost is stated rather than hidden: during an outage a deliberate "off" does
not take effect.**

**That silence is exactly why the read had to be made observable.** Every default is `true`, so a
permanently-blocked fetch renders *identically* to a healthy environment — no user would report it
and no screenshot would show it. Hence FR-009: a dev-only `console.debug` naming `ready` vs
`fallback` (stripped from production, as `warnIfMisconfigured` is), and a live check whose pass
condition is a **200 in the network panel**, not an app that looks right.

**Two tolerances, deliberately different.** A wrong VERSION or top-level SHAPE is refused whole —
this build has no reader for it, and guessing at an unknown shape is how a flag comes to mean
something nobody wrote. A single malformed VALUE inside an otherwise-fine document falls back **for
that key only**; one bad line must not discard three good ones. The resolver walks the compiled-in
KEY LIST rather than the document's keys, which is what guarantees all four are present and boolean
whatever the document said.

**The service is stricter than `getUserDirectory()`, and that divergence is the load-bearing part.**
There, absent and corrupt collapse into the empty state because "no suggestions" is an honest answer.
Here the equivalent answer is all-on, which is indistinguishable from success — so the distinction
has to survive the return or `'fallback'` could never be reported. A MISSING object is a failure for
the same reason: it means the publish workflow has never reached this bucket, which is a deploy
defect and not a starting state.

**The validator reads the publish workflow's matrix rather than being handed a target list.** FR-002
requires the environment/target check in both directions — a block nobody publishes, and a target
that publishes nothing but defaults — and a list passed in by the same workflow that declares it
would compare a copy of the answer with itself. `deploy-config.yml`'s `environment_name:` entries are
the single declaration; a matrix that parses to nothing is a hard error, not an empty set, because
that is how this stops checking (a rename, not a deletion). The key is `environment_name` and not
`environment` precisely so a GitHub Actions job keyword cannot masquerade as an upload target.

**The publish addresses ONE EXACT KEY — no `sync`, no `--delete`.** `_directory/usernames.json` lives
one prefix over in the same bucket; a mis-scoped reconcile would break username typeahead everywhere
(SPEC-146/147) for a feature nothing user-facing depends on yet. It is also a separate workflow from
the app deploy (`Deploy App` then, `Deploy SPA image` now) on purpose: flipping a flag must not be a
rebuild, which is why the upload carries `Cache-Control: no-cache`.

## Gating is by REGISTRY, not per-component opt-in (SPEC-163)

**`GATED_SURFACES` names every surface every flag hides — 26 rows, keyed by flag — and one test
walks it in both states.** Not a checklist and not a convention: a row carries the surface's
ACCESSIBLE NAME, and `gatedSurfaces.test.tsx` renders each twice (flag off, flag on) and asserts
by that name. A row it cannot make disappear fails; a row with no reach-recipe fails; a recipe
with no row fails; an empty registry, or a flag with zero surfaces, fails.

**THE TABS ARE THE EASY PART, AND THAT IS THE WHOLE ARGUMENT.** "Create table from this folder"
lives on a file-browser toolbar and is a *Query* feature. "Share table" lives in the Query rail
and pushes into *Shared Workspaces*. "Check data quality" is a button on a file-browser selection. A
per-component pass finds three of those and ships the fourth visible — the failure mode
`reviewer-contract.md` records from log-forge's SPEC-033. Adding a fifth entry point is now a registry
edit rather than a discovery exercise.

**The reach-recipes live in the TEST, not in the registry.** The registry stays declarative and
reviewable by someone who has read no component; the driving (open this drawer, expand that
node, click that menu) is test business. A guard asserts the two sets are equal, so they cannot
drift.

**One sanctioned door, and it is now absolute.** `useFeature(key)` answers "is this on?";
`FeatureGate` wraps; `useFeatureSet()` serves the three consumers that genuinely cannot ask one
question — `Header` builds one predicate for two nav components, `FeatureRoute` must tell "off"
from "not known yet", `LandingPage` picks the first enabled destination. **A tripwire test fails
if any module outside `features/feature-flags/` so much as names `useFeatureFlags`.** The spec
asked that nothing else read it; enforcing it by reading the source is stronger than asking,
because the convention is exactly what an urgent change forgets. The failure it prevents is not
exotic: a consumer that forgets `'loading'` must read as OFF makes a tab flicker, or lets a page
fetch before the answer arrives.

**Hidden means REMOVED, never `hidden` and never disabled.** A visually-hidden control is still
in the accessibility tree, still focusable and still announced — so `display: none` would leave
a screen-reader user able to reach a feature the environment says is not there. `FeatureGate`
renders no wrapper element at all, and the Share-table kind toggle renders **no toggle** rather
than a single-option radio group, which is a control that asks a question with one answer and
implies the other option exists somewhere.

**A gated route keeps its path and swaps its ELEMENT.** It must still match, or a disabled
feature falls through to `*` and tells a user with a perfectly correct link that their URL is
wrong. `FeatureUnavailablePage` says "not available in this environment" — a property of the
deployment, not of them — names no reason and offers no appeal route, because a flag is
presentation and inventing one would imply a permission model that does not exist.

**`FeatureRoute` renders `LoadingState` while the flags resolve, and that is not a contradiction
of "render nothing while loading".** The rule is right for a tab and wrong for a whole viewport:
an empty frame reads as a broken page where an absent tab reads as a tab that was never there.
What actually matters is that **the page does not MOUNT** — every gated page fetches on mount,
and on `/data-quality/:space/:requestId` an optimistic render would make a disabled feature an
existence oracle for someone else's report (SPEC-113's rule, inherited).

**`components/` still imports no feature.** `PrimaryNav` and `AppNavDrawer` take an
`isPathEnabled` **predicate**, supplied by `Header` — the one place that knows both the auth
state and the flags. Required, never defaulted: a default would make an unwired caller ship every
tab while looking correct. Both nav surfaces get the SAME predicate, because a tab hidden in the
topbar and present in the mobile hamburger is a feature that is still one tap away.

**`?space=` with shared workspaces off is NOT READ, not resolved-and-refused.** `useFileSpace`
gained `ignoreSpaceParam`; routing it through the existing `fellBack` path would raise "That
shared space is no longer available", which is a false statement about a space that is fine and
that returns the moment the flag flips back. `useConnections` still resolves normally — a flag
may not touch a service (SPEC-162 FR-006).

**Shared databases in the Query schema rail joined the contract (a deliberate extension).**
Leaving `teamspace` browsable while the spaces list and `/connections` are gone reads as a bug
rather than a policy. **Filtered at the VIEW, never at the service:** `useConnections` still
fetches every space, and a saved query naming a hidden database still RUNS. Hiding a surface is
not revoking access, and the grants are untouched.

**A REACH-RECIPE THAT RE-IMPLEMENTS THE GATE PROVES NOTHING, and two of them did.** The rows for
the Files spaces rail and the Query rail's shared databases originally rendered test-local host
components carrying their own `useFeature(...) ? … : null`. Measured in review: deleting BOTH
real gates left all 1843 tests green. Recipes now render the real page, and the same mutation
fails exactly those two rows. The rule generalises — a recipe may drive the app but may never
restate the condition under test.

**The off-half must be asserted AFTER settling, never inside `waitFor`.** `useFeature` reports
`false` while the flags resolve, so a retry loop's first attempt lands at the one moment every
surface is legitimately absent — and an ungated surface that merely renders asynchronously
passes. Each recipe carries an `anchor` (something present regardless of the flag) and absence
is asserted once. The same review found the paired sloppiness: `Go to Dashboard` was matched by
`/^Go to /`, which also matches the "Go to Query" the page correctly renders with Files off.

**`useFeatureFlags` distinguishes THREE auth states, not two.** Still-resolving is `'loading'`;
**settled with no user is `'fallback'`**, because a session with no credentials genuinely has
the compiled-in defaults in force. Collapsing the two made the documented no-AWS local workflow
a permanent spinner behind every gated route — `FeatureRoute` never left its neutral state.
Going the other way (treating still-resolving as fallback) would show every gated surface and
take it away a tick later, which is the flicker FR-007 exists to prevent.

**Hiding a surface is not hiding a WRITE PATH, and the first pass missed that.** With shared
workspaces off, the spaces rail was gone but the move/copy destination picker still offered a
space selector and the data-quality start dialog still listed shared spaces — so a user could
still paste a file into `marketing_data`. Both are now filtered at the view and registered. A
row is "a way in", not "a button".

**Test-harness consequence, and it bit before it was understood.** Gating made every gated
surface wait on a fetch, so `renderWithProviders` now seeds the flags all-on by default
(`seedFeatureFlags`, opt-out) — the same answer production reaches when the document is
unreadable. **`setQueryDefaults` must run before `setQueryData`**: the test client uses
`gcTime: 0`, so an observer-less seed is evicted the instant it is written, and every gated
control that mounts LATER — inside a drawer the test has to click open — starts from a cold
pending query and reads as flagged off. It passed every first-paint assertion and failed only
behind a click.

## The roster contradicted the connections list because a fan-out list was missing one verb

For one membership, at one moment, the app stated two things: the connections row read
`livecheck_0814a | Member | Active`, and the roster one click away read `agriffith | Pending` under
*"A Pending member has been invited but hasn't signed in yet."* The reader of that sentence **was**
the member, and they **had** signed in.

Neither settled decision is wrong. SPEC-073's `acknowledge-membership` flips pending→active and
writes the **owner's** projection; SPEC-075's `cache.write_roster_to_all` fans out on
**add/remove/leave** — a list that does not include acknowledge. So every member's copy, including
the acknowledging member's own, stayed frozen at add time, and the roster is the **only**
member-facing view of who is in a space.

Closed on both sides. The verb now fans out, and **the fan-out cannot fail the run**: the registry
write is the consistency point and has already committed, so a raise would fail the execution, and
the retry would find the member already acknowledged, no-op, and never write the caches at all —
turning a recoverable stale roster into a permanent one. In the browser, `displayedMemberStatus`
renders the reader's own row `Active` regardless, and the explanatory sentence renders **only when a
row it describes is on screen**, which closes the window before the fan-out lands.

## A verification principal is read-only, or it is a back door

Two owed assertions were unmakeable by anyone. SPEC-170's is the load-bearing one — that a
`destination_occupied` refusal did **not** already initiate retrieval — and `dat-prod-archive`
explicit-denies the laptop IAM user, its execution role trusts `lambda.amazonaws.com` only, the
deploy role is GitHub-OIDC-only, and **no CloudTrail trails existed**. The script itself records
that a refusal which had already started retrieval "looks identical from the UI", so there was no
proxy, and being wrong costs 3–5 billed, uncancellable hours.

The answer is **audit-shaped, not a grant on the data path**: a trail recording the archive
bucket's object-level events (`RestoreObject` is a CloudTrail **data** event, which is why it never
appears in the console's Event history), and a role that reads the catalog back. What is
deliberately absent is the whole of its safety: no `SELECT`, no `DATA_LOCATION_ACCESS`, no
`lakeformation:GetDataAccess` (the credential vend for reading a table's *data*, easy to add "to
make `GetTable` work", which it is not needed for), no data-bucket ARN, no `Resource: "*"`, and no
`iam:PassRole` on the deploy side — nothing but a human may assume it. A test asserts each, and
asserts the role appears nowhere in `portal-role-permissions`.

**The role is trusted to NAMED principals and does not exist until one is named**, which the
plan scan is what forced. The first version delegated to the account root; `CKV_AWS_61` rejected it,
and accepting the finding would have violated the accept list's own rule — that list is for findings
with **no scopable alternative**, and naming the principal is one. `verification_principal_arns` is
empty by default. **The trail is unconditional**, because it needs no principal and is the half that
unblocks SPEC-170.

> **CORRECTED 2026-08-14 (#461): the ARNs travel as a repo variable, NOT a gitignored
> `terraform.tfvars`.** The original wording named tfvars, which implies a local apply — and no
> human identity in this account has one. The laptop IAM user is not on the data buckets' policy
> allowlists, so `tofu plan` reads `dat-prod-user-space` and `dat-prod-archive` as absent and
> proposes to destroy and recreate them: measured `25 to add, 3 to change, 13 to destroy`, both
> buckets in the replace set, before failing on `GetLFTag` for `portal-managed`. `modules/data/s3.tf`
> had already recorded this exact failure mode for the deploy role under SPEC-016 — the general
> lesson was written down and still did not reach the one variable a human was told to set by hand,
> which is the part worth carrying: **a config route that only an operator walks is not exercised by
> anything, so it is worth checking that the route exists before documenting it.**

**The trail's own status is part of the assertion.** A trail that is off returns an empty result,
which reads exactly like a `RestoreObject` that never happened — so the script confirms
`IsLogging: true` before reading an absence as evidence.

**No blanket write-Deny on the trail bucket**, and the omission is deliberate: the obvious one rests
on a condition key CloudTrail's own delivery must populate for its Allow to survive, and if it does
not, delivery fails and the record is silently empty. That is this spec's own failure mode with the
evidence rather than a scanner.

## The provider block is the API's verifier configuration, and it is server-side (SPEC-192)

`OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URI`, `OIDC_USERNAME_CLAIM` — API Lambda environment
variables, provisioned by the infrastructure spec and consumed by the auth-boundary spec. **None of
it appears in the browser's document**, because the browser verifies nothing: it sends the ID token
Amplify already holds. The converse holds too — a verifier configured by reading the browser's
document has a client-supplied trust anchor.

**This is a VERIFIER, not an OIDC client.** No code exchange, no PKCE verifier, no client secret, no
redirect URI, no scope list: those belong to Amplify, in the browser, unchanged by this arc. Building
a client here is the shape of error the small field set exists to prevent.

**`OIDC_JWKS_URI` is a field, not a derivation of `OIDC_ISSUER`.** The well-known path is a
convention, not a guarantee, and hard-coding it makes the verifier provider-specific in the one place
that would fail closed and silently.

**The exclusion cuts ONE way only, and that is the whole subtlety.** A test intersects the document's
key set with the verifier's field names plus a case-insensitive substring rule over `oidc`, `issuer`,
`audience`, `jwks` and `secret`. It is guarded in **both** directions: a synthetic key set containing
`issuer` must be flagged (a checker that flags nothing passes the first case forever), and the four
Cognito values Amplify actually reads must **not** be. That third case can fail today. Adding
`clientId` to the forbidden set is the specific mistake — `cognitoUserPoolClientId` survives an
exact-match rule and dies under a substring one — and the visible result is not a failing test but a
Hosted UI round trip that never completes. `cognitoDomain` is likewise **not** a provider-block field:
Amplify POSTs the code exchange to it. The forbidden set is about *the API's trust anchors*, not about
the word Cognito.

Detail: `spec-delivery/SPEC-192`.

## Authorization lives in the router, not in an API Gateway authorizer (SPEC-193)

The API serves every path through one `$default` route and one integration. A per-route authorizer
would have to duplicate the route table before it could say anything at all — and, more decisively, it
would be a **second reader of the same token**, able to disagree with the router about the claim the
role assumption is scoped by, with no arbiter between them.

**SHIPPED (SPEC-195, 2026-08-27); the "nothing to authorize" reasoning below is past tense.** The
API resolves a principal before dispatch and refuses any undeclared route — an unidentified caller
gets 401, not 404, whatever path they ask for. The disposition is unchanged and now load-bearing:
the verifier is a module the router calls. The disposition
for `CKV_AWS_309` in `security-baseline.md` is the audit-trail wording, and it rests on the bearer
token — never on the session cookie the arc's re-scope removed.

Detail: `spec-delivery/SPEC-193`.

## The API is a verifier, not an OIDC client (SPEC-195)

**The API verifies a bearer token and performs no login flow.** No code exchange, no refresh token, no session, no cookie. Sign-in is untouched: the User Pool, Managed Login v2, Amplify in the tab and the Hosted UI round trip all stay exactly as they are. The browser already holds an ID token; from here it sends that token as an `Authorization` bearer and the API takes the username from the **verified claim**. That is the trust model the seven control planes have had since SPEC-011 — the token changed transport, from a queue message body to a header, and nothing else. An earlier draft of this spec built a backend-for-frontend with all three; that work is real and deferred, and a reader who saw it should read this entry as the correction.

**No ambient credential means no CSRF surface.** CSRF exists because a browser attaches cookies to cross-site requests automatically; a bearer header is attached only by script that can read the token, and cross-origin script cannot. A later spec introducing a cookie re-opens CSRF, `SameSite`, and the *two-origins-one-registrable-domain* constraint this design relaxes from a requirement to a preference. **CORS is still required.**

**Provider-agnosticism lives in five configuration fields** — issuer, audience, JWKS URI, username claim, required claims — and this is load-bearing rather than a convenience: `transition_plan.md` §3.3's baseline variant deletes Cognito outright, so a configuration-driven verifier is the difference between a config change and a rewrite of every auth path in the product. The JWKS URI is **explicit configuration, never derived from the issuer** in the verifier or in the API module; Cognito publishes under its issuer and Entra does not. The concatenation appears **once, at the composition root**, which already names Cognito three ways and is therefore already a site any swap edits — and no test pins the `/.well-known/` path, because pinning a fact about one provider would go red on a correct configuration for another.

**A key-retrieval fault is not an authentication failure**, and getting this wrong is user-visible. `PyJWKClientConnectionError` subclasses `PyJWKClientError`, so one broad handler folds a provider outage into "your token is bad" — a 401, which tells every user to sign in again for something no user can fix and brings a refresh storm with it. Worse, PyJWT raises that transport type for exactly two causes, so classifying by type alone left a provider answering a proxy page, a JSON array, an empty key set or failing TLS all arriving as ordinary verification failures. The classification is by **what failed**, not by exception type: a `kid` genuinely absent from a key set that *was* read is an auth failure; anything that stops the key set being read is a 5xx.

**The refusal surface is deliberately uninformative, and expiry is deliberately NOT distinguished.** Every authentication failure returns byte-identical bytes, because a body that varied per failure is a map of which check failed. Expiry is the one a builder is tempted to disclose, to let the browser skip a refresh — but the browser refreshes once and retries once on **any** 401, so a discriminator buys the client nothing and costs the oracle. The assertion that can fail is that the expired body is byte-identical to the no-token body.

**The JWKS refetch is bounded per container, and the cost is accepted.** An unknown `kid` makes `PyJWKClient` refresh the whole key set, so a stream of random `kid`s is an unauthenticated amplification against the provider from requests that will never be authorized. The bound is a **cooldown on the refetch**, not a negative cache keyed by `kid` — that design suggests itself and does not work, because it misses on every *distinct* unknown `kid`, which is exactly the traffic being bounded. The cost is bounded eventual consistency: for up to 60 seconds after a rotation this API refuses tokens signed with the new key. Cognito publishes both keys across a rotation and the window sits far inside any overlap, so no real rotation is expected to reach a user; the trade is a bounded refusal against an amplification vector, and refusal is the fail-closed direction.

**`error.stack` carries no credential, and the mechanism is PREVENTION rather than redaction (SPEC-195, extended by SPEC-196).** `log-foundry` attaches `traceback.format_exception` to every failed span. SPEC-130 examined that and **accepted** it *for file contents*, on the reasoning that `logs/` is admin-only and a stack is diagnostic metadata a failed run needs; that reasoning was never applied to a credential, and an ID token is a bearer credential for as long as it lives. `log-foundry` exposes no way to turn the capture off (re-verified against the pinned version, and now asserted by a test) — `max_stack_bytes` is a ceiling, not a control — so the answer is at the boundary. **What "at the boundary" means is worth being exact about, because the phrase reads like a redactor and is not one.** The exposure is not automatic: `format_exception` renders each frame's *source line*, not its locals, and the provider library's own messages carry no token material. The live route is this repo's own code putting a credential into text. So the mechanism is an AST sweep forbidding the event, the headers, a token — and, from SPEC-196, four session-material names — from appearing in an f-string, a `%`-format, a `.format()` call or a `raise` argument, paired with a sentinel test that drives a path **genuinely raising through the span** while holding a real assumed session, so the absence is asserted where a stack actually exists. **The residual is real and recorded**: a future route that interpolates a session value despite the sweep still reaches the log store. It is in `owed.md`, not implied to be closed. **The scrub's scope is credentials and nothing wider** — a scrub written against user-data-shaped strings would contradict the 2026-07-23 decision and redden its tripwire from a spec that never argued the case. If a later `log-foundry` gains an opt-out, revisit the decision; do not delete the sweep.

## The API reads the same claims and assumes the same role with the same tag set (SPEC-196)

> **AMENDED since SPEC-202 retired the Identity Pool.** `identity-pool.tf` and its map are gone, so
> there is one credential path, and `lambdas/api/apicommon/identity.py` is the only declaration of
> which claim feeds which tag. The equivalence below is the record of why no policy was rewritten.
> The tag-key paragraph's population has moved too: only `portal-role-permissions.json.tftpl`
> hard-codes `username` now, and `var.principal_tag_key` reaches the trust statement's key list
> and the API's environment as well as the analytics module. The guard is no longer a read-back
> against a declaration AWS applies. It is a pinned copy of the retired map in
> `test_identity_apicommon.py`, the trust-to-template key comparison in
> `test_portal_role_preservation.py`, and the `validation` on the variable.

**The equivalence is not an analogy — it is the same computation over the same input.** `identity-pool.tf` declares which claim feeds which tag: `username` from `cognito:username`, `shared_space_k` from `custom:shared_space_k`, merged into one map because there is only one per (pool, provider). AWS applies that map to the ID token the browser presents. The API is handed **that same token**, verified against the provider's JWKS on every request, and applies **the same map**. Same token, same claims, same tag names, **the same role** — which is why nothing downstream can tell the two credential paths apart, and why **not one IAM policy, bucket policy or Lake Formation grant is rewritten**. A policy sees a session tag, not who stamped it.

**The claim names are the only thing copied from the Identity Pool, and copying them is what makes the preservation provable.** Sourcing the membership tags from the shared-space registry instead would be defensible in isolation and would **break the equivalence**, turning a provable preservation into an argument. What else would break it, precisely: taking a tag value from a header, a query parameter, a body field, an unverified JWT, or a username re-derived from a path segment — and any route that accepts a username or space name and uses it to *select* credentials rather than to *scope* a call made with the caller's own.

**The tag set is the WHOLE tag set, and stamping only `username` fails silently.** Omit the ten slot tags and personal S3, personal Glue, notifications and the file browser all keep working; only shared spaces refuse — for which the app already has a "Refresh access" recovery built for a documented propagation delay, so a missing tag *presents as that delay*. **An unoccupied slot contributes NO tag**, never one with an empty value: an empty value makes a shared-space ARN resolve to the bucket followed by a bare slash, which is a live grant on every key beginning with one, and S3 permits such a key.

**The role is REUSED rather than minted, and that is the single strongest reason.** The user-space bucket policy Denies every principal whose `aws:PrincipalArn` is not on a hand-maintained allowlist that already names this role, and `aws:PrincipalArn` resolves an assumed-role request to the **role's** IAM ARN rather than the session ARN. Assuming the same role keeps the same entry valid; a new role would need a new entry, and this repo has already been bitten by a principal missing from that list.

**`DurationSeconds` is 3600 and it is a ceiling in BOTH directions.** Shorter caps every presigned download link and every multipart upload window at the shorter value — a user-visible regression with no failing test, because a presigned URL dies with the credential that signed it. Longer is refused outright: the function runs on an assumed-role session of its own, so this call is **role chaining**, which AWS caps at one hour and fails rather than clamps.

**A claim set is exactly as fresh as its token, and that is not a new defect.** A membership change takes effect on the next **token refresh** — SPEC-056's documented behaviour, unchanged, because the carrier is unchanged. If anything the new path is marginally fresher: the credential cache is keyed on the tag set, so a refreshed token whose slots changed is a cache miss on the very next request, where Amplify's own credential cache can hold the old credentials for the rest of the hour.

**Agreement between the tag key the API stamps and the key the policies expand is ASSERTED, not structural, and the reason matters.** `var.principal_tag_key` reaches only the analytics module; `portal-role-permissions.json.tftpl`, `portal-role-shared-space.json.tftpl` and `identity-pool.tf` all hard-code the literal. "One variable feeds both, therefore they cannot drift" is **false**, and threading the variable through those templates to make it true would edit templates the preservation claim forbids touching. So the guard is a read-back against the declaration AWS actually applies, plus a `validation` pinning the variable — because a default guards nothing on its own: an empty `TF_VAR` satisfies a required variable *and* overrides a default. A wrong value produces a session whose tags match no statement, which reads as `AccessDenied` everywhere and names nothing.

**The trust statement's conditions are a ceiling, never a floor, and the limit is stated rather than implied.** `ForAllValues:StringEquals` on `sts:TagKeys` bounds which keys may appear; it is satisfied by a subset **and equally by a request carrying none**, so it cannot require that `username` was stamped. It constrains keys and **not values**, and IAM offers no way to constrain a value. The unspoofability argument rests entirely on the value coming from a claim of a signature-verified token. Both actions — `sts:AssumeRole` **and** `sts:TagSession` — are required in the same statement: either alone renders, plans, applies and unit-tests green, then fails at runtime with a refusal naming neither the tag nor the missing action.

## Two credential planes, declared per route, defaulting to the user plane (SPEC-196)

> **AMENDED by SPEC-197 (2026-08-27) — the registry became a FIELD, and the guard's teeth moved.**
> `ROUTE_PLANES` is gone. The plane is declared on the route itself (`Route.plane`) in the transport
> contract, and `planes.planes_for()` derives it per call. The decision below is unchanged in every
> respect that matters — two planes, the user plane by default, the dangerous direction one-way —
> but the *mechanism* named in it is not what ships.
>
> The set-equality guard between the table and the dispatch table becomes a **tautology** once one
> derives from the other, so it is retained as a labelled regression tripwire rather than as the
> guard. What carries the guarantee instead: `plane` is a **required** `Literal` field, so a route
> cannot be declared without choosing; and a value that is neither of the two **raises at
> derivation**. That last half is one the set equality could never carry — a typo resolving quietly
> to user-only is indistinguishable from a correct user-only route, and the fail-closed guarantee
> would be gone with nothing to show for it.

**The failure mode fails OPEN, which is the whole reason this is machinery rather than convention.** A helper handing back the wrong client does not error — the call **succeeds**, against the wrong identity, returning right-looking data. There is no symptom to wait for. So: every AWS client comes from exactly one of two constructors, the **user plane** (the caller's assumed session) or the **API plane** (the execution role); the user plane is the default, because the dangerous direction is a user-scoped call escaping onto the execution role; and a route reaches the API plane only by being named in a registry whose keys are guarded for **set equality** against the router's dispatch table, because a hand-maintained list rots.

**The enumeration is an AST sweep, not review.** It forbids `boto3.client`/`resource`/`Session` and any import of `cpcommon.clients` — the second half matters as much as the first, because that module is a cache of *default-credential* clients, exactly the shape that works in every single-user test and serves the execution role's identity in production. The sweep **counts**: the package holds exactly one construction site, since "none outside the layer" is satisfied by a layer building six. It also closes the doors *around* the doors — a private import from the identity layer, and a `UserIdentity` minted anywhere but its own module, which would assume the role as somebody else and pass every test supplying a matching token. Every exemption is by **exact module path**, never a pattern: a pattern exemption silently exempts the next module named similarly.

**The route is set on the way IN, and this is the ordering that fails open when reversed.** The Python runtime does not hand each Lambda invocation a fresh context, so cleanup-on-exit is skipped by any path that does not reach the cleanup — and a route key left behind means the next request on a user-only route reaches the execution role and succeeds. The router sets a sentinel that authorizes nothing as its first statement, before even the public-route check; the exit reset is a second line, not the load-bearing one. The test that catches this is a **sequence** with the exit reset neutered, because while cleanup always runs the two are indistinguishable.

**An assume failure is a FAULT, never a denial, and the wrap is what makes that true.** STS answers `AccessDenied` when the trust policy is wrong — a missing `sts:TagSession` renders, plans, applies and unit-tests green — so an unwrapped error reaching the failure mapping carries that service code and is indistinguishable from the isolation model working. Every user would be told they lack a permission only an operator can restore. The identity layer wraps every STS failure before it leaves, which strips the service response so the failure can only be classified by what it is. **Measured**: swapping the classifier's two branches changes no outcome; removing the wrap changes two.

## The credential cache is keyed on the whole tag set (SPEC-196)

**A warm Lambda serves many callers in sequence and nothing about it is per-user.** Trace baggage is *cleared* at the start of every invocation precisely so one invocation's identity cannot leak onto the next; a credential cache deliberately **survives** the invocation, so it must be **keyed** instead — on the username *and* the ordered membership slots.

**Never the username alone**: that pins a caller to whichever membership set their first request of the hour happened to carry, turning refresh-to-propagate into refresh-and-nothing-happens. **Never nothing at all**: that serves the second caller the first caller's session, which succeeds against the wrong identity with the right-looking data. **None of this is visible to a single-user test**, which is why the assertion is a sequence in one process — request A, then B, then A again inside the margin — and why each clause is load-bearing: without the credential check a shared cache passes; without the call count a cache keyed on the request id, safe but useless, passes; without the tag check a cache that re-assumes with the previous caller's tags passes. It is measured on the access key the **client constructor** recorded, because reading it back out of the cache measures the cache rather than the thing a route can call.

**The expiry margin is the life of one REQUEST, derived from the function's own timeout** — the schedulable unit — with the longest downstream call subsumed by the same bound rather than omitted from it. No clock-skew literal is invented on top: the single forced re-assume **is** that allowance. The retry runs on a **new** client, because boto3 binds credentials at construction, so a proxy that re-assumes and re-calls the object it already holds fails again — fail-closed, but decorative, and green.

**And a PRESIGNED URL is not a request, so it does not take that margin.** The schedulable unit for
a URL is the window it is signed for, which outlives the invocation that minted it — so `_usable`'s
one-request margin, applied to presigning, hands back any session with half a minute left and the
clamp signs for whatever remains. The window a user gets is then a draw from roughly the whole hour
rather than the number the route asked for: on a uniform model, **about a quarter of mints land
under 900 s and about one in a hundred under a minute.** `signing_client` therefore takes
`covering=` and forces a fresh session when the cached one cannot span it. One `AssumeRole`, tens of
milliseconds, on the minority of mints that draw short.

**It is not visible in a passing test, which is why it needed one of its own.** Every offline
assertion about the clamp is satisfied by a short window, because a short window *is* correctly
clamped — the clamp and the draw are different questions and only the clamp had a test. The clamp
stays as the last line of defence for the case the force cannot fix: an AWS ceiling shorter than the
ask, which role chaining makes real at one hour.

**What this does NOT fix.** An upload slower than the configured window still depends on S3
evaluating a presigned expiry when it **receives** the request rather than when the transfer
completes — SPEC-198 FR-005 AC8, read from AWS's documentation and unmeasured. This change makes
that check *interpretable*: a failed multi-GiB upload can now only mean the premise is false, where
before it could equally have meant a short draw. The real answer to a transfer longer than any
window is multipart, which is SPEC-216.

## The error shape: a machine code, and operator text nobody renders (SPEC-197)

A failure body is `{"error": {code, requestId, detail?}}` — the only wrapped shape in the API, since
a success body is the payload itself and a `{data: …}` level is one every ported service would strip
forever. `code` is drawn from a closed enum; `detail` is operator text authored at the raise site,
read in a devtools panel and in `logs/`, and **rendered nowhere**.

The browser chooses every user-facing sentence from the code, through `lib/errorMessages.ts`. An API
that returned a sentence for the SPA to display would reverse that quietly, because the sentence
would look fine in every screenshot.

**The trap is a rule written to uphold it.** `CODE_RULES` contains eight `passthrough` rules whose
whole behaviour is *return the service's message unchanged*. If the API ever returned one of those
codes, server text would reach a user through one of the rules protecting against exactly that. The
guard intersects `API_ERROR_CODES` (generated from the Python contract) with `PASSTHROUGH_CODES`
(computed from the rules) — **two derived sets, never two lists** — and covers the two codes the
client mints as a third. Verified by adding a passthrough code to the Python contract and watching
it redden.

**An unrecognised code resolves to the generic sentence, and that is the deploy-skew case rather
than a fallback nobody meets:** the API deploys before the SPA image, so an old bundle *will* meet a
new code. A missing rule is not a crash — it is the generic wording, which is right for an unknown
code and wrong for a known one, and only a guard tells them apart.

One collision surfaced on the way: `InvalidRequest` is both an API code and a code two browser
services already mint. Both resolve to the same generic sentence, so nothing changed for them — but
a **code** rule wins over an engine-message **match** rule, so a fixture sending `InvalidRequest`
with Athena text stopped reaching the column-name hint. The fixture now sends Athena's real
`InvalidRequestException`, which carries no code rule.

## The contract is declared in Python and the TypeScript is generated (SPEC-197)

Two hand-edited copies rot. A contract test both sides hand-wrote against each other compares a copy
of the answer with itself, and it agrees most confidently exactly when both were written by the same
session on the same afternoon. So `lambdas/api/apicommon/contract.py` is the single declaration and
`scripts/generate_api_contract.py` emits the TypeScript.

Python is the source rather than TypeScript because the runtime request validator and the wire types
must read **one** declaration — a validator written against a separate schema is a third copy, and
the third copy is the one nobody regenerates. The generator and the validator consume the same
`walk` of the same annotation, asserted structurally: an AST check that the generator defines no
walker of its own.

**Two gates.** CI regenerates and refuses a diff on the generated file, which catches both
directions — a Python type edited without regenerating, and the generated TypeScript hand-edited.
`npm run build` is the second: a field removed or renamed regenerates into a changed type and fails
at every call site, which no test has to be written for.

**The type vocabulary is closed and the emitter never falls back.** `str`, `int`, `float`, `bool`,
`None`, `list[X]`, `X | None`, `Literal` over strings, references to declared `TypedDict`s, and
optional keys in both spellings. Anything else **raises**. This is the requirement that can silently
succeed: a fallback type agrees with every possible value, so the day the emitter meets a shape it
cannot express is the day the contract stops being checked and nothing goes red. It never emits
`unknown` and never emits `any`.

## `apiRequest` retries nothing, and idempotency is declared per route (SPEC-197)

Zero retries under every condition — a timeout, a 429, a 503, a network failure — asserted as a
`fetch` call count of exactly one. Retrying a 429 amplifies the condition that caused it.

**Exactly one exception, and deleting it signs every user out at the hour mark with a green suite:**
a 401 triggers one forced token refresh and one retry, and no more. That refresh is the browser's
only token-refresh path. The test that says so is a count — a 401-then-200 sequence issues exactly
two requests, and a 401-then-401 sequence issues exactly two as well.

Whether a call may be retried *above* the client is a property of the **route**, declared in the
contract and never derived from the method: a `POST` that resolves a free name is a read, and a `PUT`
that appends is not. `apiRetryPolicy(routeId)` is the only source of a TanStack Query `retry` value
for an API-backed hook, and the test enumerates the generated table so a route added later is covered
without the test being edited. The reason it is a rule rather than a habit: a failing apply in the
Data Explorer once issued **two** `StartQueryExecution` calls 1.1 s apart, because `retry: 1` had been
set on something that looked like a read and was a billed, stateful action.

**The client's timeout sits ABOVE the function's**, so the server always gives up first and a client
abort always means a genuinely dead connection. A shorter client timeout aborts requests the server
then completes, which for a write is a mutation the user believes failed. The ordering is created by
the function's 29 s against the integration's 30 s ceiling — not, as the spec's constant name
suggested, by a 29-second gateway timeout that does not exist.

## Cognito tokens are held per TAB, not per browser (2026-08-27)

Amplify's default token store is `localStorage`, so an ID token survived a browser restart and was
readable by anything running on the origin. `configureAmplify` now hands the provider the
tab-scoped store instead.

**The cost is deliberate and user-visible**, which is why it is a decision rather than a tidy-up:
there is no "stay signed in" any more, a second tab signs in again rather than inheriting the
first one's session, and a link opened in a new tab lands on the Hosted UI first. Nothing in
`helpContent.ts` promised otherwise, so no guide became untrue — but a later spec adding one must
know this is the behaviour.

**Set AFTER `Amplify.configure`, never before**: the provider resolves the pool it was configured
with, and a store installed on an unconfigured provider is discarded. Both halves are guarded, and
both guards were verified by planting the mistake.

**It touches sign-in, which a warm session cannot exercise.** The offline tests assert which store
the provider is given; they cannot drive a real authorization-code round trip, and Amplify keeps
the OAuth `state` and PKCE verifier in its own store — so the two now live in different stores.
Expected to be fine, not observed. Recorded in `owed.md`, along with the SPEC-192 fresh-sign-in
check this **re-invalidates**.

Requested by Andrew alongside SPEC-197 and shipped as its own commit, so it can be reverted without
the port.

## A presigned URL is a bearer token (SPEC-198)

AWS's own words: presigned URLs "are bearer tokens that grant access to those who possess them". The
capability **is** the URL, so everything true of a credential is true of it.

**Minted only after exactly the authorization the direct call would have had** — the same space
resolution from claims, the same membership check, the same protected-location rules — and signed
with the **caller's own assumed session**, never the API's execution role. A test asserts the
signing credentials come from `user_client`; the wrong one mints a working URL against the wrong
identity, which is the isolation question turned inside out.

**It appears in no emitted record.** The span carries `route_id`, the space kind and the key's
**length** — never the URL and never the query string. The obvious wrong implementation is a debug
field stamping the response body, and it would look like good telemetry. The `error.stack` scrub
covers these routes, and the assertion is a sentinel in an exception **message** or a log **field**,
not a URL-shaped local: `traceback.format_exception` renders each frame's source line and never its
locals, so a test that binds a URL to a local and raises can never fail whatever the code does. The
live exposure is this repo's own code interpolating a signed URL into a message.

**The lifetime is clamped to the SIGNING SESSION's remaining life, read from the credential that
signed.** Not from `DurationSeconds`: the two agree today and will not later — `transition_plan.md`
§3.9 signs from Access-Grants-vended credentials in the target environment, whose maximum differs,
and a clamp computed as `min(900, DURATION_SECONDS)` passes every test here and mints URLs that
outlive their own signature there. The trap that cost this an implementation: `user_client()` assumes
internally, so a clamp that assumes *again* is a **second read**, and the cache refuses a session
with under ~30s left — read 2 returns a fresh hour-long session while read 1's near-dead one signed
the URL. Measured: signed by a credential with 20 seconds left, `expiresAt` came back 15 minutes
out. `identity.py` therefore exposes **one accessor returning the client and the credentials backing
it**.

**The expiry is evaluated when S3 RECEIVES the request, not when the transfer completes.** That is
the premise the whole single-`PUT` design rests on, it is read from AWS's documentation rather than
measured, and it is recorded as **owed** — if it were false, every large upload would fail at the
tail with an opaque 403 after the user had waited.

## The dev-unauth path is retired (SPEC-198, supersedes SPEC-002)

`VITE_S3_DEV_UNAUTH=true` browsed a read-only public test bucket with **unsigned** S3 requests, so a
developer needed no AWS account. It worked by having the browser call S3 directly, which is the
thing this arc removes: after the port there is no unsigned call left for it to make.

Gone with it: `lib/s3Client.ts` (and `devS3Client`, `getS3Client`, `CHECKSUM_OPTS`,
`REQUEST_HANDLER`), `lib/s3Errors.ts` (its last caller went with them), `ProtectedLayout`'s auth-gate
bypass, `FilesPage`'s read-only target, and five variables — `VITE_S3_DEV_UNAUTH`,
`VITE_S3_BUCKET_NAME`, `VITE_S3_ROOT_PREFIX`, `VITE_AWS_ACCESS_KEY_ID`,
`VITE_AWS_SECRET_ACCESS_KEY`.

**The guard that protected it was deleted only once the grep was clean**, and in that order for a
reason: `support.test.ts`'s block was two layers, and the load-bearing one globbed every non-test
module and asserted **set equality** between the modules naming the flag and its three-site registry.
Removing two sites and leaving one turns that red. It was deleted because its **subject** is gone,
not because it was weak — and the `runtimeConfig` allowlist that named five modules permitted to read
`import.meta.env.VITE_` is now one, `lib/env.ts`, which is the remaining fallback table.

**Local development is now: point the SPA at an API.** `.env.example` and the README say so, rather
than leaving the story implied by the absence of the old one. Presigned uploads and downloads redeem
from `http://localhost:5173`, which both buckets' CORS allowlists still name — and that entry stays
for exactly this reason, not because of the path this entry retires.

## The API makes exactly ONE AWS call per request, and every loop stays in the browser (SPEC-199)

> **The heading's literal count was already false when it was written, and is kept because every
> link and ADR row points at it (2026-09-01).** `objects.move` heads, copies and deletes on one
> request, and SPEC-216's multipart create heads then creates. **What this entry actually settles,
> and what `test_api_thinness.py` enforces, is the SHAPE:** no route sleeps, waits, paginates or
> walks a continuation token, and no route's call count grows with the user's data. A small fixed
> number is fine; free-name's is bounded rather than fixed, at `FREE_NAME_MAX_ATTEMPTS`. Read the
> count as "not a loop", not as "not two".

The shape a reader reaches for is *"the API waits for the query"*, and it is wrong twice over. **The
ceiling is computed, not asserted:** an HTTP API's integration timeout is 30,000 ms and is **not
raisable**, so a five-minute query is 10× the budget — the rejected design does not fail at the
margin, it fails always — and it would hold a Lambda open for the duration of a user's query while
doing so. The slowest route on this surface is `athena.results` at a 1000-row page, sub-second.

So the four loops the catalog rides on stayed exactly where they were, unchanged apart from what they
call: `useQueryExecution`'s poll (1.5 s, 5-minute ceiling), `runStatementToCompletion`'s (400 ms × 90),
`useQueryResults`' `NextToken` paging, and `useResultRowCount`'s background walk. `listTables` walks
the API's `nextToken` inside the service, so `useSchema` still gets every table from one call.

> **Changed by SPEC-234:** `useQueryExecution`'s ceiling is now 30 minutes, and it is a verdict on a
> read after it rather than a stop on the clock. Full entry: `browser.md`, *A long query settles at
> the ceiling, judged on a read after it, and says where its results go*.

**The counting rule is the part that is easy to get wrong.** "One botocore call per request" is
unsatisfiable on a cold invocation and satisfiable on the next, because the per-container session
cache makes `sts:AssumeRole` fire on some invocations and not others. The assertion is therefore on
**the service client the route holds** — the one returned by `user_client('athena'|'glue', …)` — and
says nothing about STS. The distinguishing case is `catalog.tables.list`: a server-side `NextToken`
walk would satisfy every behavioural test and quietly make the API a loop over a user-controlled
collection.

**The accepted consequence is stated rather than mitigated.** A five-minute query is ~200 status
requests and a million-row walk ~1000 results requests — the same counts as before, one extra hop
each. They now meet API Gateway account throttling, `apiRequest` never retries a 429, and the walk
already swallows a failed page into `total: null`. No new mechanism was added.

**The one exception in this arc is SPEC-198's free-name route**, and its justification — 999
sequential probes for one gesture — does not generalise to a 1.5-second poll. The sweep that holds
this reads code, not prose: no `time.sleep`, no botocore waiter, no paginator, no `while` over a
continuation token, plant-verified in both directions.

## A route may carry PATH parameters, and a value that is not one segment is refused in the browser (SPEC-199)

Four of the six catalog routes name a resource in the path, and the transport could not address one —
`route_for` was a string comparison and `apiRequest` used the generated path verbatim. SPEC-198
sidestepped it by flattening identifiers into the query string; this declares templates, and
SPEC-200/201 inherit the mechanism.

**API Gateway hands the function a percent-decoded path**, measured against the deployed API rather
than assumed (`GET /health%7A` answers 200 — it matched `/healthz`; `GET /healthz%20` answers 401). So
the browser encodes each segment and the server never unquotes.

**A parameter must be ONE segment, and two unrelated mechanisms at two different layers turn a value
into extra structure:** `a/b` survives `encodeURIComponent` as `%2F`, reaches the wire intact and is
decoded by the gateway; `.` and `..` are not encoded at all and never reach the wire, because the URL
parser collapses dot segments when `fetch` reads the string. Either one addresses a template the
caller did not name — `athena.status` asked for `abc/results`, or for `.`, arrives as
`athena.results`. Both answer **200, with a body of the wrong shape, typed as the right one**; a 404
would have been survivable. A first version of the guard refused only the slash, which is the same
defect it was written to prevent.

**The refusal is client-side, and that is about where the check can work rather than about safety.**
The server cannot tell such a path from one a caller legitimately typed — by the time it matches, the
separator is a separator. Both siblings sit on the user plane under the same assumed identity, so a
caller reaches nothing a direct request would not give them. Whether `rawPath` preserves the encoding
and would allow the same check server-side is **not measured**, and the comment says so rather than
implying it was ruled out. It mints its own `UnsendableParameter` code, deliberately not the server's
`InvalidRequest`: reusing that would make a refusal of ours indistinguishable from the API's own, in
the one case where the difference is the whole diagnosis.

**A missing parameter is a COMPILE error, through a conditional rest tuple** rather than an optional
field. As an optional field the omission compiles and the literal `/v1/queries/{queryExecutionId}/stop`
goes on the wire — where the gateway decodes the braces, the matcher **matches**, and Athena is handed
`{queryExecutionId}` as an execution id. A generic wrapper must forward `...args` rather than take an
options object: with the route id still a type variable, TypeScript cannot pick an arm of the
conditional. **Both silent failures of a templated matcher are refused at declaration time** — a
segment carrying a brace that is not a well-formed placeholder (which would 404 every caller while
every type check stayed green, and silently publish no parameters) and two overlapping templates
(which would resolve by declaration order). There is deliberately no literal-beats-template precedence
rule: it would be a second thing to reason about at every future declaration and only ever fires in
the case the refusal makes unreachable.

## The identity block is nested, and it stays nested (SPEC-200)

Every control-plane message the API sends carries one extra top-level key, `identity`, holding
`{actor, delegated_by, assurance}` — the verified username, `null`, and the literal `interactive`.

**Nesting is forced, not stylistic.** On table-share, file-send, archive and file-ops the top-level
field named `actor` ~~**is the raw ID token today**~~ **— superseded by SPEC-201:** was the raw ID
token when this was decided, and now holds one only in a message enqueued before the API stopped
sending one. A flat verified `actor` would have overwritten the very field those four planes then
verified, which is precisely the ordering failure the two-spec rollout existed to avoid. It stays
nested after the cutover: SPEC-201 took the token off the wire rather than moving the block into its
place, so there is no second migration and no window in which one plane's `actor` is a username
while another's is still a JWT.

`delegated_by` is **present rather than omitted** — an absent key and a null key are different to a
strict parser, and the planes are written to refuse the absent one. `assurance` names the assurance
**kind**, not the mechanism: `verified-id-token` would need renaming the day the provider changes or a
machine-facing caller mints a delegated one.

**Nothing in the block is secret, and that is load-bearing.** The dead-letter drain's redaction
replaces TOP-LEVEL keys only, so anything nested here reaches CloudWatch verbatim when a message
dead-letters. A key set is asserted rather than the absence of a token inspected by eye.

## The browser's queue grants come off with the switchover, not with the trust flip (SPEC-200)

The rollout is two specs. SPEC-200 has the API write **both** the token and the identity block,
changes no plane's trust, and leaves every `verified_username` call working on the field it already
reads. SPEC-201 flips the planes onto `identity.actor` and only then — as its own second step, after
that flip is deployed — stops the token being sent. Collapsing either boundary fails all eight planes
closed on the first request after deploy.

**The eight `sqs:SendMessage` grants come off in SPEC-200, and that ordering is separate from the
trust flip.** The Identity Pool survived until SPEC-202 — it is retired now — so at the moment
`identity.actor` became authoritative, any signed-in tab that could still write a queue could have
named any actor. "201 before the grant removal" would have been a real impersonation window rather
than a theoretical one.

The recovery consequence was worth writing down and the revert it protected has since expired: the
eight `VITE_*_QUEUE_URL` repository variables were left in place until SPEC-202, because a revert of
the switchover needed them and re-reading eight values from `tofu output` was the only step of that
recovery which was not `git revert`. SPEC-202 removed the credentials that revert would have used,
so recovery from here is forward. The variables themselves are still **set** in the repository and
read by nothing — their deletion is one line of SPEC-215's owed ledger entry, not something this
arc closed.

## Table-share's dedup id is keyed on the verified actor, not the token (SPEC-200)

This is the one FIFO derivation the port deliberately changed; the other nine are reproduced
byte-for-byte against golden vectors captured from the browser before it was deleted.

The browser hashed `[idToken, source, tableName, sortedRecipients, minuteBucket]`. Table-share is the
only plane with **no `requestId`**, so that digest is the entire double-submit guard — and because the
token was an input, two submits a minute apart with a token refresh between them produced two
different digests and therefore **two shares**. The guard lapsed silently, and it would have stopped
working entirely once the token went away.

It now hashes the verified actor in position 0. Two properties evidence the change rather than assert
it: the browser's own digest **moves** across a refresh where the new one does not, and two different
users submitting the identical share in the same minute still get **different** ids — dropping the
actor from the canonical form entirely, which is the obvious simplification, would collapse one user's
share into another's and deliver nothing.

The canonical form is pinned field by field, because the vector replay cannot cover the one derivation
whose whole point is that it no longer matches. `ensure_ascii` is off so a non-ASCII space name
digests the way `JSON.stringify` would — a divergence no ASCII fixture can show.

## The identity grant is the only path to a request queue; no resource policy (SPEC-200)

There is no `aws_sqs_queue_policy` anywhere in `infra/`, and SPEC-200 adds none. "Only the API may
write" is achieved by adding one grant and removing eight.

The precedent for a resource-side allowlist is the user-space bucket policy, whose own recorded
failure mode is that it is hand-maintained and a missing plane half-works. What stands in its place is
an **enumerated** sweep — the portal-role templates are globbed from the filesystem and asserted to
carry no `sqs:SendMessage` — because a hand-kept list is exactly what would miss the ninth plane.

**Do NOT add a blanket `Deny` with a `StringNotEquals` on the API's role ARN.** It is the shape a
reader reaches for, and it silences every outcome notification this product sends: the notifications
request queue has eight writers and SPEC-200 removes exactly one. The other seven are execution roles
that notify, plus the dead-letter drain. The shared-spaces producer runs with `ResultPath: null` and a
`Catch` leading onward so it deliberately cannot fail its run, and the other planes notify
best-effort — so archives, shares and sends would all complete and no user would ever be told.

## The planes trust a body field because of who may WRITE it, not because of cryptography (SPEC-201)

Eight control planes each verified a Cognito ID token out of the queue message. That was correct
while the browser was the sender: the queue was writable by every signed-in user's credentials, so
the body proved nothing and only a signature could say who was asking.

SPEC-200 changed the sender. The API verifies the bearer at the edge, writes a nested `identity`
block carrying the verified actor, and — because SPEC-200 FR-008 also removed the browser's
`sqs:SendMessage` grants — is the only principal that may write those queues. From that point the
per-plane verification is a second answer to a question already answered, and it is the last reason
a raw JWT travels through eight queues, sits in eight state-machine execution inputs, and lands in
CloudWatch whenever a message dead-letters.

**The provenance is a grant, and it is enumerated rather than asserted:** the API's execution role
holds `sqs:SendMessage` on ~~exactly the eight request-queue ARNs~~ **— superseded by SPEC-211 and
SPEC-221:** every request-queue ARN, feedback's (SPEC-211) and results-conversion's (SPEC-221)
having joined the eight, from a list whose length the module pins, and a `.tftpl` sweep derived
from the modules on the filesystem fails if any policy attached to the ~~browser's role~~ **—
superseded by SPEC-202:** portal role, which the browser no longer holds, grants it again.
If that grant is ever widened, no amount of verification in the plane would help — a principal that
can write the queue can write the block.

**Dropping a VERIFICATION is not dropping an AUTHORIZATION, and the distinction is the whole
spec.** The token answered "is this really alice?"; membership, ownership, containment, a space's
active status and the recipient checks answer "may alice do this?". The API answers the first.
Nothing but the plane answers the second, and `authorize` / `authorize_source` have **zero diff** —
their inputs always took a plain username, and only where that string comes from changed.

**Do NOT add a queue resource policy** to "make it structural". On the notifications queue it is
destructive: that queue has eight writers, of which SPEC-200 removes one; the other seven are
execution roles that notify. A blanket `Deny` denies all of them and presents as nothing at all —
every plane notifies best-effort, so archives, shares and sends would complete and users would
simply never be told. Enumerating the seven exceptions is the hand-maintained allowlist whose
failure mode SPEC-164 FR-006 already records, arriving before the policy shipped. SPEC-200 FR-008
AC5 settled this for the arc.

**The reader may not verify, and that prohibition is the interesting half.** `cpcommon.actor`
imports neither `jwt` nor `cpcommon.auth`, makes no network call and reads no environment variable,
asserted by an import sweep. A reader that could fall back to verifying looks like defence in depth
and is the opposite: a second answer to a settled question, in a module whose premise is that it was
settled elsewhere. The fleet had five such readers and they had drifted; the cost was never that any
one was wrong, it was that nobody could say which one a request had used.

**The flat top-level `actor` is never consulted.** On four planes that field holds the raw token in
any message enqueued before the API stopped sending one, and a raw JWT and a username are both
non-empty strings — so a reader shaped "take the block, fall back to the field" passes every
well-formed fixture ever written and builds an S3 prefix, a Glue database name and a notification
recipient out of a 900-character token on the first message carrying the token and no block. The
actor is checked against `config.CATALOG_IDENTIFIER_RE` (with `fullmatch`, since `$` also matches
before a trailing newline), which is what makes the JWT case *fail* rather than merely look odd.
Measured: mutating that check to a truthiness test reddens seven cases in the reader's own suite and
leaves **every plane's suite green**.

## `assurance` fails closed on an unknown value, including an absent one (SPEC-201)

`identity.assurance` says how strongly the API established the actor, and today exactly one value is
minted. A plane presented with anything else — including the reserved-but-unminted `delegated`, an
empty string, a non-string, or **no value at all** — refuses the message terminally under a distinct
reason code, `unsupported_assurance`. It does not downgrade, ignore, or treat an unrecognised value
as the default. `identity.delegated_by` must be *present* and null, because SPEC-200 stamps an
explicit null and an absent key is therefore a malformed block.

Nothing mints anything but `interactive`, so the refusal is unreachable in production — **and that
is its purpose.** When a later arc mints a machine principal, every plane refuses it until that
plane is deliberately widened, rather than silently treating a service as a person at a keyboard.
The absent case is refused for the same reason: a missing assurance reading as `interactive` makes
the field's fail-closed property decorative, and an omitted field is the shape most likely to arrive
first.

The set is defined **once**, in `cpcommon.actor`, and a sweep fails if a second module declares its
own — the widening must be one edit in one place, not whichever plane relaxed first. The literal
agrees with the one the API mints **by import**, not by restatement: two hand-written copies of one
string in two suites is exactly the shape that lets a contract disagree while both suites pass.

**Its reason code does not survive on two planes**, and that is worth knowing before relying on it.
shared-space and notifications-writer pass their own exception type, which carries a string and no
code, so the refusal is prefixed into the detail for a human reading a log line. It does **not** come
back through `errors.failure_reason`, which gates on `errorType == "TerminalError"`. A live check for
an unaccepted assurance must therefore aim at a plane taking the default exception.

## Collapsing five claim readers cost four things the spec did not list (SPEC-201)

The collapse itself was the easy part — thirteen call sites onto one reader. What it actually cost:

1. **The whole Cognito arm of `cpcommon.auth`, not the two entry points the spec named.** Once
   `verified_username` and the two domain wrappers were gone, `verify_id_token`, `_verify`,
   `_cognito_detail`, `_cognito_config` and the hard-coded claim name had no callers. Leaving
   `_cognito_config` was not the conservative option: it reads `config.USER_POOL_ID`, which this
   change removes from `_REQUIRED_VARS`, so it would have been an `AttributeError` on a path no test
   exercises. `verify_exp` went too — no caller wants a relaxation, so there is now no flag, private
   or public, that turns expiry off.
2. **`COGNITO_USER_POOL_ID` could not follow its twin.** `cpcommon/cognito.py` and
   `shared-space-common/membership.py` read it for `AdminGetUser`, which FR-004 requires to survive.
   It moved out of the fleet-wide `_REQUIRED_VARS` — that set is a contract every plane must satisfy,
   so a variable only three planes set would fail every other plane's guard — to a lazy
   `config.require` at the call site, and stays in Terraform on **shared-spaces, file-send and
   table-share** alone. The trade is real: a lazily-required variable that is missing raises
   **mid-request** rather than at cold start, which is why `test_pool_id_reaches_its_readers.py`
   pins both sets and why the live pass aimed at it deliberately.
3. **What it did NOT reach.** The SPA's `getCurrentUser().username` is the same value but never the
   claim string; `identity-pool.tf`'s principal-tag mapping retires in SPEC-202; and
   `notifications_writer`'s `create` branch never had a token to read.
4. **A correction worth keeping:** `notifications_writer` had not had "its own verification path"
   since SPEC-156 FR-004. `transition_plan.md` §6.1 said it did, and a build session hunting for a
   second `jwt.decode` would not have found one. It was a claim *reader*, which is why the count of
   five still held.

**`notifications_writer`'s branch is the one that must not be simplified.** `trusted_actor` replaces
the reader on the `USER_ACTIONS` arm **only**. The `create` arm is the trusted-producer path —
written by the control-plane execution roles, carrying a body `username` with no actor and no token —
and hoisting the reader above the branch is the obvious tidy that a "one reader, every call site"
sweep pushes toward. It refuses **every notification the fleet produces**, and it does so silently:
the producers notify best-effort, so archives and shares complete and users are simply never told.
Planted during the build, six tests redden.

## The trust flip is two deploys, and the second cannot be rolled back (SPEC-201)

Step one: the eight consumers require `identity` and stop calling `cpcommon.auth`, while the API is
**still writing the token beside the block**. Step two, only once step one is deployed and
exercised: the API stops writing it. Collapsing them into one merge fails all eight planes closed on
the first request after deploy — and **both suites still pass**, because the planes' tests are
written against `identity` and the API's against its own output, and nothing in either sees the
other's envelope.

**Rollback has a shape rather than a direction, and step one's is the inverse of the forward
order.** Reverting step one's Lambdas restores token verification while the producer is still
sending a token, so the revert is clean — *but only if the infra is reverted first*. The env comes
out with the code, so redeploying the previous zips alone restores a verifier reading
`config.USER_POOL_ID`, which is gone: a `RuntimeError` on the first request of every plane, worse
than what is being rolled back. **Infra, then code.** After step two there is no backward path at
all; recovery is forward.

**The window between step one's deploy and the queue draining is real and its outcome is
deliberate.** A message the API enqueued before step one carries the block beside the token and
is served as usual. A pre-cutover message — the browser's envelope, a flat token and no block — is
refused `unauthorized` with **no notification**: there is no trustworthy recipient and nothing in
the message may be believed. It does **not** dead-letter: every plane's Pipe is `FIRE_AND_FORGET`, so
`StartExecution` succeeds, the Pipe deletes the message, and the refusal happens inside the
execution. A request DLQ only ever receives what the Pipe could not *deliver*. The spec asked for a
drain record for this case; there cannot be one, and looking for it reads as the drain being broken.

**The plane allowed-field sets are NOT tightened**, and this is the easy thing to get wrong while
making everything else green. Removing the legacy flat token field turns a pre-cutover message into
`malformed_event` before the reader ever sees it — a different reason code, a different notification
decision, and a criterion that silently stops testing what it names. The sets are pinned **per
plane**; a fleet-level "at least one still admits it" passes while any single plane regresses.

## The membership index is an authorization input, where the username directory is not (SPEC-203)

**The registry cannot answer "which spaces is this user in" cheaply.** It is one object per space,
keyed by space name, so the question costs a full listing plus a read per space — on the
credential-minting path, on every request. `s3://{admin-bucket}/memberships/{username}.json` answers
it in one `GetObject`, written under ETag CAS by the six verbs that move a Cognito membership slot
— **amended 2026-09-15: beside the Cognito slot rather than beside the roster fan-out, so a GRANT
lands before the registry commit and a REVOCATION after it** ([the group id
entry](control-planes.md#a-group-id-orders-the-starts-not-the-runs-and-what-overlap-costs-on-each-plane-control-plane-wide)).

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
  ([control-planes](control-planes.md#a-spaces-name-is-held-to-the-catalog-rule-where-it-is-chosen-and-the-refusal-is-create-only-2026-09-22)),
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

## The role's Lake Formation grants and the principal tag are ONE mechanism (2026-09-01)

**Isolation between shared spaces is the intersection of a grant in Python and a condition in HCL,
and each half reads as complete on its own.** `shared-space-create` grants Lake Formation `Database`
and `Table` permissions to `config.PORTAL_ROLE_ARN` — the **shared** portal role — once per space,
naming no member. Every portal user assumes that role, so that grant alone entitles everyone to
everything. What narrows it lives in `portal-role-shared-space.json.tftpl`, where every Glue database
and table ARN is scoped by `$${aws:PrincipalTag/shared_space_k}`, so the ARNs resolve only to the
spaces the caller's session tags name.

**Neither artefact mentions the other, and they are two trees apart.** A reader standing in either
one sees a complete-looking mechanism. That is why this is a register entry and a test rather than a
comment: `lambdas/test_shared_space_isolation_coupling.py` fails when create stops granting to the
portal role, when a Glue resource in that statement loses its tag scoping, or when any portal-role
template gains `glue:DeleteDatabase` or `glue:UpdateDatabase`.

**The two failure directions, which matter because the edit looks like housekeeping.** Retire the
principal tags and leave the role-level grants: every portal user holds catalog access to every
shared space. Revoke the grants first: every member is locked out. The ordering that avoids both is
transition work — `transition_plan.md` §3.11 — and the trigger for the union is the **policy
rewrite**, not the tags going quiet: if tags simply stop being stamped and the statement is
untouched, the ARNs resolve to nothing and the outcome is a lockout.

**A third fact falls out of the same intersection, and it is a live security property rather than a
transition one.** The Lake Formation grant carries `ALTER` and `DROP` on the Database. The role
cannot use them because **no** portal-role template grants `glue:DeleteDatabase` or
`glue:UpdateDatabase` — the shared-space template names ten Glue actions and the analytics one
eleven, and neither names either of those two. So a member cannot destroy a shared space's catalog today, and the reason is an
omission in IAM rather than anything in the grant. **Adding either action is not a widening; it is
the removal of the guard**, and it needs no other change to become reachable by any member of any
space. The same reasoning is why a future per-member grant must be the **intersection** — Database:
`DESCRIBE`, `CREATE_TABLE` — and not a copy of the role's constants.

## The Identity Pool is retired, and no one's sign-in changed (SPEC-202)

**The conflation this entry exists to prevent.** The Cognito **User Pool** authenticates people:
Managed Login v2, the Hosted UI round trip, Amplify in the tab, the ID token. The Cognito **Identity
Pool** did something else entirely — it exchanged that ID token for temporary AWS credentials so the
browser could call AWS. SPEC-202 deleted the second and touched the first not at all. A reader who
reads "Cognito is retired" into this will go looking for a sign-in change that does not exist.

**What actually came out.** The pool itself, its principal-tag map, its role attachment, the portal
role's `AssumeRoleWithWebIdentity` trust statement (two statements to one — what remains admits the
API's execution role), `cognitoIdentityPoolId` from the runtime document, and the browser's last two
credential modules. `lib/awsCredentials.ts` became `lib/idToken.ts` with one export, `getIdToken`:
named for a JWT rather than for credentials **deliberately**, because there are no AWS credentials
in the browser to name and a module called `awsCredentials` invites putting some back.
`credentialRetry.ts` went with it — the expired-credential retry that used to wrap every AWS call is
a server-side re-assume now.

**The load-bearing negative could not be observed until the pool was gone, which is why the order
was not a preference.** `lib/amplify.ts` configures `identityPoolId` whenever the key is present, and
every `fetchAuthSession()` then vends pool credentials — including the one `getIdToken` makes on
every API call. So *"the browser makes no AWS call other than presigned S3 bytes"* reads as false
while the pool exists no matter how much code has been deleted, and running that check before the
retirement and calling it a pass is the failure the spec was ordered around. Measured after, in
Chromium: four hosts blocked by the CSP (`cognito-identity.`, `athena.`, `glue.`, `sqs.`), two
allowed and required (`cognito-idp.`, the Hosted UI host).

**A retirement is proved by an absence, and an absence needs a positive form.** Two ids were captured
**before** the merges, because the Terraform outputs that name them do not survive:
`describe-identity-pool` on the recorded pool id returns `ResourceNotFoundException`, `get-role`
returns exactly one trust statement. "Gone from the plan" is not the same claim.

**What did not change is the part worth asserting.** FR-010 re-ran SPEC-196's IAM simulation against
the deployed roles after the retirement, row for row: `alice/` allowed, `bob/` implicit-deny, every
denial paired with an allowed control on the same bucket so an ungranted action is distinguishable
from a mistyped ARN. **No row moved.** The retired browser grants stayed retired. The SPA task role
was asserted by **absence** — no attached and no inline policies — rather than by simulation,
because a role with no policies returns `implicitDeny` for everything with no control available, and
an unpaired `implicitDeny` presented as a pass is exactly what the rest of that check exists to
avoid.

## An execution id is a claim, and every route that names one proves it first (SPEC-232)

Athena authorizes `GetQueryExecution`, `GetQueryResults` and `StopQueryExecution` by
**workgroup**, and there is one, so the per-user role reaches any execution whose id it holds. SPEC-199 recorded that as an exposure owed a spec, on the premise that
closing it needs an execution→owner record that does not exist. **The premise was false.** Every
query the API starts writes under the caller's own `user_results_prefix`, and Athena records that
location on the execution. Two measurements back that. Through the API, SELECT, SHOW, EXPLAIN,
DESCRIBE, the table and view DDL (create, show-create, drop) and CTAS all record it under the prefix
they were given. From the operator account, a `SELECT 1` already carries it while QUEUED, and an
UNLOAD records it under its prefix, not under its `TO`. Results-conversion already proved ownership
from it (SPEC-221). The location IS the record.

**The proof is one predicate and one helper.** `cpcommon.results.owned_results_key` (the prefix,
plus no dot segment) is shared by results-conversion and the API. `_owned_execution` wraps it with
one `GetQueryExecution` on the route's own client, and status, results, stop and the row count call it before any
other Athena call; a later route that names an execution is held to the same by the guard. An unknown id and a foreign execution get **one 404 body**. The unknown
case is Athena's `InvalidRequestException`, which a malformed id raises too. `detail` reaches the
body, so there is exactly one string, and the span records which case it was in
`execution_ownership`, because a refusal's reason belongs in the log.

**Results takes the proof even though S3 guards its rows.** Measured before the change: a finished
foreign execution answered 400, like an unknown id, because Athena wraps the S3 denial. But a
foreign execution still RUNNING answered 409, which told a holder of the id that its owner's query
was still going. That is why ownership is checked before state, on every route. It also means the
ownership of results no longer rests on the S3 policy, which the client transition moves.

**"The caller's" means written into the caller's own results folder, not started by the caller.** A
plane's statement run into a user's personal space passes that user's proof, and the harm stays
inside her own space. A shared space's plane statements write to the shared-space bucket, which the
proof never accepts.

**Two consequences are stated rather than mitigated.** First, a workgroup that ENFORCES its own
result location makes every execution route answer 404 for every user's own queries. The proof has
to move with the location, in `cpcommon.results`. Second, the same answer holds only within the
portal workgroup. An id from AWS's `primary` workgroup gets IAM's 403, because the per-user role has
no grant there, and mapping that 403 to 404 would make a broken grant read as "not found" on every
poll.

**Do NOT** build an execution-to-owner table, give the guard an exemption, or fold `AccessDenied`
into `NotFound`. The guard derives its population from the contract, and a placeholder spelled
other than `{queryExecutionId}` fails it.
