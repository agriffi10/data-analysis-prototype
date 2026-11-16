---
type: Spec
id: SPEC-269
title: "The Recipient Check Asks S3, Not Cognito"
description: "Moves the control planes' 'does this user exist?' check off Cognito and onto the user's provisioned prefix marker in S3, so file send, table share and adding a shared-space member keep resolving recipients by portal username once the successor account's bridge pool keys Cognito on the Entra object id."
spec_status: Draft
depends_on: []
---

**Dependency notes:** none to build on. SPEC-265 (the bridge pool) names this spec in its Out of
Scope as one of three things that must land before its `entra_federation` flag is set anywhere; this
spec does not need SPEC-265 to have been built, and FR-002 says what changes in SPEC-265's guardrail
test depending on which of the two builds first. `docs/transition_plan.md` §3.12 (*Provisioning a
user without a signup*) is the design this spec leans on: a provisioned space is, first, the prefix
marker `{username}/DO_NOT_DELETE.txt`, written ahead of any sign-in by the provisioner. SPEC-146's
decision (*The username directory is built from S3, not Cognito*) carries the argument that S3
becomes the complete record of who exists after the transition, and this spec reverses the one
clause of it that kept existence checks on `admin_get_user`.

**Decided while authoring, 2026-11-16:**

- **The source is the prefix marker, read with `HeadObject`.** Three other candidates were weighed
  and refused. The **username directory** (`_directory/usernames.json`) is rebuilt daily, so a user
  provisioned this morning is unknown until tomorrow, and its decision fences it as advisory and
  never read by a control plane, with a tripwire test holding that. The **SPEC-265 identity index**
  is keyed on the Entra object id, so asking it about a username means listing every entry; it also
  exists only in the bridge. The **provisioner's username list** has a shape, a delivery path and a
  refresh rule that are all still open Phase 0 questions (§3.12), and it exists only in the bridge.
  The marker is the thing §3.12 defines a provisioned space to be, it is keyed on the username, it is
  one cheap request, and it already exists in both environments.
- **One source in both environments, not a switch.** A configuration switch between Cognito today and
  S3 in the bridge would leave the S3 path unexercised until the successor account, which is exactly
  the condition the plan's `MEMBERSHIP_SOURCE` item warns against for another authorization input.
  So the current environment moves too, and FR-004 closes its one gap: today the marker is written by
  the browser on a user's first visit to the file browser, so a confirmed user who has never opened
  it has none. `provision_user` gains the marker write, which is §3.12's "existing sequence plus the
  prefix marker write" arriving early, and an existing user is reconciled by re-running the backfill.
- **This is not a product change.** The three outcomes, the reasons a sender sees and the
  notifications are unchanged. The population a "yes" covers moves from "has a Cognito account" to
  "has a provisioned space", and in the current environment, once FR-004 lands, those are the same
  people.

## Overview

When someone sends files or shares a table with a colleague, or adds a colleague to a shared space,
the portal first checks that the colleague exists. Today it asks Cognito, by portal username. In the
client's environment Cognito is only a bridge to Entra ID, and its usernames are a provider prefix
and an Entra object id rather than portal usernames, so that question would answer "no such user"
for everybody. This spec asks a different question that means the same thing in both environments:
does this person have a provisioned personal space? A provisioned space always carries a small marker
file at the root of the user's folder, written before the person ever signs in, so asking for that
file is a reliable and cheap test. The sender sees the same outcomes as today: the recipient is
reached, the recipient is reported as unknown, or a temporary fault is retried rather than being
misreported as "no such user".

## Scope

### In Scope

- One shared lookup, `cpcommon.users.user_exists`, that reads the marker and keeps the three-way
  classification. It replaces `cpcommon.cognito.user_exists` and the `tscommon.cognito` re-export.
- File send's and table share's recipient checks moved onto it, their `RecipientUserCheck` Cognito
  grants deleted, and `COGNITO_USER_POOL_ID` removed from both planes.
- Shared-space add-members asking the same question before it touches a membership slot, so the
  existence answer no longer depends on the Cognito read the slot code happens to make.
- `provision_user` writing the marker, the post-confirmation role's grant and its entry in the
  user-space bucket policy, and a backfill of existing users.

### Out of Scope

- **The shared-spaces plane's slot writes.** `membership.assign_or_find_slot` and `clear_slot` keep
  reading and writing `custom:shared_space_k` in Cognito in the current environment. Stopping them is
  the Phase 1 item *Wire `MEMBERSHIP_SOURCE` to the index*, which SPEC-265's Out of Scope names
  separately. FR-003 only takes the existence question away from them, so that item can delete the
  Cognito read without losing it.
