---
type: Spec
id: SPEC-248
title: "A Name Is One User's or One Space's, and Only the Plane Writes a Membership"
description: "Closes the access gap where a signup or shared-space name could be claimed as the other's Glue database name and anyone could write any name into their own membership list, so only the plane writes memberships."
spec_status: Draft
depends_on: [SPEC-012, SPEC-051, SPEC-056, SPEC-257]
---

**Dependency notes:** SPEC-012, SPEC-051, SPEC-056, and SPEC-257, whose confidential server client
and whose test over `cognito.tf` FR-001 changes. The control-plane data-loss audit this spec was
written beside merged on 2026-09-26 (#892), so FR-003 to FR-006 read its database marker from
`main`. FR-001 and FR-002 depend on nothing else in this list, and FR-001 lands first.

**This spec builds before, between or after SPEC-262's two merges, and neither spec waits for the
other.** SPEC-262 adds a dev client and then destroys the public one. FR-001 is written against
every app client the infrastructure declares, whichever those are on the day, and its probe and its
control say which client they use in each case. A client added after FR-001 lands, the dev client
included, fails FR-001's test until it declares both lists.
## Overview

A username and a shared-space name are both used as the name of a Glue database, and there is only
one set of Glue database names. The permissions a signed-in session carries are written against
that name: "the database called whatever your username is" and "the database called whatever each
of your spaces is called". So whoever controls a name controls a catalog.

The data-loss half of this was fenced on 2026-09-26. A space named after a user no longer takes over
that user's database, and deleting a space only ever drops a database the space made.

This spec closes the access half. It has four parts:
- A person signing up must not be able to take a space's name and so reach its catalog.
- A person creating a space must not be able to name it after a user and so reach that user's
  catalog, not even for the few hundred milliseconds before the create is refused.
- Above all, no one may write a space's name or a user's name into their own account's membership
  list. The evidence below says that today anyone can, including someone who has not signed in yet
  and does it at sign-up.
- Nobody should notice any of this except a person trying one of these things. That person is
  refused with the same short sentence whichever name they collided with.

## What was measured, and what it means

A security spec rests on its premises, so each one is stated with where it was read. None was
exercised against the deployed account. P6 is measured by FR-001 before anything else is built, and
P3 by FR-006. Each was read again against `main` at `5408a55e`, after SPEC-257 merged; P5 and P6 are
rewritten for what the audit and that spec changed, and the rest stood.

- **P1. One namespace, two writers.** `post_confirmation._ensure_database(username)` and
  `create_space._ensure_database(name)` are the only `create_database` calls in `lambdas/`, and
  `infra/` declares no Glue database. Both names answer to the one catalog rule
  `^[a-z][a-z0-9_]{2,62}$`, so any username is a legal space name and the reverse.
- **P2. Lake Formation cannot tell sessions apart, so IAM is the gate.**
  - Both writers grant the **shared portal role**, not the person's own principal. (The brief for
    this spec said the opposite, and it is corrected here.)
  - The role gets `DESCRIBE`, `CREATE_TABLE`, `ALTER` and `DROP` on the database, and `SELECT`,
    `INSERT`, `DESCRIBE`, `ALTER` and `DROP` on its tables. Every user shares that role.
  - Which database a session may touch is decided by two IAM statements that write into the same
    ARN space. `GlueUserDatabaseScoped` in `portal-role-analytics.json.tftpl` puts
    `${aws:PrincipalTag/username}` into `database/<name>` and `table/<name>/*`. `SharedSpaceGlue` in
    `portal-role-shared-space.json.tftpl` does the same with each `shared_space_k` tag.
- **P3. As configured in `infra/`, a collision reaches the catalog, not the files.**
  - **What a colliding tag gives.** Both buckets are registered with
    `hybrid_access_enabled = true`, and no principal is opted in. The S3 statements are scoped per
    bucket: `username` to the user-space bucket, `shared_space_k` to the shared bucket. So a
    colliding tag gives the Glue actions of the statement it matches. That means reading every
    table's schema, location and partition values, creating tables, pointing an existing table
    somewhere else, and dropping tables. It does not give the objects.
  - **This rests on what the IaC declares, not on what the account holds.** `infra/` has no
    `aws_lakeformation_opt_in`, but an opt-in made outside Terraform would not show there. A
    comment in `infra/modules/analytics/lakeformation.tf` also describes the portal role as reading
    "by LF credential vending", which contradicts the hybrid setting. FR-006 reads the account's
    opt-ins once and records them.
  - **The condition would not survive a change.** An opt-in, or a move to Lake Formation
    enforcement (transition Phase 1 re-registers these buckets), would have Lake Formation hand
    out the credentials, and a collision would then reach the data (`docs/transition_plan.md` §3.12
    item 3).
