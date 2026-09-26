# Spec: A Name Is One User's or One Space's, and Only the Plane Writes a Membership

**ID:** SPEC-248
**Status:** Draft
**Last Updated:** 2026-09-26
**Depends On:** SPEC-012, SPEC-051, SPEC-056, and the control-plane data-loss audit
(`audit/control-planes`, commit `394cfce8`), which was **not on `main`** when this spec was written.
FR-003 to FR-006 read that commit's database marker and do not start until it has merged. FR-001
depends on nothing and lands first.

## Overview

A username and a shared-space name are both used as the name of a Glue database, and there is only
one set of Glue database names. The permissions a signed-in session carries are written against
that name: "the database called whatever your username is" and "the database called whatever each
of your spaces is called". So whoever controls a name controls a catalog. The data-loss half of
this was fenced on 2026-09-26: a space named after a user no longer takes over that user's database,
and deleting a space only ever drops a database the space made. This spec closes the access half.
A person signing up must not be able to take a space's name and so reach its catalog. A person
creating a space must not be able to name it after a user and so reach that user's catalog, not
even for the few hundred milliseconds before the create is refused. Above all, no one may simply
write a space's name, or a user's, into their own account's membership list, and the evidence below
says today they very likely can. Nobody should notice any of this except a person trying one of these
things, who is refused with the same short sentence whichever name they collided with.

## What was measured, and what it means

A security spec rests on its premises, so each one is stated with where it was read. None was
exercised against the deployed account. P6 is measured by FR-001 before anything else is built.

- **P1. One namespace, two writers.** `post_confirmation._ensure_database(username)` and
  `create_space._ensure_database(name)` are the only `create_database` calls in `lambdas/`, and
  `infra/` declares no Glue database. Both names answer to the one catalog rule
  `^[a-z][a-z0-9_]{2,62}$`, so any username is a legal space name and the reverse.
- **P2. Lake Formation cannot tell sessions apart. IAM is the gate.** Both writers grant the
  **shared portal role**, not the person's own principal (the brief for this spec said the
  opposite, and it is corrected here). The role gets `DESCRIBE`, `CREATE_TABLE`, `ALTER` and `DROP`
  on the database, and `SELECT`, `INSERT`, `DESCRIBE`, `ALTER` and `DROP` on its tables. Every user
  shares that role. Which database a session may touch is decided by two IAM statements that write
  into the same ARN space: `GlueUserDatabaseScoped` in `portal-role-analytics.json.tftpl`
  interpolates `${aws:PrincipalTag/username}`, and `SharedSpaceGlue` in
  `portal-role-shared-space.json.tftpl` interpolates each `shared_space_k` tag, into
  `database/<name>` and `table/<name>/*`.
- **P3. Today a collision reaches the catalog, not the files.** Both buckets are registered with
  `hybrid_access_enabled = true`, and no principal is opted in: `infra/` has no
  `aws_lakeformation_opt_in`. So Athena reads S3 with the caller's own IAM, and the S3 statements
  are scoped per bucket: `username` to the user-space bucket, `shared_space_k` to the shared
  bucket. A colliding tag therefore gives the Glue actions of the statement it matches. That means
  reading every table's schema, location and partition values, creating tables, pointing an
  existing table somewhere else, and dropping tables. It does not give the objects. **This depends
  on configuration and would not survive a change to it.** An opt-in, or a move to Lake Formation
  enforcement (transition Phase 1 re-registers these buckets), would have Lake Formation hand out
  the credentials, and a collision would then reach the data (`docs/transition_plan.md` §3.12
  item 3).
