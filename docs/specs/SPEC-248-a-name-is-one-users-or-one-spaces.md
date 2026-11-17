---
type: Spec
id: SPEC-248
title: "A Name Is One User's or One Space's, and Only the Plane Writes a Membership"
description: "Closes the access gap where a shared-space name could be claimed as a user's Glue database name and anyone could write any name into their own membership list, so only the plane writes memberships; sign-up is left out because the target environment has none."
spec_status: Draft
depends_on: [SPEC-012, SPEC-051, SPEC-056, SPEC-257]
---

**Dependency notes:** SPEC-012, SPEC-051, SPEC-056, and SPEC-257, whose confidential server client
and whose test over `cognito.tf` FR-001 changes. The control-plane data-loss audit this spec was
written beside merged on 2026-09-26 (#892), so FR-002 to FR-004 read its database marker from
`main`. FR-001 depends on nothing else in this list, and it lands first.

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

This spec closes the access half on the side of spaces and memberships. It has three parts:
- A person creating a space must not be able to name it after a user and so reach that user's
  catalog, not even for the few hundred milliseconds before the create is refused.
- Above all, no one may write a space's name or a user's name into their own account's membership
  list. The evidence below says that today anyone can, including someone who has not signed in yet
  and does it at sign-up.
- Nobody should notice any of this except a person trying one of these things. That person is
  refused with the same short sentence whichever name they collided with.

**Sign-up is not one of the doors this spec guards.** In the target environment nobody signs up:
users arrive federated, and their database names are predetermined. So the work that would only
guard self-sign-up in the current account is left out, as Andrew decided on 2026-11-17: a pre-signup
check on the requested name, a post-confirmation guard against taking over a space's database, a
pre-signup refusal of `custom:` attributes, and a live `SignUp` check. The current account keeps
self-sign-up until it is decommissioned, and what that leaves open there is stated under Out of
Scope. FR-001's write list still applies to `SignUp`, because a client's write list governs the
calls made through that client, `SignUp` and `UpdateUserAttributes` alike. For `SignUp` that is
documented and not measured. Admin calls made under IAM are not limited by it, which is why the
plane can still write a slot.

## What was measured, and what it means

A security spec rests on its premises, so each one is stated with where it was read. None was
exercised against the deployed account. P6's `UpdateUserAttributes` half is measured by FR-001
before anything else is built, and its `SignUp` half is not measured at all. P3 is measured
by FR-004. Each was read again against `main` at `5408a55e`, after SPEC-257 merged; P5 and P6 are
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
    "by LF credential vending", which contradicts the hybrid setting. FR-004 reads the account's
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
  - **This spec leaves this door open.** It is a sign-up door, and the target environment has no
    sign-up (Overview). FR-004's lists (a), (b) and (f) name anyone who had come through it by the
    time the report ran.
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
  `ALTER DATABASE … SET DBPROPERTIES`) can write a database parameter. That is what lets FR-002 to
  FR-004 trust the marker.
- **P8. What a refusal discloses.**
  - Usernames are already visible to anyone signed in. The username directory publishes everyone
    with a personal prefix, and adding a non-member to a space answers "no such user".
  - Whether a space name exists can already be tested by anyone signed in, because a create of a
    taken name fails "name already taken".
  - So FR-002's refusal discloses nothing new, as long as its sentence is the same whatever the name
    collided with.

## Scope

### In Scope

- FR-001: every app client declares which attributes it may read and write, so a signed-in user
  cannot write a membership slot. Measured live before and after.
- FR-002: a space cannot be named after a user in the pool.
- FR-003: the creator holds no slot for a name until the database under it is the space's own.
- FR-004: one read-only report says whether a collision, a self-written slot or an inherited
  database already exists. It also records the decision not to backfill markers.

### Out of Scope