- **P4. The reverse door is open.**
  - `pre_signup.py` makes no Glue or Cognito call. Its only AWS traffic is its own structured
    records, sent to the logs queue, and its role grants only that and CloudWatch Logs. It runs
    with a 3-second timeout and 128 MB, sized, in its own comment, for "a regex match".
  - `post_confirmation._ensure_database` treats `AlreadyExistsException` as success, then grants
    and tags.
  - So a stranger who signs up as `team_x`, where a space `team_x` exists, is stamped
    `username=team_x`. `GlueUserDatabaseScoped` then gives them that space's catalog, with no
    membership at all.
  - The same person also loses everything later. When the space is deleted, the teardown drops
    that database (its marker says it is the space's), along with every table they made there
    believing it was their own.
- **P5. The forward door leaves a window even after the audit.**
  - The create refuses a database that is not the space's own, but only inside `_ensure_database`.
    That runs **after** `membership.assign_or_find_slot` has written `custom:shared_space_k = <name>` onto the
    creator, and the rollback, `clear_slot`, is best-effort.
  - Every deployed environment runs the `claims` membership source (`MEMBERSHIP_SOURCE` is set
    nowhere in `infra/` or `.github/`). Under it, the API stamps whatever the ID token carries and
    consults no registry.
  - An ID token lasts one hour on either client. The public client sets no lifetime and takes
    Cognito's default, and the server client declares 60 minutes.
  - So a creator who refreshes their token inside the window keeps that user's catalog for an hour.
    They can reopen the window at will: the owner of a failed, never-active create may run it
    again (`registry._resolve_reserve_collision`).
  - The `index` source is not exposed, because it yields a tag only for an active space and the
    index is written after the space goes active.
- **P6. The membership slot is very likely writable by the user it belongs to, and by anyone at
  sign-up.**
  - **No client says.** The `auth` module declares two app clients, the public `spa` client and the
    confidential `server` client, and neither sets `read_attributes` or `write_attributes`. A test
    holds them to that (`lambdas/test_session_infrastructure.py`), for a reason FR-001 keeps: a
    read list that omits a slot drops that slot's claim from the ID token.
  - **AWS's two documents disagree on what that means.** The developer guide says a new client
    gets "read and write permissions for all standard and custom attributes". The API reference
    says an unset list means standard attributes only.
  - **Reads follow the "all attributes" default.** The deployed ID token carries
    `custom:shared_space_k`, and Cognito includes a claim only for an attribute the client can
    read. Nothing suggests writes behave differently.
  - **Two paths write, and one needs no account.**
    - `SignUp` takes attributes, subject to the same write list, and through the public client it
      needs only that client's id. Anyone can sign up already carrying
      `custom:shared_space_1 = <any space>`, confirm, and sign in with that tag.
    - An existing user can call `UpdateUserAttributes` with a token from `ALLOW_USER_SRP_AUTH`,
      which carries `aws.cognito.signin.user.admin`. The public client allows that flow with no
      secret.
  - **Destroying the public client narrows this and does not close it.** After SPEC-262's second
    merge every client has a secret, and an API request to such a client must carry a hash of it
    (AWS developer guide, *Computing secret hash values*, which lists `SignUp` and `InitiateAuth`).
    Both paths above then need a secret that the server and anyone who can read the dev client's
    parameter hold. Sign-up through the managed-login page stays open to everyone, and whether a
    crafted form can carry a `custom:` attribute through it is not measured. So FR-001 is needed on
    either side of that merge.
  - **What a written slot reaches.** A slot naming a space gets that space's objects and catalog.
    A slot naming a user gets that user's catalog through `SharedSpaceGlue`.
  - The `cognito.tf` comment "Only the orchestrator role writes these" is a claim that nothing
    enforces. `transition_plan.md` §6.1 already says "everything is writable".
  - This is the grant side in its most direct form, and every door below assumes it is shut.
- **P7. The marker cannot be forged from a session.** No statement on the portal role grants
  `glue:CreateDatabase` or `glue:UpdateDatabase`, and the `data` module's portal-role policy has no
  Glue action at all. So neither the API nor Athena DDL (`CREATE DATABASE`,
  `ALTER DATABASE … SET DBPROPERTIES`) can write a database parameter. That is what lets FR-003 and
  FR-006 trust the marker.
- **P8. What a refusal discloses.**
  - Usernames are already visible to anyone signed in. The username directory publishes everyone
    with a personal prefix, and adding a non-member to a space answers "no such user".
  - Whether a space name exists can already be tested by anyone signed in, because a create of a
    taken name fails "name already taken".
  - **What is new is FR-002**, which lets an anonymous visitor test one name per sign-up attempt.
    The identity-and-access fences decline a published **list** of spaces as a disclosure. This
    publishes no list.
  - Andrew accepted the one-name-at-a-time test on 2026-09-26, on condition that the sentence is the
    same whatever the name collided with. The successor account has no self-sign-up.

## Scope

### In Scope

- FR-001: every app client declares which attributes it may read and write, so the membership slots
  cannot be written at sign-up or afterwards. Measured live before and after.
- FR-002: sign-up refuses a username that already names a Glue database.
- FR-003: provisioning never takes over a space's database, and a user found holding one is
  disabled.
- FR-004: a space cannot be named after a user in the pool.
- FR-005: the creator holds no slot for a name until the database under it is the space's own.
- FR-006: one read-only report says whether a collision, a self-written slot or an inherited
  database already exists. It also records the decision not to backfill markers.

### Out of Scope

- **The successor account's fence.**
  - `transition_plan.md` §3.12 item 3 leaves two choices to Phase 0: a check where credentials are
    minted, or database names that cannot overlap by construction. This spec builds neither for the
    successor.
  - It changes one input to that choice: the database marker now exists, so a minting check would
    have an ownership test to read.
  - The successor has no pre-signup, and its `cognito:username` is a synthetic
    `identitycenter_<subject>`.
- **A minting check in the current account** (`apicommon/identity.py` reading Glue before it stamps
  a tag). Declined. It would make every credential depend on Glue being reachable, file uploads and
  downloads included, and once FR-001 to FR-005 are in place every writer of either kind of name
  passes a door.
- **Space databases named so they cannot overlap usernames** (for example a leading underscore).
  Declined by Andrew on 2026-09-26: users see and type these names in SQL, and existing spaces would
  need a migration.
- **A backfill that marks the databases of spaces created before the marker.** Decided against in
  FR-006.
- **Removing `ALLOW_USER_SRP_AUTH`.** It is not what the slot write depends on, because `SignUp`
  writes attributes with no token at all, and FR-001's write list closes both paths. Removing it
  would also stop self-deletion through `DeleteUser`, but nothing has measured that Managed Login
  works without it.
- **A name freed by self-deletion when there is no database behind it.** FR-002 keeps a name taken
  while its database exists. A user whose post-confirmation never ran, who has files, and who
  deletes their own account leaves a name that can be registered again, prefix and all. No code
  path in the repo deletes users. This hazard is recorded here and not closed.
- **Fixing what the report finds.** Clearing a self-written slot, resolving a collision, or
  dropping a leftover database is done by hand and recorded. The report writes nothing.
- The archive and table-share keys' own versions of this hazard, named in the audit's register
  entry.
- An early warning in the browser's create dialog.

---

## Functional Requirements

### FR-001: Only the plane can write a membership slot

#### Description:

Every `aws_cognito_user_pool_client` under `infra/` declares two lists. Today those clients are
`spa` and `server`, both in `infra/modules/auth/cognito.tf`; a client added later, in that file or
another, declares them too, and the test below fails until it does.
- `write_attributes = ["email"]`, written as that literal on each client. Email is the one
  attribute sign-up collects, and it is required.
- `read_attributes = local.client_read_attributes`, one local that every client references:
  `email`, `email_verified`, and every `custom:shared_space_k` for `k` in
  `1..max_shared_memberships`. The API's `claims` source reads those slots from the ID token,
  whichever client issued it, and the header reads the email. The local is exactly this, and its
  `range` is the one the pool schema's `for_each` uses:

```hcl
client_read_attributes = concat(
  ["email", "email_verified"],
  [for k in range(1, var.max_shared_memberships + 1) : "custom:shared_space_${k}"],
)
```

Both lists are set together, on every client, in one apply. Setting only the write list could send
the read list back to a default that one of AWS's documents says excludes custom attributes, which
would remove every space from every token.

**This replaces an assertion and keeps its reason.**
`test_the_server_client_mirrors_the_spa_client_and_differs_only_where_it_must` asserts that neither
client carries either list, because a list that omits a slot drops that slot's claim, and a dropped
claim presents as the documented propagation delay and not as a fault. FR-001's test asserts the
stronger thing, that both lists are present and the read list covers every slot, so that assertion
is deleted and the mirror test's other assertions stay.

Pre-signup also refuses any sign-up whose `request.userAttributes` carries a `custom:` key,
whichever client or page it came through and whatever the trigger source. This is a second layer
behind the write list, and it keeps a live sign-up probe from creating an account. The check runs
after the format check and before the email-domain check. It refuses with **"Sign-up could not be
completed."**, a sentence only someone sending such an attribute ever sees, and records the
username with reason `custom-attribute`, never the attribute's value.

The premise is measured before the change with a **probe that changes nothing**:
- It is a short throwaway Python script that uses `pycognito`, in a virtual environment outside the
  repository, so it adds no dependency. `pycognito` signs in by SRP and sends the secret hash when
  it is given a client secret, so one script serves a client with a secret and one without.
- It signs in with a test account through the public client while that client exists, and through
  SPEC-262's dev client once it does not. Andrew types the password, and for the dev client
  supplies its secret from his own shell; the session never handles either.
- It reads the account's attributes and picks a slot that is already empty.
- It calls `UpdateUserAttributes` setting that slot to the empty string. `clear_slot` writes that
  same value, and `_from_claims` ignores it.

The probe has one "not writable" verdict: `NotAuthorizedException` whose message is about writing
an unauthorized attribute. Cognito uses the same code for a missing scope and for a bad token, so
any other outcome is inconclusive and is treated as writable.

The probe runs against one client, and the others are read. An unset list is the same setting on
every client, so one client's answer before the apply says what the default means for all of them.
After the apply the probe shows the list refusing on that client, and
`describe-user-pool-client` shows it on each: that call returns `WriteAttributes` and
`ReadAttributes` only for a client whose lists were set (AWS API reference,
`CreateUserPoolClient`), so a returned list is positive evidence and a missing one is a failure.

#### Acceptance Criteria:

- [ ] Before the apply, Andrew runs the probe against the deployed pool. The outcome is recorded
  with the client it signed in through and the error code and message quoted, along with the
  verdict the rule above gives it.
- [ ] A test in the lambdas suite visits every `aws_cognito_user_pool_client` block in every `.tf`
  file under `infra/`, as `test_every_rotation_block_states_its_grace_period` visits its blocks,
  and fails, naming the client, unless its `write_attributes` is exactly `["email"]`. It reads the
  list's literal elements, so `concat` or a reference to a local cannot hide a `custom:` entry.
- [ ] The same test fails, naming the client, unless its `read_attributes` is the reference
  `local.client_read_attributes`. It fails, naming the local, unless that local with its
  whitespace collapsed is exactly the expression in the Description, and unless the `range(...)` in
  it is character for character the one in the pool schema's `for_each`. The whole expression is
  pinned because the bounds alone prove nothing: a filter on `k`, or a slot name without `custom:`,
  keeps the bounds and drops claims.
- [ ] The mirror test no longer asserts that the lists are absent, and its other assertions pass
  unchanged.
- [ ] Six planted defects each turn that test red by its own message, naming the client or the
  local, and each is reverted. Another test going red beside it does not count.
  - deleting `write_attributes` from one client;
  - adding `"custom:shared_space_1"` to one client's;
  - changing the local's range to `range(1, var.max_shared_memberships)`, one short;
  - adding `if k != 3` to the local's comprehension;
  - dropping `custom:` from the local's slot name;
  - adding a client block that declares neither list, in a new `.tf` file beside `cognito.tf`.
- [ ] Unit: pre-signup refuses a sign-up carrying any `custom:` attribute with "Sign-up could not
  be completed." and reason `custom-attribute`, for `PreSignUp_SignUp` and
  `PreSignUp_AdminCreateUser` alike. It admits one carrying only `email`, and the keep-warm payload
  still passes.
- [ ] The CI plan shows every client updated in place, and neither the pool nor any client
  replaced. A replaced client is a new client id, which would end every session held under the old
  one.
- [ ] After the apply, the probe returns the "not writable" verdict.
- [ ] After the apply, `describe-user-pool-client` for every client the module declares returns a
  `WriteAttributes` of exactly `email` and a `ReadAttributes` naming `email`, `email_verified` and
  every slot.
- [ ] After the apply, a `SignUp` request with a fresh, well-formed username that submits
  `custom:shared_space_1` creates no account. It goes to the client the probe used, with a secret
  hash where that client has a secret. The refusal is recorded with its code and message, and it
  is one of two. Any other outcome fails this criterion.
  - **Cognito's `NotAuthorizedException` about an attribute the client may not write.** The write
    list refused at sign-up. This is the expected answer.
  - **Pre-signup's "Sign-up could not be completed."** Cognito handed the attribute to the
    trigger, so the write list has not been shown to guard sign-up, and pre-signup is the only
    layer shown to. Phase 6's fence then names pre-signup, and not the write list, as what closes
    sign-up, and the delivery doc says the write list is proven for `UpdateUserAttributes` only.
- [ ] After the apply, as the control, a member signs in fresh, through each client a browser can
  sign in through on that day, in a sign-in that starts after the apply. The web tier is on for
  it. Through each one a listing of their shared space's files succeeds, which it cannot without
  the slot claim, and their email is shown:
  - the server client, in every state: in the portal once the browser signs in through the
    server, and before that through `/auth/login`, with the listing asked through the `/api/`
    pass-through and the email read from `GET /auth/session`;
  - the public client, only while the portal signs in through Amplify: in the portal;
  - the dev client, once it exists: under `next dev`.

  Between SPEC-262's two merges the public client still exists and no browser signs in through it,
  so `describe-user-pool-client` is its only evidence.
- [ ] If the probe before the apply had any verdict other than "not writable", FR-006's report runs
  against the deployed account before this spec closes. A slot someone already wrote for
  themselves survives FR-001.

### FR-002: Sign-up refuses a username that already names a database

#### Description:

After the format check, `pre_signup.py` calls Glue `GetDatabase` on the requested username. Only
`EntityNotFoundException` admits the name. Every other answer refuses it:

- **A returned database, or `AccessDeniedException`**, refuses with **"That username is not
  available."** Access-denied is not read as absence. Lake Formation governs Glue metadata here,
  because `create_database_default_permissions` is empty, and this role holds no Lake Formation
  permission, so an existing database should answer exactly that way.
- **A throttle, a server fault or a timeout** refuses with **"Sign-up is briefly unavailable.
  Please try again in a minute."**

Details:
- The "not available" sentence is the same whatever kind of database it is: a space's, a user's, a
  leftover from a deleted space, or anything else.
- The record names the username and a reason that says which Glue answer refused the name. It never
  names the email.
- The check runs for every trigger source, so an operator's `AdminCreateUser` passes through it too.

Budget:
- Cognito waits five seconds for a trigger. The function's timeout rises from 3 to 5 seconds and its
  memory from 128 to 256 MB, to leave a cold start room.
- The Glue client allows 1 second to connect and 2 to read, with one attempt and no retries.
- A timeout at the function level still refuses. Cognito reports its own error instead of the
  try-again sentence, which is an accepted cost of failing closed.

Placement and permissions:
- The client is built with `boto3` directly, not `cpcommon.clients`. The singleton import-safety
  guard keeps pre-signup to `observability` from `cpcommon`, and that stays.
- The role gains `glue:GetDatabase` on the catalog and `database/*`, and nothing else.

Because no code path in the repo drops a user's database, this also stops the name of a provisioned
user who deleted their account from being registered again, together with that user's catalog and
prefix.

#### Acceptance Criteria:

- [ ] Unit: a name the format rule refuses is refused with the existing sentence, and no Glue call
  is made.
- [ ] Unit: a returned database refuses with "That username is not available." So does
  `AccessDeniedException`, with the same sentence byte for byte, and a reason field that tells the
  two apart.
- [ ] Unit: a throttle and a timeout each refuse with the try-again sentence, and neither admits the
  name.
- [ ] Unit: `EntityNotFoundException` admits the name and returns the event unchanged.
- [ ] Unit: the check runs for `PreSignUp_AdminCreateUser` as well as `PreSignUp_SignUp`.
- [ ] Unit: the record carries the username and the reason, and does not contain the email address.
- [ ] The singleton import-safety test still passes, with pre-signup's allowlist unchanged at
  `observability`.
- [ ] Live: signing up with a fresh name that follows the rule is admitted. This is the positive
  control. It fails if the IAM is wrong, or if Glue answers access-denied for names that do not
  exist. The trigger's reported duration on that cold start is recorded.
- [ ] Live: signing up with an existing space's name is refused, and the managed-login page shows
  "That username is not available." The record's reason says which Glue answer refused it.
  Access-denied is the expected answer. A returned database would mean Lake Formation lets this role
  see the database, and that is recorded.

### FR-003: Provisioning never takes over a space's database

#### Description:

The marker key moves to a new `cpcommon.markers` module, and is declared there once. The audit's
`teardown` and `create_space`, and `post_confirmation`, all read it from there. The module holds
constants only: it imports nothing and reads no environment.

**Why not `cpcommon.config`.** Post-confirmation sets none of the environment variables `config`
governs, and the singleton import-safety guard has two halves:
- The AST half checks which `cpcommon` **modules** a singleton names, not which attributes it
  reads. Allowlisting `config` would let a later `config.ADMIN_BUCKET` on some branch through,
  which is the exact failure the guard's docstring describes. It would do so for `backfill.py`
  too, since the guard globs the whole directory.
- The subprocess half runs only the import, and cannot see a deferred read.

So post-confirmation's allowlist widens from `observability` to `observability` and `markers`, with
that reason written beside it, and `config` stays forbidden.

When `provision_user` meets `AlreadyExistsException`, it reads the database before granting or
tagging anything. What it does next depends on what it finds:

- **Marked as a space's database (any space name).** It grants nothing and tags nothing.
  - In the Cognito trigger it calls `AdminDisableUser` on the new user and records an error with
    reason `username-is-a-space`, naming the username. Once a session is stamped with that
    username it already reaches the space's catalog, so refusing to grant stops nobody. Disabling
    does.
  - In the backfill it exits non-zero for that user, and its message names the collision.
- **Unreadable.** It grants nothing and tags nothing, and fails closed for the same reason.
  - In the trigger it also disables the user, and records reason `database-unreadable`.
  - In the backfill it exits non-zero for that user.
  - A legitimate user reaches this branch only through a Cognito retry of their own confirmation
    whose read also fails. The retry exists because the first attempt was slow, so the two faults
    are **correlated**, not independent: a Glue slowdown during sign-up will disable some
    legitimate new users. An operator re-enables each one after checking the database. That is the
    accepted cost of failing closed, in an account with few sign-ups.
- **Unmarked.** It carries on exactly as today. This is either an earlier attempt of the same
  confirmation (Cognito retries triggers) or, in the backfill, a user database that predates the
  marker. Once FR-002 is live it refuses any database that exists at sign-up. Pool usernames are
  unique, so between sign-up and confirmation the only thing that can create a database under this
  name is a space create, and a space create marks what it makes.

The collision record (`username-is-a-space` or `database-unreadable`) is written **before** the
first `AdminDisableUser` call. So a function timeout part-way through containment still leaves the
collision on record, and a Cognito retry of the trigger re-enters the same branch and tries again.
If `AdminDisableUser` fails, it is retried once. If it fails again, a second record with reason
`collision-uncontained`, at error level, follows, and the trigger still returns the event. FR-006
lists (a), (b) and (f) will then name the user.

The Glue, Lake Formation and Cognito clients are built with `boto3` directly, and each allows
1 second to connect and 1 to read, with one attempt and no retries. Botocore's defaults (60 seconds
each, with retries) would let one slow call outlast the trigger. The pool id comes from the trigger
event. Post-confirmation's timeout rises from 3 to 5 seconds. The role gains
`cognito-idp:AdminDisableUser` on the pool.