- **P4. The reverse door is open.** `pre_signup.py` makes no AWS call; its role grants logs only.
  `post_confirmation._ensure_database` treats `AlreadyExistsException` as success, then grants and
  tags. So a stranger who signs up as `team_x`, where a space `team_x` exists, is stamped
  `username=team_x`, and `GlueUserDatabaseScoped` gives them that space's catalog with no
  membership at all. The same person also loses everything later: when the space is deleted, the
  teardown drops that database (its marker says it is the space's), along with every table they
  made there believing it was their own.
- **P5. The forward door leaves a window even after the audit.** On `main` the create adopts a
  user's database and goes active, so the creator and every later member carry a tag naming that
  user's database, permanently. The audit commit refuses an unmarked database, but only inside
  `_ensure_database`, which runs **after** `membership.assign_or_find_slot` has written
  `custom:shared_space_k = <name>` onto the creator. The rollback, `clear_slot`, is best-effort. Under
  the `claims` membership source, which every deployed environment runs (`MEMBERSHIP_SOURCE` is set
  nowhere in `infra/`), the API stamps whatever the ID token carries and consults no registry. The
  SPA client sets no token lifetime, so an ID token lasts Cognito's default of one hour. A creator
  who refreshes their token inside the window, and can retry the create to reopen it, keeps that
  user's catalog for an hour. The `index` source is not exposed, because it yields a tag only for an
  active space and the index is written after the space goes active.
- **P6. The membership slot is very likely writable by its own user.** `aws_cognito_user_pool_client.spa`
  sets neither `read_attributes` nor `write_attributes`, and AWS's two documents disagree on what
  that means. The developer guide says a new client gets "read and write permissions for all
  standard and custom attributes". The API reference says an unset list means standard attributes
  only. The deployed ID token carries `custom:shared_space_k`, and Cognito includes a claim only for
  an attribute the client can read, so this client has the "all attributes" default for reads.
  Nothing suggests writes behave differently. `ALLOW_USER_SRP_AUTH` is enabled, and a token from the
  user-pools API carries `aws.cognito.signin.user.admin`, which is the only scope
  `UpdateUserAttributes` needs. If the slot is writable, any user can put any space's name into
  their own slot and get that space's objects and catalog, or put a username there and get that
  user's catalog through `SharedSpaceGlue`. The `cognito.tf` comment "Only the orchestrator role
  writes these" is a claim that nothing enforces. `transition_plan.md` §6.1 already says
  "everything is writable". This is the grant side in its most direct form: every door below
  assumes it is shut.
- **P7. The marker cannot be forged from a session.** No statement on the portal role grants
  `glue:CreateDatabase` or `glue:UpdateDatabase`, and the `data` module's portal-role policy has no
  Glue action at all. So neither the API nor Athena DDL (`CREATE DATABASE`,
  `ALTER DATABASE … SET DBPROPERTIES`) can write a database parameter. That is what lets FR-003 and
  FR-006 trust the marker.
- **P8. What a refusal discloses.** Usernames are already visible to anyone signed in: the username
  directory publishes everyone with a personal prefix, and adding a non-member to a space answers
  "no such user". A space name's existence is already probe-able by anyone signed in, because a
  create of a taken name fails "name already taken". **What is new is FR-002**, which lets an
  anonymous visitor test one name per sign-up attempt. The identity-and-access fences decline a
  published **list** of spaces as a disclosure. This publishes none, and Andrew accepted the
  one-name-at-a-time probe on 2026-09-26, on the condition that the sentence is the same whatever the
  name collided with. The successor account has no self-sign-up.

## Scope

### In Scope

- FR-001: the SPA client declares which attributes it may read and write, and the membership slots
  are not writable. Measured live before and after.
- FR-002: sign-up refuses a username that already names a Glue database.
- FR-003: provisioning never takes over a space's database, and a user found holding one is
  disabled.
- FR-004: a space cannot be named after a user in the pool.
- FR-005: the creator holds no slot for a name until the database under it is the space's own.
- FR-006: one read-only report says whether a collision or a self-written slot already exists, and
  the decision not to backfill markers.

### Out of Scope

- **The successor account's fence.** `transition_plan.md` §3.12 item 3 leaves two choices to
  Phase 0: a check where credentials are minted, or database names that cannot overlap by
  construction. This spec builds neither for the successor. It changes one input to that choice:
  the database marker now exists, so a minting check would have an ownership test to read. The
  successor has no pre-signup, and its `cognito:username` is a synthetic `identitycenter_<subject>`.
- **A minting check in the current account** (`apicommon/identity.py` reading Glue before it stamps
  a tag). Declined. It would make every credential depend on Glue being reachable, file uploads and
  downloads included, and once FR-001 to FR-005 are in place every writer of either kind of name
  passes a door.
- **Space databases named so they cannot overlap usernames** (for example a leading underscore).
  Declined by Andrew on 2026-09-26: users see and type these names in SQL, and existing spaces would
  need a migration.
- **A backfill that marks the databases of spaces created before the marker.** Decided against in
  FR-006.
- **Removing `ALLOW_USER_SRP_AUTH`.** That would take the admin-scoped token away altogether, and
  would also stop self-deletion through `DeleteUser`. But nothing has measured that Managed Login
  works without it, and FR-001's write list closes the slot on its own.
- **Fixing what the report finds.** Clearing a self-written slot, or resolving a collision, is done
  by hand and recorded. The report writes nothing.
- The archive and table-share keys' own versions of this hazard, named in the audit's register
  entry.
- An early warning in the browser's create dialog.

---

## Functional Requirements

### FR-001: Only the plane can write a membership slot

#### Description:

`aws_cognito_user_pool_client.spa` declares `write_attributes = ["email"]`. Email is the one
attribute sign-up collects, and it is required. It also declares `read_attributes` as `email`,
`email_verified` and every `custom:shared_space_k` for `k` in `1..max_shared_memberships`, built
from the same `range` expression the pool schema uses. The API's `claims` source reads those slots
from the ID token, and the header reads the email. Both lists are set together. Setting only the
write list could send the read list back to a default that one of AWS's documents says excludes
custom attributes, which would remove every space from every token.

The premise is measured before the change with a **probe that changes nothing**. It is a short Node
script using the portal's own `aws-amplify`. It signs in by SRP with a test account (the password
is typed by Andrew; the session never handles it), reads the account's attributes, picks a slot
that is already empty, and calls `UpdateUserAttributes` setting that slot to the empty string.
Accepted means writable. The value is unchanged whichever way it goes.

