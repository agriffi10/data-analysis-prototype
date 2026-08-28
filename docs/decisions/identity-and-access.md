# Identity, access and the name that ties them together

Part of the **Key Decisions register** — [`INDEX.md`](INDEX.md) is the router, and `CLAUDE.md`
carries the one-line digest of each entry. This file holds the reasoning, the constraints and the
explicit "do NOT build" fences for one area. **Read the entry you need, not the file.**

## Contents

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

## Auth

Cognito User Pool → Identity Pool (ABAC) stamps the `username` principal tag from the verified token claim **server-side** (unspoofable; never client-asserted). One shared IAM role for all users; per-user isolation via `${aws:PrincipalTag/username}`. (SPEC-011; reversed the earlier "no Identity Pool".)

## Hosted UI = Managed Login v2

The domain runs Cognito **Managed Login** (`managed_login_version = 2`); the classic Hosted UI didn't complete the OAuth redirect after self-service signup confirmation (user landed confirmed-but-signed-out). Sign-in and signup both route through Amplify `signInWithRedirect`. The branding resource is provider-6.x-only (repo pins `~> 5.0`), so CI ensures Cognito's default branding post-apply (`deploy-infra.yml`); revisit when the provider is bumped.

## No backend

Browser → AWS direct. Cognito **trigger Lambdas** are allowed (service config, not an API).

> **Superseded (2026-08-28).** This premise no longer describes the system. Privileged work moved onto
> seven **control planes** (SPEC-051 onward), and SPEC-192→197 added an **HTTP API** that verifies a
> bearer and serves routes. What survives is the boundary, not the absence: the browser still calls S3,
> Athena and Glue **directly** with scoped credentials for most reads, and the two live rules are **no
> second API** and **no new browser-side AWS SDK call on a path an API route already serves**. Full
> entries: [`control-planes.md`](control-planes.md) and the API entries below. Shape:
> `docs/architecture.md` → *The control planes* and *The API layer*.

## Usernames

Usernames are the S3 prefix = principal tag = Glue DB name → validated at signup by the pre-signup Lambda; SPEC-033 tightens to catalog-safe `^[a-z][a-z0-9_]{2,62}$`.

## Bucket 2 (shared-space)

User-created shared connections via a privileged async control plane (FIFO SQS → EventBridge Pipe → Standard Step Function) — reverses "no backend" for shared-space mutations only; access = a membership principal tag (SPEC-056). **The tag set is ten slots PER USER** — Cognito `custom:shared_space_1..10`, each holding one space name — because the Identity Pool maps a claim to exactly one single-valued tag and IAM cannot iterate a list inside a `Resource` ARN. A space's own member count is unbounded; what is capped is how many spaces one person can be in. The Step Function **orchestrates single-task verb Lambdas** (`validate-authorize → Choice(action) → create-space | add-members | remove-members | leave | delete-space`) sharing a **`shared-space-common` Lambda layer** — **not** one monolithic provisioner (SPEC-062 refactor; the 050→054 monolith is decomposed). The six Lambdas + the Step Function keep **one shared `orchestrator` role** (per-verb roles were descoped — user decision, SPEC-062 FR-005); the layer is CI-built/published (deploy-lambdas) with TF `ignore_changes=[layers]`. **Create is creator-only** (members added later via add-members from the Connections tab). Decision record: `lambdas/info/planes/shared-spaces.md`; Lambda rules: `lambdas/info/best-practices/lambdas/lambdas.md`. Do NOT build the old daily-IAM-pipeline / user-managed-keys models.

## Member join status (SPEC-073)

The owner projection carries a per-member `pending`/`active` chip. Membership stays `members: string[]` (source of truth in the registry); join status is a separate `acknowledged: string[]` list — a legacy record without it reads as all-active (back-compat). A **seventh verb `acknowledge-membership`** (member-only, idempotent, same shared `orchestrator` role) flips pending→active; the browser enqueues it once/session when a member resolves a shared space (`useAcknowledgeMembership` from `FilesPage`). Display + bookkeeping only — access is still granted at add time.

## Member roster for members (SPEC-075)

SPEC-053's member-privacy stance is **reversed** — every member sees a **read-only** roster (owner tagged + first, same `Member[]` join-status projection the owner sees), via "View members" on their Connections card. `cache.write_roster_to_all` fans the roster out to the owner + every member on add/remove/leave (best-effort per member, CAS-safe); member entries now carry `members` too. No management power for non-owners; no new IAM (orchestrator already writes every user's cache). Legacy member entries backfill on the next membership change.

## Dev-unauth path

`VITE_S3_DEV_UNAUTH=true` browses a test bucket read-only without auth (local only); production `/files` always uses the authenticated user-space bucket (SPEC-013).

## The username directory is built from S3, not Cognito (SPEC-146)

The daily builder enumerates the user-space bucket's **top-level common prefixes**. It makes **no
Cognito call**, and a test asserts the module never names `cognito` in any import, attribute or call.