#### Acceptance Criteria:

- [ ] Unit, with fakes: when the existing database is space-marked, the trigger makes no
  `GrantPermissions` call, no `AddLFTagsToResource` call, and exactly one `AdminDisableUser` for
  that username. It records reason `username-is-a-space`, and it returns the event.
- [ ] Unit: when reading the existing database fails, the trigger makes no grant and no tag, makes
  one `AdminDisableUser`, and records reason `database-unreadable`.
- [ ] Unit: when `AdminDisableUser` fails twice, exactly two disable attempts were made, a
  `collision-uncontained` record follows the collision record, and the event is returned.
- [ ] Unit: the fakes' call order shows the collision record written before the first
  `AdminDisableUser` call.
- [ ] Unit: the Glue, Lake Formation and Cognito clients post-confirmation builds carry a 1-second
  connect limit, a 1-second read limit and a single attempt.
- [ ] Unit: when the existing database is unmarked, the trigger grants and tags exactly as it does
  today, and disables nobody.
- [ ] Unit: the backfill exits non-zero for a username whose database is space-marked or unreadable,
  its output names the collision, and another username in the same run is still provisioned.
- [ ] Unit: `teardown`, `create_space` and `post_confirmation` all resolve the marker key to the
  one `cpcommon.markers` constant, and no module declares a second literal of it.