#### Acceptance Criteria:

- [ ] Before the apply, Andrew runs the probe against the deployed pool, and its outcome is recorded
  with the error code and message quoted: accepted, or `NotAuthorizedException`.
- [ ] A test over `infra/modules/auth/cognito.tf` in the lambdas suite fails when `write_attributes`
  is absent, and when it contains any `custom:` attribute. Its message names the offending
  attribute.
- [ ] The same test fails, naming the missing slot, when `read_attributes` lacks any
  `custom:shared_space_k` for `k` in `1..max_shared_memberships`. It reads the slots from the
  `range` expression rather than from a hand-written list.
- [ ] Each of those two tests is broken once and seen to go red, then restored. The broken states
  are deleting `write_attributes`, and removing the slot expression from `read_attributes`.
- [ ] `tofu plan` shows the client updated in place, and neither the pool nor the client replaced.
- [ ] After the apply, the probe is refused with `NotAuthorizedException`, and its message is about
  writing an unauthorized attribute, not about a missing scope or a bad token.
- [ ] After the apply, as the control, a member's shared space still opens in the portal and the
  header still shows their email.
- [ ] If the probe before the apply was accepted, FR-006's report runs against the deployed account
  before this spec closes. A slot someone already wrote for themselves survives FR-001.

### FR-002: Sign-up refuses a username that already names a database

#### Description:

After the format check, `pre_signup.py` calls Glue `GetDatabase` on the requested username. Only
`EntityNotFoundException` admits the name. Every other answer refuses it:

- A returned database, or `AccessDeniedException`, refuses with **"That username is not
  available."** Access-denied is not read as absence. The role holds no Lake Formation permission,
  so an existing database it cannot see may well answer that way.
- A throttle, a server fault or a timeout refuses with a separate sentence asking the person to
  try again shortly.

The "not available" sentence is identical whatever kind of database it is: a space's, a user's, a
dropped space's leftover, or anything else. The check runs for every trigger source, so an
operator's `AdminCreateUser` passes through it too. The client's connect and read timeouts, and its
retry count, keep the check inside Cognito's five-second trigger limit. The record names the
username and the reason, and never the email. The role gains `glue:GetDatabase` on the catalog and
`database/*`, and nothing else.

Because no code path in the repo drops a user's database, this also stops a name being registered
again after its user was deleted. Otherwise the new owner would inherit the old owner's catalog and
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
- [ ] Live: signing up with a fresh name that follows the rule is admitted. This is the positive
  control. It fails if Glue answers access-denied for names that do not exist.
- [ ] Live: signing up with an existing space's name is refused, and the managed-login page shows
  "That username is not available." The record's reason says which Glue answer produced the
  refusal.

### FR-003: Provisioning never takes over a space's database

#### Description:

The marker key moves to `cpcommon.config` and is declared there once. The audit's `teardown` and
`create_space`, and `post_confirmation`, all read it from there. When `provision_user` meets
`AlreadyExistsException`, it reads the database before granting or tagging anything:

- **Marked as a space's database (any space name):** it grants nothing and tags nothing. In the
  Cognito trigger it also calls `AdminDisableUser` on the new user and records an error with
  reason `username-is-a-space`, naming the username. Once a session is stamped with that username
  it already reaches the space's catalog, so refusing to grant stops nobody. Disabling does. In the
  backfill it exits non-zero for that user, and its message names the collision.
- **Unmarked:** it carries on exactly as today. This is either an earlier attempt of the same
  confirmation (Cognito retries triggers) or, in the backfill, a user database that predates the
  marker. FR-002 refused any database that existed at sign-up. Pool usernames are unique, so
  between sign-up and confirmation the only thing that can create a database under this name is a
  space create, and a space create marks what it makes.
- **Unreadable:** it grants nothing, tags nothing and disables nobody, and records today's
  `provisioning-failed` error with remediation `backfill`.

The post-confirmation role gains `cognito-idp:AdminDisableUser` on the pool.

#### Acceptance Criteria:

- [ ] Unit, with fakes: when the existing database is space-marked, the trigger makes no
  `GrantPermissions` call, no `AddLFTagsToResource` call, and exactly one `AdminDisableUser` for
  that username. It records reason `username-is-a-space`, and it returns the event.
- [ ] Unit: when the existing database is unmarked, the trigger grants and tags exactly as it does
  today, and disables nobody.
- [ ] Unit: when reading the existing database fails, there is no grant, no tag and no disable, and
  the recorded reason is `provisioning-failed`.
- [ ] Unit: the backfill run on a username whose database is space-marked exits non-zero, and its
  output names the collision. Another username in the same run is still provisioned.
- [ ] Unit: `teardown.owns_database`, `create_space` and `post_confirmation` all resolve the marker
  key to the one `cpcommon.config` constant, and no module declares a second literal of it.
- [ ] Deleting the marker read in `provision_user` turns the first criterion red, and the deletion
  is then reverted.

### FR-004: A space cannot be named after a user

#### Description:

`create_space` asks the pool about the requested name with `AdminGetUser` **before** `reg.reserve`.
The orchestrator role already holds that permission.

- **The user exists, in any status, unconfirmed included:** the create fails with
  `ProvisioningError("name already taken")` through the branch that already handles a reserve
  collision. That branch writes a failed cache entry with the friendly reason and sends a
  notification, and it touches no registry record. The sentence is the same one a taken space name
  produces, so the refusal does not say whether the name belongs to a user or a space.