**The reasoning inverts the obvious answer, which is why it is written down.** *Today* Cognito is the
complete record of who exists and S3 is not: the personal prefix is created **by the browser**, by
`ensurePrefixMarker` on the first visit to `/files` (SPEC-014, a deliberate no-backend decision), so a
confirmed user who has never opened the file browser has no prefix. On that reading Cognito wins.

*After the client transition it reverses.* `transition_plan.md` §2 item 7 settles that **sign-in
provisions nothing** — the sync pre-creates every existing user's space and database, the client's own
automation creates them for new users, and `ensurePrefixMarker` is deleted outright (§6.3). At the same
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

**What was deliberately NOT granted:** no `ListBucket` widening (the portal role's grant stays
conditioned on the caller's own prefix, so `_directory/` is invisible to the file browser and the file
browser needed no change), no `PutObject`, no `DeleteObject`. The user reads; the daily builder is the
only writer.

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
`test_recipient_space_membership_not_required` pins that any active space is a valid target — so the
suggestions cover less than the field accepts, on purpose. The cost of closing that gap is a
disclosure with **no existing equivalent**: today a non-member learns a space exists only by
colliding with its name at create time, and space names are user-chosen and often descriptive
(`acme_merger`, `q4_layoffs`). The username directory is not a precedent — a username is already the
S3 prefix, the principal tag and the Glue database name (see the entry above); a space name a user
does not belong to is disclosed nowhere. The trade was put to the user on 2026-08-05 and **declined
in favour of suggesting only what the user can already see.**

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
overrides, resolved in the browser against `VITE_ENVIRONMENT`.

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
`_config/*`, one `s3:GetObject`, no `ListBucket` widening, no write, no deploy-role change, no CORS,
CSP or bucket-policy change. This is now the precedent for a third such document.

**"It already works" is a claim about three files this spec does not touch, so all three are
asserted.** `lambdas/test_feature_flags_config.py` checks the user-space CORS rule still allows `GET`
from the app origin, that the bucket host is still in `csp_connect_src`, and that the portal role is
still on the bucket policy's hand-maintained principal allowlist — plus the deploy role's existing
`s3:*` on `${user_space_bucket_arn}/*`, which is why the publish adds no IAM. If one of these ever
fails it is a **finding to raise, not a licence to widen infra inside this spec**.

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
`Deploy App` on purpose: flipping a flag must not be a rebuild, which is why the upload carries
`Cache-Control: no-cache`.

## Gating is by REGISTRY, not per-component opt-in (SPEC-163)

**`GATED_SURFACES` names every surface every flag hides — 26 rows, keyed by flag — and one test
walks it in both states.** Not a checklist and not a convention: a row carries the surface's
ACCESSIBLE NAME, and `gatedSurfaces.test.tsx` renders each twice (flag off, flag on) and asserts
by that name. A row it cannot make disappear fails; a row with no reach-recipe fails; a recipe
with no row fails; an empty registry, or a flag with zero surfaces, fails.

**THE TABS ARE THE EASY PART, AND THAT IS THE WHOLE ARGUMENT.** "Create table from this folder"
lives on a file-browser toolbar and is a *Query* feature. "Share table" lives in the Query rail
and pushes into *Shared Workspaces*. "Check quality" is a button on a file-browser selection. A
per-component pass finds three of those and ships the fourth visible — the failure mode
`process.md` records from log-forge's SPEC-033. Adding a fifth entry point is now a registry
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

**`error.stack` carries no credential, and the mechanism is PREVENTION rather than redaction (SPEC-195, extended by SPEC-196).** `log-foundry` attaches `traceback.format_exception` to every failed span. SPEC-130 examined that and **accepted** it *for file contents*, on the reasoning that `logs/` is admin-only and a stack is diagnostic metadata a failed run needs; that reasoning was never applied to a credential, and an ID token is a bearer credential for as long as it lives. `log-foundry` 0.6.0 exposes no way to turn the capture off — `max_stack_bytes` is a ceiling, not a control — so the answer is at the boundary. **What "at the boundary" means is worth being exact about, because the phrase reads like a redactor and is not one.** The exposure is not automatic: `format_exception` renders each frame's *source line*, not its locals, and the provider library's own messages carry no token material. The live route is this repo's own code putting a credential into text. So the mechanism is an AST sweep forbidding the event, the headers, a token — and, from SPEC-196, four session-material names — from appearing in an f-string, a `%`-format, a `.format()` call or a `raise` argument, paired with a sentinel test that drives a path **genuinely raising through the span** while holding a real assumed session, so the absence is asserted where a stack actually exists. **The residual is real and recorded**: a future route that interpolates a session value despite the sweep still reaches the log store. It is in `owed.md`, not implied to be closed. **The scrub's scope is credentials and nothing wider** — a scrub written against user-data-shaped strings would contradict the 2026-07-23 decision and redden its tripwire from a spec that never argued the case. If a later `log-foundry` gains an opt-out, revisit the decision; do not delete the sweep.

## The API reads the same claims and assumes the same role with the same tag set (SPEC-196)

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