- [ ] The singleton import-safety test passes with post-confirmation's allowlist widened to
  `markers`, including its subprocess import with no environment set, and still fails if
  post-confirmation names `config`. That last case is planted once and reverted.
- [ ] Deleting the marker read in `provision_user` turns the first criterion red, and the deletion
  is then reverted.

### FR-004: A space cannot be named after a user

#### Description:

`create_space` asks the pool about the requested name with `AdminGetUser`, which the orchestrator
role already holds. It asks **after** `reg.reserve` and **before** the database step or any slot,
inside the guard whose failure path records a failed create.

- **The user exists, in any status, unconfirmed included:** the create fails with
  `ProvisioningError("name already taken")`.
  - The ordinary failure path runs. It finalizes the actor's own reservation as `failed`, writes the
    failed cache entry and sends the notification.
  - Both use `_user_reason`, so the sentence is the one a taken space name produces. The refusal
    does not say whether the name belongs to a user or to a space.
- **Any pool answer other than `UserNotFoundException`:** the create fails as a retryable fault. It
  never reads the error as "no such user".
- **A taken name offers Dismiss and no Retry.** There are three taken-name refusals: the reserve
  collision in `registry.reserve`, the database that is not this space's in `_ensure_database`, and
  this one.
  - All three say the one sentence `name already taken`, byte for byte, so none tells a user from a
    space from an orphaned database.
  - Today the failed card offers Retry beside Dismiss for every failed create
    (`ConnectionsPage.tsx`, the failed create branch). Each of the three is refused again at the
    same step on every Retry for as long as the name's holder exists, so Retry there is a control
    that can never work.
  - The one holder that does give way is the same owner's own create still in flight, which
    `reserve` refuses as taken. It needs no Retry either: that create's own result, active or
    failed, replaces the collision card by name when it ends.
  - So all three raise one type, `NameTaken`, a subclass of `ProvisioningError` in
    `registry.py`, at `registry.py`'s collision, `_ensure_database`'s refusal and the pool check.
    Both failure branches of `create_space` write `retryable: false` on the actor's cache entry
    when, and only when, the caught exception is a `NameTaken`. The reserve branch catches every
    exception, including an S3 fault and a compare-and-swap that runs out of attempts, and those
    keep Retry. So does the membership limit, which is also a `ProvisioningError`.
  - The reserve branch writes through `cache.upsert_create_card`, which replaces only the create's
    own card (none, the provisioning seed, or a failed create) and leaves a space the actor
    already owns or belongs to as it is. So the flag goes on the entry that writer is handed, and
    never lands on an active, member, deleting or failed-delete card.
  - The card drops Retry when it reads the flag. Dismiss stays, since forgetting is what frees the
    owner's own failed reservation. It is a flag, not a match on the sentence, so the browser never
    keys on wording, and an entry without the flag keeps Retry.