- **Any pool answer other than `UserNotFoundException`:** the create fails as a retryable fault.
  It never reads the error as "no such user".

The check belongs in the verb, not in the API's create route. The API plane holds no pool read, and
in the successor the pool is keyed on a synthetic username. There, a user's database exists before
the user ever signs in, so the audit's marker check is what covers the forward door.

#### Acceptance Criteria:

- [ ] Unit, with fakes: creating a space named after an existing user leaves no registry record,
  makes no `AdminUpdateUserAttributes` call, writes no S3 prefix marker, and makes no Glue call. The
  actor's cache entry is `failed` with reason `name already taken`, and one notification is sent.
- [ ] Unit: the same holds for a user in `UNCONFIRMED` status.
- [ ] Unit: the refusal's cache reason and notification text are byte-identical to those of a
  create whose name is an existing space.
- [ ] Unit: an `AdminGetUser` fault other than `UserNotFoundException` fails the create as a
  retryable fault, and no registry record is written.
- [ ] Unit: a name with no pool user goes on to reserve and provision as it does today.

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

### FR-006: One read-only report says whether a collision already exists

#### Description:

A one-shot function in the shared-space plane runs under the orchestrator role. That role already
reads the registry, lists and reads pool users, and reads Glue databases as a Lake Formation admin.
A `workflow_dispatch` workflow shaped like `backfill-ever-active.yml` invokes it. It writes nothing,
and it reports four lists:

- (a) usernames equal to the name of a space in the registry, in any status;
- (b) users whose personal database carries a space's marker;
- (c) membership slots naming a space whose registry roster does not include that user, or naming
  a username. These are what a self-written slot looks like, and so are drift left by a failed
  rollback;
- (d) spaces in the registry whose database is unmarked. These predate the marker, and the list is
  for information only.

The workflow fails when (a), (b) or (c) has entries, or when any read failed. A read failure is
never reported as an empty list. List (d) on its own passes.

**Decision: no backfill marks the legacy databases.** A mark is what allows the teardown to drop a
database, so a marking backfill is the one new path that could bring back the data loss the audit
closed. The only evidence it could go on is circumstantial: the pool, the registry's `createdAt`
against Glue's `CreateTime`. Leaving them unmarked costs little and is safe. Tearing down a legacy
space leaves its database behind, as the audit accepted. With FR-002 that leftover database retires
the name for sign-ups too, so no one can inherit it. The population is small and temporary: there
are no production users, the current account is decommissioned at cutover, and spaces in the
successor are seeded by code that marks. List (d) tells an operator where every leftover is, so a
name can be dropped by hand if it is ever wanted back.

#### Acceptance Criteria:

- [ ] Unit, with fakes: each of (a), (b), (c) and (d) lists exactly the planted entries, and each
  has a case with nothing planted that produces an empty list.
- [ ] Unit: a failed registry, pool or Glue read makes the run fail and names the read. It never
  produces a list reported as clean.
- [ ] Unit: the function makes no write call to S3, Cognito, Glue or Lake Formation. The fakes
  record every call and the test asserts that none was a write.
- [ ] The workflow's exit status is non-zero when (a), (b) or (c) has entries, and zero when only
  (d) does. A test over the workflow or the function's result asserts both cases.
- [ ] The report is run once against the deployed account. The four counts are recorded in the
  delivery doc. Any entry in (a), (b) or (c) is handled by hand and recorded there before this spec
  closes.

---

## Data Model