- **The provisioner itself** (§3.12): its trigger, its list reader and its refusals. FR-004 puts the
  marker write into `provision_user`, which the provisioner reuses, and nothing more.
- **De-provisioning.** A leaver keeps a marker, so they stay a valid recipient, as they keep a
  directory entry and a prefix. §3.12 records that nothing owns de-provisioning yet; the recipient
  check inherits whatever that owner decides and needs no change of its own.
- **The browser's `ensurePrefixMarker`.** It keeps writing the same constant on a first visit until
  the cutover removes it (§6.3). Two writers of one key are safe because both write the same bytes,
  which FR-004's mirror test holds.
- **The username directory.** It is still advisory and still read by no control plane. The marker is
  not the directory, and the tripwire test that fences the directory's path and constants is
  unchanged.
- **The space recipient check** (`reg.may_receive_share` on the registry). It never touched Cognito.

---

## Functional Requirements

### FR-001: One shared lookup reads the user's prefix marker

#### Description:

A new module, `lambdas/control-plane-common/cpcommon/users.py`, holds `user_exists(username)`. It
replaces `cpcommon/cognito.py`, which is deleted, and `tscommon/cognito.py`, which is deleted rather
than re-pointed, because a re-export kept only for its name is how a second copy grows back.

1. A `username` that does not `fullmatch` `cpcommon.config.CATALOG_IDENTIFIER_RE` returns `False`
   with no request (`fullmatch`, because the pattern's `$` also matches before a final newline). This is a correctness rule, not tidiness: folders inside a user's space carry their own
   `DO_NOT_DELETE.txt`, so without it a recipient named `alice/reports` would read as existing
   because `alice/reports/DO_NOT_DELETE.txt` does. It also keeps the bucket's non-user top-level
   prefixes (`_config/`, `_directory/`) from ever reading as users.
2. Otherwise it sends `HeadObject` for `{username}/DO_NOT_DELETE.txt` on `USER_SPACE_BUCKET`.
3. A success returns `True`. A `404` (the client error code `404`, `NoSuchKey` or `NotFound`) returns
   `False`. Every other outcome, including `403`, a throttle and a network fault, raises
   `TransientError`. A `403` is deliberately not "unknown": S3 answers a missing key with `403` when
   the caller lacks `s3:ListBucket`, so a role missing that grant would otherwise report every
   recipient as nonexistent, quietly. Raising makes that misconfiguration fail loudly instead.

The marker's filename is one constant, `PREFIX_MARKER_FILENAME`, in `cpcommon/users.py`, and FR-004's
writer imports it from there.

#### Acceptance Criteria:

- [ ] Against a stubbed S3 client: an existing marker returns `True`, a missing one returns `False`,
      and a `403`, a `SlowDown` and a connection error each raise `TransientError`. Each case asserts
      the request's bucket and key, not only the result.
- [ ] `user_exists("alice/reports")`, `user_exists("_directory")`, `user_exists("Al")` and
      `user_exists("alice\n")` return
      `False` and the stub records no request, while `alice/reports/DO_NOT_DELETE.txt` is present in
      the stub.
- [ ] `cpcommon/cognito.py` and `tscommon/cognito.py` no longer exist, and no module under `lambdas/`
      imports either name (an import scan that counts attribute-style and aliased imports).
- [ ] `user_exists` makes no Cognito call: the test patches `clients.cognito` to raise and every case
      still passes.

### FR-002: File send and table share resolve recipients through it, and lose their Cognito grant

#### Description:

`file_send_validate_authorize._annotate_recipients` and
`table_share_validate_authorize._annotate_recipients` call `cpcommon.users.user_exists`. The
outcomes are unchanged: `True` leaves the recipient valid, `False` annotates it `unknown_user`, and
`TransientError` propagates so the Step Function retries as it does today.

- The `RecipientUserCheck` statements are deleted from `infra/planes/file-send/execution.json.tftpl`
  and `infra/planes/table-share/execution.json.tftpl`. Neither role needs a new S3 grant: both
  already hold `s3:GetObject` on `${user_space_bucket_arn}/*` and an unconditioned `s3:ListBucket`
  on the bucket, and both are on the user-space bucket policy's allowlist.
- `COGNITO_USER_POOL_ID` is removed from `infra/plane-file-send.tf` and `infra/plane-table-share.tf`,
  and `lambdas/test_pool_id_reaches_its_readers.py` is updated to the new set of readers, which is
  the shared-spaces plane alone.
- `lambdas/test_file_send_portal_grant.py`'s Cognito assertion becomes "no `cognito-idp:` action".
- `_MAX_RECIPIENT_NAME` stays as a request-shape cap, and its docstring is rewritten to say so. Its
  current reason, that `AdminGetUser` rejects a longer name as a fault the lookup would classify as
  transient, stops being true.
- **SPEC-265's guardrail test.** SPEC-265 FR-005 allows `cognito-idp:AdminGetUser` and `ListUsers`
  in its identity test as "the reads the recipient checks use". After this FR no recipient check uses
  them. If `lambdas/test_portal_roles_cannot_rewrite_identity.py` exists when this spec builds, the
  build removes those two actions from its allowance in the same PR. If it does not, the build
  amends SPEC-265 FR-005's bullet to allow no `cognito-idp:` action.

#### Acceptance Criteria:

- [ ] Each verb's existing recipient tests pass with `users.user_exists` patched where
      `cognito.user_exists` was, and a new case per verb shows a `TransientError` from the lookup
      propagating out of the handler rather than being annotated `unknown_user`.
- [ ] Rendered, neither plane's execution policy contains any `cognito-idp:` action, and neither
      plane's Lambda environment contains `COGNITO_USER_POOL_ID`.
- [ ] One end-to-end check per plane, against the real bucket in this account: a send to an existing
      user with a marker is delivered, and a send to a name with no prefix is reported to the sender
      as an unknown user. A run of each is recorded in `docs/testing/e2e.md`.
- [ ] SPEC-265's identity test, or SPEC-265 FR-005's text, allows no `cognito-idp:` action, per the
      rule above.

### FR-003: Adding a shared-space member asks the same question first

#### Description:

`add_members` calls `cpcommon.users.user_exists(member)` before
`membership.assign_or_find_slot`. `False` puts the name in `ignoredUnknown` with today's
notification text, and no slot is read or written for it. `True` goes on to the slot assignment
as today. `TransientError` fails the run the way a Cognito fault fails it today: the plane's retry
policy, which retries only Lambda service errors, is unchanged, and the run's existing failure path
releases the grants it made.

The existing `UserNotFoundException` branch around `assign_or_find_slot` stays. In the current
environment a name can have a marker and no Cognito account (an account deleted from the pool by
hand), and that name is still reported unknown rather than failing the run. That branch goes with the
slot writes, in the `MEMBERSHIP_SOURCE` work.

The shared-spaces execution role gains one statement, `s3:GetObject` on
`${user_space_bucket_arn}/*/DO_NOT_DELETE.txt`. It already holds an unconditioned `s3:ListBucket` on
the user-space bucket (Sid `UserSpaceCacheList`), so a missing marker answers `404`, and its
orchestrator role is already on the bucket policy's allowlist.

#### Acceptance Criteria:

- [ ] A member with no marker lands in `ignoredUnknown` with the existing notification, and the
      Cognito fake records no `admin_get_user` call for them.
- [ ] A member with a marker and a Cognito account is added exactly as before.
- [ ] A member with a marker and no Cognito account lands in `ignoredUnknown`.
- [ ] A `TransientError` from the lookup fails the run, and the grants already made for earlier
      members in the same request are released, asserted on the fakes.
- [ ] Rendered, the shared-spaces execution policy grants `s3:GetObject` on the marker pattern and on
      no new resource besides it.

### FR-004: Every provisioned user has a marker in the current environment

#### Description:

`provision_user` in `lambdas/post-confirmation/post_confirmation.py` writes the marker as a new step,
after the database and its Lake Formation grant and before the tag. After the database, so a marker
means the database the table share writes into was created; before the tag, because §3.12 keeps the
tag last so a tagging failure costs only table-creation rights.

- The write is `PutObject` with `If-None-Match: *` on `{username}/DO_NOT_DELETE.txt`. A `412` means a
  marker is already there and counts as success, so the step is idempotent and does not race the
  browser's writer.
- The body is a Python constant equal byte for byte to `PREFIX_MARKER_BODY` in
  `apps/portal/src/features/file-browser/fileBrowser.constants.ts`, because two writers of one key
  are safe only while both write the same bytes (§3.12). A test reads the TypeScript file and asserts
  the two are equal.
- The post-confirmation role gains `s3:PutObject` on `${user_space_bucket_arn}/*/DO_NOT_DELETE.txt`
  in `infra/modules/auth/policies/post-confirmation-permissions.json.tftpl` and nothing else on the
  bucket, and its constructed ARN (`local.post_confirmation_exec_role_arn`) joins the allowlist in
  `infra/modules/data/policies/user-space-bucket-policy.json.tftpl`. Without the allowlist entry the
  bucket policy's explicit deny refuses the write at runtime with a green plan.
- `backfill.py`'s docstring gains the reconciliation: list the pool's confirmed users, list the
  bucket's top-level prefixes that hold a marker, and run the backfill over the difference. That run
  writes to the production bucket, so the build hands Andrew the exact commands rather than running
  them, and the PR records the run as owed until it is done.

#### Acceptance Criteria:

- [ ] `provision_user` against fakes writes the marker after the grant and before the tag, asserted
      as an order of calls, and a second run with the marker present succeeds on the `412` and writes
      nothing.
- [ ] A marker write failing with anything but `412` makes `provision_user` raise, and the tag step
      does not run.
- [ ] The mirror test fails when either body constant is edited alone (mutated once during the build
      and reverted).
- [ ] Rendered, the post-confirmation role grants exactly `s3:PutObject` on the marker pattern in the
      user-space bucket, and the bucket policy's allowlist contains its ARN.
- [ ] After the backfill run, every confirmed user in the pool has a marker, by the two listings
      above showing no difference. Owed until Andrew runs it.

---

## How it behaves in each environment

| | Current environment (`entra_federation` unset) | Successor account (bridge pool) |
|---|---|---|
| Who writes a marker | `provision_user` at sign-up (FR-004), the browser on first visit, and the backfill for earlier users | The provisioner's run of `provision_user` over the username list, before anyone signs in (§3.12) |
| A recipient reads as existing when | they have signed up | they are on the provisioned list, whether or not they have ever signed in |
| Cognito's part | none in the check; the shared-spaces slot code still reads and writes the pool | none |
| A name not yet provisioned | unknown, as today | unknown, until the provisioner runs for them |

---

## Data Model

```python
# lambdas/control-plane-common/cpcommon/users.py
PREFIX_MARKER_FILENAME = "DO_NOT_DELETE.txt"

def user_exists(username: str) -> bool:
    """True when {username}/DO_NOT_DELETE.txt exists in USER_SPACE_BUCKET.

    Returns False for a name failing CATALOG_IDENTIFIER_RE (no request) or a 404.
    Raises TransientError on any other outcome, a 403 included.
    """
```

## Environment Variables

None new. `COGNITO_USER_POOL_ID` is removed from the file-send and table-share planes; the
shared-spaces plane keeps it for its slot code. `USER_SPACE_BUCKET` is already fleet-wide.

## File & Folder Structure

```
lambdas/
├── control-plane-common/cpcommon/
│   ├── cognito.py                      (deleted)
│   ├── users.py                        (new)
│   └── test_users_cpcommon.py          (new)
├── table-share-common/tscommon/cognito.py   (deleted)
├── file-send-validate-authorize/       (caller and tests)
├── table-share-validate-authorize/     (caller and tests)
├── shared-space-add-members/           (caller and tests)
├── post-confirmation/                  (provision_user, backfill docstring, tests)
├── test_pool_id_reaches_its_readers.py (new reader set)
└── test_file_send_portal_grant.py      (no cognito-idp action)
infra/
├── plane-file-send.tf, plane-table-share.tf          (pool id removed)
├── planes/file-send/execution.json.tftpl             (RecipientUserCheck deleted)
├── planes/table-share/execution.json.tftpl           (RecipientUserCheck deleted)
├── planes/shared-spaces/execution.json.tftpl         (marker read added)
├── modules/auth/policies/post-confirmation-permissions.json.tftpl  (marker write added)
└── modules/data/policies/user-space-bucket-policy.json.tftpl       (post-confirmation role allowed)
```

## Implementation Phases

### Phase 1: The marker write (FR-004)

- `provision_user`'s new step, its mirror test, the post-confirmation grant and the bucket-policy
  allowlist entry. This is its own PR, deployed first, because an operator step sits between it
  and Phase 2: the backfill must have given every existing user a marker before any check reads
  one, or existing users read as unknown in the window. The backfill commands go to Andrew with it.

### Phase 2: The lookup and its callers (FR-001, FR-002, FR-003)

- `cpcommon/users.py`, the three callers, the deleted modules, the IAM changes on three planes, the
  updated guard tests, and SPEC-265's allowance. One PR: deleting `cpcommon/cognito.py` follows its
  last caller, so splitting it leaves either a dead module or a broken import.
- The end-to-end checks in FR-002, run after the deploy and after the backfill.

### Phase 3: Close-out

- The completion ritual. Rewrite SPEC-146's decision in place (its fence names `admin_get_user` as
  where existence checks stay) with a dated History entry, and mark the same claim at each other site
  that states it: `lambdas/info/planes/standalone.md`, `lambdas/info/planes/shared-spaces.md`,
  `infra/planes/file-send/README.md`, `cpcommon`'s and `membership.py`'s docstrings. Mark §3.12's item
  1 and the Phase 1 provisioner bullet in `docs/transition_plan.md` as carrying the marker write in
  `provision_user` already, and strike the recipient-check bullet in SPEC-265's Out of Scope as
  done.