Why after the reservation: the state machine retries the create verb (`MaxAttempts` 3). A retry
that found a new user and refused **before** reserving would go through the reserve-collision
branch, which writes no registry record. The reservation would then stay `provisioning` for good.
Refusing after it leaves a `failed` record, which the owner can forget. Forgetting it
drops a database only if an earlier attempt of the same create already made and marked one, and that
database is the space's own.

**The teardown revokes only on a database that is the space's own.** The audit's
`revoke_portal_role` stops when `owns_database` is `False`, but carries on when it is `None`, meaning
there is no database. A refused create for `x` leaves no database, and forgetting it while an
unconfirmed user `x` confirms would race post-confirmation and could revoke the portal-role grant it
had just made on `x`'s new database. That costs `x` availability, not access. The condition becomes
"stop unless `owns_database` is `True`". A missing database has no grants of this space's to
revoke.

An unconfirmed sign-up holds a name against spaces just as it already holds it against other
sign-ups. That is accepted.

The check belongs in the verb, not in the API's create route. The API plane holds no pool read, and
in the successor the pool is keyed on a synthetic username. There, a user's database exists before
the user ever signs in, so the audit's marker check is what covers the forward door.

#### Acceptance Criteria:

- [ ] Unit, with fakes: creating a space named after an existing user makes no
  `AdminUpdateUserAttributes` call, writes no S3 prefix marker and makes no Glue call. It ends with
  the registry record `failed`, the actor's cache entry `failed` with reason `name already taken`,
  and one notification.