```python
# lambdas/control-plane-common/cpcommon/config.py
DATABASE_MARKER_KEY: str = "dataquarry.shared-space"  # moved here; one declaration

# lambdas/post-confirmation/post_confirmation.py
class ExistingDatabase(enum.Enum):
    """What an already-existing database under the username turned out to be."""
    UNMARKED = "unmarked"      # own earlier attempt, or a pre-marker user database: carry on
    SPACE = "space"            # a space's database: grant nothing, disable in the trigger
    UNREADABLE = "unreadable"  # grant nothing, record provisioning-failed

# shared-space name-collision report result
class CollisionReport(TypedDict):
    usernames_that_are_spaces: list[str]             # (a)
    user_databases_marked_as_spaces: list[str]       # (b)
    unbacked_slots: list[dict[str, str]]             # (c) {"username", "slot", "value"}
    unmarked_space_databases: list[str]              # (d), informational
    failed_reads: list[str]                          # non-empty fails the run
```

## API / Interface Contract

No route changes. The browser changes nothing either: the create refusal arrives through the
existing failed card and notification, and the sign-up refusal is the trigger's message on the
managed-login page.

```text
pre-signup refusal (name exists or unreadable):  "That username is not available."
create refusal (user or space already holds it): "name already taken"   (unchanged sentence)
post-confirmation record on a space-marked db:   reason="username-is-a-space", username=<name>
```

## File & Folder Structure

```
infra/modules/auth/
├── cognito.tf                                    # FR-001 read/write attributes
└── policies/
    ├── pre-signup-permissions.json.tftpl         # FR-002 glue:GetDatabase
    └── post-confirmation-permissions.json.tftpl  # FR-003 cognito-idp:AdminDisableUser
infra/modules/shared-spaces/                      # FR-006 one-shot function under the orchestrator role
lambdas/
├── control-plane-common/cpcommon/config.py       # FR-003 marker key, one declaration
├── pre-signup/pre_signup.py                      # FR-002
├── post-confirmation/{post_confirmation,backfill}.py   # FR-003
├── shared-space-common/{config,teardown}.py      # FR-003 read the moved key
├── shared-space-create/create_space.py           # FR-004, FR-005
└── shared-space-name-collisions/                 # FR-006 (new, report only)
.github/workflows/report-name-collisions.yml      # FR-006
```

## Implementation Phases

### Phase 1: The slot is not writable (FR-001)

- Andrew runs the probe against the deployed pool, and the outcome is recorded.
- Add both attribute lists to the client, and the test over `cognito.tf`.
- Apply, re-run the probe, and run the member and email control.
- This phase depends on nothing else in the spec and is the most urgent. It lands on its own, first.

### Phase 2: IAM before the code that needs it

- `glue:GetDatabase` for the pre-signup role, and `cognito-idp:AdminDisableUser` for the
  post-confirmation role. Also whatever the deploy role needs to create the FR-006 function, read
  from `infra/info/deploy-role-iam.md` and `lambdas/info/deployment.md`.

### Phase 3: The create verb and provisioning (FR-003, FR-004, FR-005)

- Starts only once the audit commit is on `main`.
- Move the marker key into `cpcommon.config`.
- Put the pool check in front of reserve, and the database step in front of the slot.
- Classify the existing database in `provision_user`, and disable the user in the trigger.

### Phase 4: The sign-up door (FR-002)

- The Glue read in pre-signup, with its timeouts and its two sentences.
- The live checks: a fresh name is admitted, and a space's name is refused.

### Phase 5: The report (FR-006)

- The function, the workflow, and one run against the deployed account.
- Record the four counts, and handle any finding by hand.

### Phase 6: Where the decisions are written down

- A register entry in `docs/decisions/control-planes.md`, and one in
  `docs/decisions/identity-and-access.md`.
- Clauses in the identity fences. The slot claims are an authorization input only because the
  client cannot write them. A name is a user's or a space's, and pre-signup and create are the two
  doors.
- Mark as superseded, in place, `transition_plan.md` §6.1's "this repo's app client sets neither"
  and the sentence in §3.12 item 3 saying no fence exists.
- The `cognito.tf` slot comment, which FR-001 makes true, and `infra/modules/auth/README.md`.