- **The sign-up door, in the current account.** The target environment has no self-sign-up, and its
  database names are predetermined, so nothing here guards sign-up (Andrew, 2026-11-17). Left out:
  - a pre-signup check that refuses a username already naming a Glue database;
  - a post-confirmation guard that refuses to grant on, and disables a user who lands on, a
    database marked as a space's;
  - a pre-signup refusal of any sign-up carrying a `custom:` attribute, which would have been a
    second layer behind FR-001's write list;
  - a live `SignUp` check that a submitted slot creates no account.

  What that leaves open in the current account until it is decommissioned: P4's reverse door, so a
  stranger who signs up under a space's name reaches that space's catalog, and a name freed by
  self-deletion can be registered again, prefix and catalog both, because post-confirmation treats
  an existing database as success and grants on it. There are no production users, and FR-004's
  lists (a), (b) and (f) name anyone who had come through by the time the report ran. FR-001's
  write list is documented to cover a slot submitted at sign-up, though no live check proves it
  for `SignUp`.
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
  downloads included, and once FR-001 to FR-003 are in place every space create passes a door.
  The other writer, sign-up, is left out above.
- **Space databases named so they cannot overlap usernames** (for example a leading underscore).
  Declined by Andrew on 2026-09-26: users see and type these names in SQL, and existing spaces would
  need a migration.
- **A backfill that marks the databases of spaces created before the marker.** Decided against in
  FR-004.
- **Removing `ALLOW_USER_SRP_AUTH`.** It is not what the slot write depends on, because `SignUp`
  writes attributes with no token at all, and FR-001's write list closes `UpdateUserAttributes`,
  which is measured, and is documented to close `SignUp`, which is left unmeasured along with the
  rest of sign-up. Removing it
  would also stop self-deletion through `DeleteUser`, but nothing has measured that Managed Login
  works without it.
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
`spa` and `server`, both in `infra/modules/auth/cognito.tf`, which is where the local below lives;
a client added later, in any file of that module, declares them too, and the test below fails
until it does.
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

- [ ] Before the apply, Andrew runs the probe against the deployed pool, as a test account he
  names. The outcome is recorded in the delivery doc with the client it signed in through and the
  error code and message quoted, along with the verdict the rule above gives it.
- [ ] A test in `lambdas/test_session_infrastructure.py` visits every `aws_cognito_user_pool_client` block in every `.tf`
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
- [ ] Seven planted defects each turn that test red by its own message, naming the client or the
  local, and each is reverted. Another test going red beside it does not count.
  - deleting `write_attributes` from one client;
  - adding `"custom:shared_space_1"` to one client's;
  - changing the local's range to `range(1, var.max_shared_memberships)`, one short;
  - adding `if k != 3` to the local's comprehension;
  - dropping `custom:` from the local's slot name;
  - changing the pool schema's `for_each` to `range(1, var.max_shared_memberships + 2)`, which is
    the one plant the range comparison alone catches;
  - adding a client block that declares neither list, in a new `.tf` file beside `cognito.tf`.
- [ ] The CI plan shows every client updated in place, and neither the pool nor any client
  replaced. A replaced client is a new client id, which would end every session held under the old
  one.
- [ ] After the apply, the probe returns the "not writable" verdict.
- [ ] After the apply, `describe-user-pool-client` for every client the module declares returns a
  `WriteAttributes` of exactly `email` and a `ReadAttributes` naming `email`, `email_verified` and
  every slot.
- [ ] After the apply, as the control, a member signs in fresh, through each client a browser can
  sign in through on that day, in a sign-in that starts after the apply. The web tier is on for
  it. Through each one a listing of their shared space's files succeeds, which it cannot without
  the slot claim, and their email is shown:
  - the server client, in every state: in the portal once the browser signs in through the
    server, and before that through `/auth/login`, with the listing sent as the request the portal
    itself makes for it, `/api` put in front of its path, and the email read from
    `GET /auth/session`;
  - the public client, only while the portal signs in through Amplify: in the portal;
  - the dev client, once it exists: under `next dev`.

  Between SPEC-262's two merges the public client still exists and no browser signs in through it,
  so `describe-user-pool-client` is its only evidence.
- [ ] If the probe before the apply had any verdict other than "not writable", FR-004's report runs
  against the deployed account before this spec closes. A slot someone already wrote for
  themselves survives FR-001.

### FR-002: A space cannot be named after a user

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

### FR-003: The creator holds no slot until the database is the space's own

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

### FR-004: One read-only report says what already exists

#### Description:

A one-shot function in the shared-space plane runs under the orchestrator role. That role already
reads the registry, lists and reads pool users, and lists and reads Glue databases
(`glue:GetDatabases`) as a Lake Formation admin. The only permission it gains is
`lakeformation:ListLakeFormationOptIns`. A `workflow_dispatch` workflow shaped like
`backfill-ever-active.yml` invokes it. It writes nothing, and it reports these lists:

- **(a) Usernames equal to the name of a real space.** A real space is a registry record that is
  active, or ever-active, or whose database `owns_database` says is its own. A refused
  reservation, meaning a `failed` record that was never active and owns no database, is what
  FR-002 leaves behind on every refusal, so it is not a collision.
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
  database behind, as the audit accepted. In the current account a sign-up under that name would
  inherit it, which is the sign-up door this spec leaves open (Out of Scope), and a later run's
  list (f) would name that user.
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
`retryable: false` offers Dismiss without Retry (FR-002). Otherwise the create refusal arrives
through the existing failed card and notification.

```text
create, user, space or foreign db holds it: "name already taken"   (unchanged sentence)
                                           cache entry retryable: false
```

## File & Folder Structure

```
infra/modules/auth/cognito.tf                     # FR-001 read/write attributes on every client
infra/plane-shared-spaces.tf                      # FR-004 one-shot function, in the plane's function map
infra/planes/shared-spaces/execution.json.tftpl   # FR-004 ListLakeFormationOptIns
lambdas/
├── test_session_infrastructure.py                # FR-001 the mirror test's absent-lists assertion goes
├── shared-space-common/teardown.py               # FR-002 revoke only on own
├── shared-space-common/registry.py               # FR-002 NameTaken, raised at the collision
├── shared-space-create/create_space.py           # FR-002, FR-003
└── shared-space-name-collisions/                 # FR-004 (new, report only)
apps/portal/src/features/
├── shared-spaces/sharedSpaces.{service,types}.ts # FR-002 read the entry's retryable flag
├── connections/{useConnections,connection.types}.ts  # FR-002 carry it; fields are copied by name
├── shared-spaces/ConnectionsPage.tsx             # FR-002 carry it to the row; no Retry when false
└── help/helpContent.ts                           # FR-002 the create steps' "Retry to try again"
.github/workflows/report-name-collisions.yml      # FR-004
```

## Implementation Phases

### Phase 1: The slot is not writable (FR-001)

- Andrew runs the probe against the deployed pool, and the outcome is recorded.
- Add both attribute lists to every client and the test over `cognito.tf`, and delete the mirror
  test's absent-lists assertion.
- In the same change, correct the two `cognito.tf` comments the lists make wrong or make true: the
  one above the server client, which says neither client carries a read list, and the slot
  comment's "Only the orchestrator role writes these".
- Apply, re-run the probe, and read every client's lists.
- Switch the web tier on through the repository variable and CI, run the fresh-sign-in control
  through each client, and switch the tier off the same way.
- This phase depends on nothing else in the spec and is the most urgent. It lands on its own, first.

### Phase 2: IAM before the code that needs it

- `lakeformation:ListLakeFormationOptIns` for the orchestrator role.
- Whatever the deploy role needs to create the FR-004 function, read from
  `infra/info/deploy-role-iam.md` and `lambdas/info/deployment.md`.

### Phase 3: The report (FR-004)

- The function, the workflow, and one run against the deployed account.
- Record the counts, and handle any finding by hand.

### Phase 4: The create verb (FR-002, FR-003)

- Make the teardown revoke only on a database that is the space's own.
- Put the pool check after the reservation, and the database step in front of the slot.
- Raise `NameTaken` at all three taken-name refusals and write `retryable: false` on it alone,
  carry the flag through the connection mapping, and drop Retry from the card that reads it.
- In Help, the create steps' last step stops promising Retry for every failure: a taken name
  offers Dismiss only.

### Phase 5: Where the decisions are written down

- A register entry in `docs/decisions/control-planes/`, and one in
  `docs/decisions/identity-and-access/`.
- Clauses in the identity fences:
  - The slot claims are an authorization input only because no client can write them.
  - A name is a user's or a space's. The space create is the door this account guards; sign-up is
    left open until the account is decommissioned, because the target environment has no sign-up.
- Mark as superseded, in place, `transition_plan.md` §6.1's "this repo's app client sets neither"
  and the sentence in §3.12 item 3 saying no fence exists.
- Update:
  - `infra/modules/auth/README.md`;
  - the `analytics/lakeformation.tf` credential-vending comment, if FR-004's opt-in read
    contradicts it.