- [ ] Unit: the same holds for a user in `UNCONFIRMED` status.
- [ ] Unit: the refusal's cache reason and notification text are byte-identical to those of a
  create whose name is an existing space.
- [ ] Unit: a create that has already reserved, and whose name gains a pool user before a retry,
  ends `failed` on the retry and is never left `provisioning`.
- [ ] Unit: an `AdminGetUser` fault other than `UserNotFoundException` fails the create as a
  retryable fault, and makes no slot write and no Glue call.
- [ ] Unit: a name with no pool user goes on to provision as it does today.
- [ ] Unit: the reserve collision, the database refusal and the pool refusal each write the reason
  `name already taken` and `retryable: false` on the create's own cache entry.
- [ ] Unit: none of these writes the flag: a reserve that fails with an S3 fault, a reserve whose
  compare-and-swap runs out of attempts, and a reached membership limit.
- [ ] Component: a failed create card whose entry carries `retryable: false` offers Dismiss and no
  Retry. One whose reason is `name already taken`, word for word, but which carries no flag still
  offers both, so a build that matches on the sentence fails.
- [ ] Unit: `revoke_portal_role` makes no `RevokePermissions` call when `owns_database` is `None`,
  and none when it is `False`. It revokes both grants when it is `True`.

### FR-005: The creator holds no slot until the database is the space's own

#### Description:

`create_space` finishes the database step before `membership.assign_or_find_slot`. The database
step is creating the database with the marker, or confirming that an existing one carries this
space's marker. A name whose database belongs to somebody else is then refused before any slot is
written, not written and rolled back. With the `claims` source, a slot written and rolled back has
already been in any ID token issued in between. A legitimate create still ends with the slot
assigned.

A membership-limit refusal now arrives after the database has been made. The existing failure path
records the space as failed, and because the database carries the marker, the teardown of the failed
record drops it.

#### Acceptance Criteria:

- [ ] Unit, with fakes: a create whose name has an unmarked existing database is refused, and the
  whole run makes **zero** `AdminUpdateUserAttributes` calls. The fake records every call.
  Rolling a slot back afterwards does not satisfy this criterion.
- [ ] Unit: a create with a fresh name ends `active`, holding a slot, with the database marked for
  the space.
- [ ] Unit: a create refused for the membership limit ends with the registry `failed` and the
  database marked, so `teardown.owns_database` returns `True`.
- [ ] Moving `assign_or_find_slot` back in front of the database step turns the first criterion red,
  and the move is then reverted.

### FR-006: One read-only report says what already exists

#### Description:

A one-shot function in the shared-space plane runs under the orchestrator role. That role already
reads the registry, lists and reads pool users, and lists and reads Glue databases
(`glue:GetDatabases`) as a Lake Formation admin. The only permission it gains is
`lakeformation:ListLakeFormationOptIns`. A `workflow_dispatch` workflow shaped like
`backfill-ever-active.yml` invokes it. It writes nothing, and it reports these lists:

- **(a) Usernames equal to the name of a real space.** A real space is a registry record that is
  active, or ever-active, or whose database `owns_database` says is its own. A refused
  reservation, meaning a `failed` record that was never active and owns no database, is what
  FR-004 leaves behind on every refusal, so it is not a collision.
- **(a′) Refused reservations whose name is a username.** For information only.
- **(b) Users whose personal database carries a space's marker.**
- **(c) Slots no registry record backs.** That is, every non-empty `custom:shared_space_k` that is
  not backed by a registry record whose roster includes that user. This covers a slot naming a
  space the user does not belong to, a username, a space since deleted, and a space not yet
  created. The last is a live grant the moment anyone creates that name. A self-written slot looks
  like this, and so does drift left by a failed rollback.
- **(d) Spaces in the registry whose database is unmarked.** These predate the marker. For
  information only.
- **(e) Glue databases that name neither a registry space nor a pool user.** These are leftovers,
  including those of legacy spaces whose records the delete removed. For information only.
- **(f) Users whose database's `CreateTime` is earlier than their `UserCreateDate`.** Such a user
  inherited a database that existed before them.
- **(g) The account's Lake Formation opt-ins.** For information only. A principal opted in over
  either bucket means P3's catalog-only reading does not hold, and any entry in (a), (b), (c) or
  (f) reached data as well.

The workflow fails when (a), (b), (c) or (f) has entries, or when any read failed. A read failure is
never reported as an empty list. Lists (a′), (d), (e) and (g) on their own pass.

The report runs under the orchestrator role, which can write. So "writes nothing" rests on the unit
test below and on review. A dedicated read-only role for a one-shot report was weighed and not
built.

**Decision: no backfill marks the legacy databases.**
- **Marking is the risky direction.** A mark is what allows the teardown to drop a database, so a
  marking backfill is the one new path that could bring back the data loss the audit closed. The
  only evidence it could go on is circumstantial: the pool, and the registry's `createdAt` against
  Glue's `CreateTime`.
- **Leaving them unmarked costs little, and is safe.** Tearing down a legacy space leaves its
  database behind, as the audit accepted. With FR-002 that leftover retires the name for sign-ups
  too, so no one can inherit it.
- **The population is small and temporary.** There are no production users, the current account is
  decommissioned at cutover, and spaces in the successor are seeded by code that marks.
- **An operator can still find every leftover.** List (e) names each one, so a name can be dropped
  by hand if it is ever wanted back.

#### Acceptance Criteria:

- [ ] Unit, with fakes: each of (a) to (f) lists exactly the planted entries, and each has a case
  with nothing planted that produces an empty list.
- [ ] Unit: a refused reservation whose name is a username (a `failed`, never-active record with no
  owned database) appears in (a′) and not in (a), and on its own the run passes.
- [ ] Unit: (c) lists a slot naming a space that does not exist, and a slot naming a deleted space.
  It does not list a slot backed by a roster that includes the user.
- [ ] Unit: a failed registry, pool, Glue or Lake Formation read makes the run fail and names the
  read. It never produces a list reported as clean.
- [ ] Unit: the function makes no write call to S3, Cognito, Glue or Lake Formation. The fakes
  record every call and the test asserts that none was a write.
- [ ] The workflow's exit status is non-zero when any of (a), (b), (c) or (f) has entries, and zero
  when only (a′), (d), (e) or (g) do. A test over the function's result asserts both cases.
- [ ] The report is run once against the deployed account. The count of every list is
  recorded in the delivery doc, along with the opt-ins in (g). Any entry in (a), (b), (c) or (f)
  is handled by hand and recorded there before this spec closes.

---

## Data Model

```python
# lambdas/control-plane-common/cpcommon/markers.py  (new; constants only, no imports, no env)
DATABASE_MARKER_KEY: str = "dataquarry.shared-space"  # moved here; one declaration

# lambdas/post-confirmation/post_confirmation.py
class ExistingDatabase(enum.Enum):
    """What an already-existing database under the username turned out to be."""
    UNMARKED = "unmarked"      # own earlier attempt, or a pre-marker user database: carry on
    SPACE = "space"            # a space's database: grant nothing, disable in the trigger
    UNREADABLE = "unreadable"  # grant nothing, disable in the trigger

# shared-space name-collision report result
class CollisionReport(TypedDict):
    usernames_that_are_spaces: list[str]             # (a) fails the run
    refused_reservations_named_for_users: list[str]  # (a') informational
    user_databases_marked_as_spaces: list[str]       # (b) fails the run
    unbacked_slots: list[dict[str, str]]             # (c) {"username", "slot", "value"}; fails
    unmarked_space_databases: list[str]              # (d) informational
    orphan_databases: list[str]                      # (e) informational
    inherited_databases: list[str]                   # (f) usernames; fails the run
    lake_formation_opt_ins: list[str]                # (g) principal ARNs; informational
    failed_reads: list[str]                          # non-empty fails the run
```

## API / Interface Contract

No route changes. The browser changes in one place: a failed create card whose cache entry carries
`retryable: false` offers Dismiss without Retry (FR-004). Otherwise the create refusal arrives
through the existing failed card and notification, and the sign-up refusal is the trigger's message
on the managed-login page.

```text
pre-signup, name exists or unreadable:   "That username is not available."
pre-signup, Glue throttled or timed out: "Sign-up is briefly unavailable. Please try again in a minute."
pre-signup, a custom: attribute sent:    "Sign-up could not be completed."   reason="custom-attribute"
create, user, space or foreign db holds it: "name already taken"   (unchanged sentence)
                                           cache entry retryable: false
post-confirmation, space-marked db:      reason="username-is-a-space", user disabled
post-confirmation, db unreadable:        reason="database-unreadable", user disabled
post-confirmation, disable failed twice: reason="collision-uncontained"
```

## File & Folder Structure

```
infra/modules/auth/
├── cognito.tf                                    # FR-001 read/write attributes on every client
├── lambda.tf                                     # FR-002, FR-003 timeouts and memory
└── policies/
    ├── pre-signup-permissions.json.tftpl         # FR-002 glue:GetDatabase
    └── post-confirmation-permissions.json.tftpl  # FR-003 cognito-idp:AdminDisableUser
infra/plane-shared-spaces.tf                      # FR-006 one-shot function, in the plane's function map
infra/planes/shared-spaces/execution.json.tftpl   # FR-006 ListLakeFormationOptIns
lambdas/
├── test_session_infrastructure.py                # FR-001 the mirror test's absent-lists assertion goes
├── control-plane-common/cpcommon/markers.py      # FR-003 marker key, one declaration (new)
├── control-plane-common/test_layer_import_safety.py   # FR-003 post-confirmation allowlist
├── pre-signup/pre_signup.py                      # FR-001 custom: refusal, FR-002 Glue read
├── post-confirmation/{post_confirmation,backfill}.py   # FR-003
├── shared-space-common/{config,teardown}.py      # FR-003 read the moved key; FR-004 revoke only on own
├── shared-space-common/registry.py               # FR-004 NameTaken, raised at the collision
├── shared-space-create/create_space.py           # FR-004, FR-005
└── shared-space-name-collisions/                 # FR-006 (new, report only)
apps/portal/src/features/
├── shared-spaces/sharedSpaces.{service,types}.ts # FR-004 read the entry's retryable flag
├── connections/{useConnections,connection.types}.ts  # FR-004 carry it; fields are copied by name
├── shared-spaces/ConnectionsPage.tsx             # FR-004 carry it to the row; no Retry when false
└── help/helpContent.ts                           # FR-004 the create steps' "Retry to try again"
.github/workflows/report-name-collisions.yml      # FR-006
```

## Implementation Phases

### Phase 1: The slot is not writable (FR-001)

- Andrew runs the probe against the deployed pool, and the outcome is recorded.
- Add both attribute lists to every client and the test over `cognito.tf`, delete the mirror test's
  absent-lists assertion, and add pre-signup's refusal of `custom:` attributes.
- Apply, re-run the probe, read every client's lists and run the sign-up check.
- Switch the web tier on through the repository variable and CI, run the fresh-sign-in control
  through each client, and switch the tier off the same way.
- This phase depends on nothing else in the spec and is the most urgent. It lands on its own, first.

### Phase 2: IAM before the code that needs it

- `glue:GetDatabase` for the pre-signup role.
- `cognito-idp:AdminDisableUser` for the post-confirmation role.
- `lakeformation:ListLakeFormationOptIns` for the orchestrator role.
- Whatever the deploy role needs to create the FR-006 function, read from
  `infra/info/deploy-role-iam.md` and `lambdas/info/deployment.md`.

### Phase 3: The sign-up door (FR-002)

- The Glue read in pre-signup, with its client limits and its two sentences.
- The timeout and memory changes.
- The live checks: a fresh name is admitted, and a space's name is refused.
- This comes before Phase 5, because FR-003's handling of an unmarked database rests on FR-002
  being live.

### Phase 4: The report (FR-006)

- The function, the workflow, and one run against the deployed account.
- Record the counts, and handle any finding by hand.

### Phase 5: The create verb and provisioning (FR-003, FR-004, FR-005)

- Move the marker key into `cpcommon.markers`, and widen post-confirmation's import allowlist to it.
- Make the teardown revoke only on a database that is the space's own.
- Put the pool check after the reservation, and the database step in front of the slot.
- Raise `NameTaken` at all three taken-name refusals and write `retryable: false` on it alone,
  carry the flag through the connection mapping, and drop Retry from the card that reads it.
- In Help, the create steps' last step stops promising Retry for every failure: a taken name
  offers Dismiss only.
- Classify the existing database in `provision_user`, disabling the user in the trigger.

### Phase 6: Where the decisions are written down

- A register entry in `docs/decisions/control-planes/`, and one in
  `docs/decisions/identity-and-access/`.
- Clauses in the identity fences:
  - The slot claims are an authorization input only because no client can write them.
  - A name is a user's or a space's, and pre-signup and create are the two doors.
- Mark as superseded, in place, `transition_plan.md` §6.1's "this repo's app client sets neither"
  and the sentence in §3.12 item 3 saying no fence exists.
- Update:
  - the `cognito.tf` slot comment, which FR-001 makes true, and its comment above the server
    client, which says neither client carries a read list;
  - `infra/modules/auth/README.md`;
  - the pre-signup and post-confirmation sizing comments in `lambda.tf`;
  - the `analytics/lakeformation.tf` credential-vending comment, if FR-006's opt-in read
    contradicts it.
