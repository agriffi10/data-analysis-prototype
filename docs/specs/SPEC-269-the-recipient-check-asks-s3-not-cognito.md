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
  provisioned this morning is unknown until tomorrow, and its decision says it is advisory and never
  an authorization input. The **SPEC-265 identity index** is keyed on the Entra object id, so asking
  it about a username means listing every entry; it also exists only in the bridge. The
  **provisioner's username list** has a shape, a delivery path and a refresh rule that are all still
  open Phase 0 questions (§3.12), and it exists only in the bridge. The marker is the thing §3.12
  defines a provisioned space to be, it is keyed on the username, it is one cheap request, and it
  already exists in both environments.
- **One source in both environments, not a switch.** A configuration switch between Cognito today and
  S3 in the bridge would leave the S3 path unexercised until the successor account, which is exactly
  the condition the plan's `MEMBERSHIP_SOURCE` item warns against for another authorization input.
  So the current environment moves too, and FR-004 closes its one gap: today the marker is written by
  the browser on a user's first visit to the file browser, so a confirmed user who has never opened
  it has none. `provision_user` gains the marker write as its first step, which is §3.12's "existing
  sequence plus the prefix marker write" arriving early, and an existing user is reconciled by
  re-running the backfill.
- **This is not a product change.** The three outcomes, the reasons a sender sees and the
  notifications are unchanged. The population a "yes" covers moves from "has a Cognito account" to
  "has a provisioned space". In the current environment, once FR-004 lands and the backfill has run,
  those are the same people except for one case: a sign-up whose marker write itself fails reads as
  unknown until the backfill re-runs or the user opens the file browser. Today such a user reads as
  existing. The failure is recorded as a provisioning failure, which already sends the operator to
  the backfill.

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
- Shared-space add-members asking the same question for every requested name before it touches any
  membership slot, so the existence answer no longer depends on the Cognito read the slot code
  happens to make.
- `provision_user` writing the marker first, the post-confirmation function's bucket variable, grant
  and timeout, its entry in the user-space bucket policy, and a backfill of existing users.

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
- **The username directory.** It stays advisory, and no control plane reads it. The marker is a
  different object, and nothing here reads `_directory/`.
- **The space recipient check** (`reg.may_receive_share` on the registry). It never touched Cognito.

---

## Functional Requirements

### FR-001: One shared lookup reads the user's prefix marker

#### Description:

A new module, `lambdas/control-plane-common/cpcommon/users.py`, holds `user_exists(username)`. It
replaces `cpcommon/cognito.py`, which is deleted, and `tscommon/cognito.py`, which is deleted rather
than re-pointed, because a re-export kept only for its name is how a second copy grows back.

1. A `username` that does not `fullmatch` `cpcommon.config.CATALOG_IDENTIFIER_RE` returns `False`
   with no request (`fullmatch`, because the pattern's `$` also matches before a final newline). This
   is a correctness rule, not tidiness: folders inside a user's space carry their own
   `DO_NOT_DELETE.txt` (saved queries and "New folder" both write one), so without it a recipient
   named `alice/reports` would read as existing because `alice/reports/DO_NOT_DELETE.txt` does. It
   also keeps the bucket's non-user top-level prefixes (`_config/`, `_directory/`) from ever reading
   as users.
2. Otherwise it sends `HeadObject` for `{username}/DO_NOT_DELETE.txt` on `USER_SPACE_BUCKET`.
3. A success returns `True`. A `404` (the client error code `404`, `NoSuchKey` or `NotFound`) returns
   `False`. Every other outcome, including `403`, a throttle and a network fault, raises
   `TransientError`. A `403` is deliberately not "unknown": S3 answers a missing key with `403` when
   the caller lacks `s3:ListBucket`, so a role missing that grant would otherwise report every
   recipient as nonexistent, quietly. Raising makes that misconfiguration fail loudly instead.

The marker's filename is the constant `PREFIX_MARKER_FILENAME` in `cpcommon/users.py`.
`lambdas/test_absence_is_answerable.py` finds the new `head_object` absence site, and its
`DISPOSITIONS` gains `cpcommon/users.py::user_exists` as `LIST_GRANT`, which FR-002 and FR-003's IAM
make true.

#### Acceptance Criteria:

- [ ] Against a stubbed S3 client: an existing marker returns `True`, a missing one returns `False`,
      and a `403`, a `SlowDown` and a connection error each raise `TransientError`. Each case asserts
      the request's bucket and key, not only the result.
- [ ] `user_exists("alice/reports")`, `user_exists("_directory")`, `user_exists("Al")` and
      `user_exists("alice\n")` return `False` and the stub records no request, while
      `alice/reports/DO_NOT_DELETE.txt` is present in the stub.
- [ ] `cpcommon/cognito.py` and `tscommon/cognito.py` no longer exist, and no module under `lambdas/`,
      tests included, imports either name or patches an attribute named `cognito` on a verb module
      (an import scan that counts attribute-style and aliased imports). The patch sites today are in
      both verbs' tests, `file-send-common/test_state_machine_file_send.py`,
      `control-plane-common/test_one_run_one_trace.py` and
      `control-plane-common/test_state_reads_match_verb_returns.py`.
- [ ] `user_exists` makes no Cognito call: the test patches `clients.cognito` to raise and every case
      still passes.

### FR-002: File send and table share resolve recipients through it, and lose their Cognito grant

#### Description:

`file_send_validate_authorize._annotate_recipients` and
`table_share_validate_authorize._annotate_recipients` call `cpcommon.users.user_exists`. The
outcomes are unchanged: `True` leaves the recipient valid, `False` annotates it `unknown_user`, and
`TransientError` propagates so the Step Function retries as it does today.

- The `RecipientUserCheck` statements are deleted from `infra/planes/file-send/execution.json.tftpl`
  and `infra/planes/table-share/execution.json.tftpl`, and the `user_pool_arn` entry they rendered is
  deleted from `infra/control-planes.tf`, which leaves it no consumer. Neither role needs a new S3
  grant: both already hold `s3:GetObject` on `${user_space_bucket_arn}/*` and an unconditioned
  `s3:ListBucket` on the bucket, and both are on the user-space bucket policy's allowlist.
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
- [ ] One end-to-end check per plane, against the real bucket in this account, after the backfill: a
      send to an existing user is delivered, and a send to a name with no prefix is reported to the
      sender as an unknown user. A run of each is recorded in `docs/testing/e2e.md`.
- [ ] SPEC-265's identity test, or SPEC-265 FR-005's text, allows no `cognito-idp:` action, per the
      rule above.

### FR-003: Adding shared-space members checks every name before any slot is touched

#### Description:

`add_members` resolves existence for every requested name that is not already on the roster, with
`cpcommon.users.user_exists`, **before** its slot loop begins. A name answering `False` goes to
`ignoredUnknown` with today's notification text and never reaches `membership.assign_or_find_slot`.
The slot loop then runs over the names that answered `True`, as today. Checking first is what makes
a `TransientError` safe: it is raised before any slot has been written, so the run fails the way a
Cognito fault fails it today and leaves nothing behind. The loop itself has no rollback, and a lookup
raised half way through it would leave earlier members' slots assigned. The plane's retry policy,
which retries only Lambda service errors, is unchanged.

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
- [ ] A request naming three members, where the lookup raises `TransientError` on the third, fails
      the run, and the Cognito fake records no slot write for any of the three.
- [ ] Rendered, the shared-spaces execution policy grants `s3:GetObject` on the marker pattern and on
      no new resource besides it.

### FR-004: Every provisioned user has a marker in the current environment

#### Description:

`provision_user` in `lambdas/post-confirmation/post_confirmation.py` writes the marker as its
**first** step, before the database, its Lake Formation grant and the tag. First, because §3.12
lists the marker as the first thing a provisioned space is, and because it makes "exists" mean "has
signed up" whatever happens to the Glue and Lake Formation steps after it. A Glue fault at sign-up
today leaves a Cognito account with no database, and that account reads as existing; written first,
the marker keeps that the same. A marker failure raises and stops the later steps, and the handler
records it as the provisioning failure it already records.

- The write is `PutObject` with `IfNoneMatch="*"` on `{username}/DO_NOT_DELETE.txt`. A `412` means a
  marker is already there and counts as success. A `409` (`ConditionalRequestConflict`, which S3
  returns when the browser's unconditional write lands at the same moment) is retried once, and the
  retry's `412` is then success. So the step is idempotent and does not race the browser's writer.
- **The constants stay local to `post_confirmation.py`.** `test_layer_import_safety.py` allows
  post-confirmation to import only `observability` from `cpcommon`, so it cannot import
  `cpcommon.users`. It keeps its own filename and body constants, and one test asserts the filename
  equals `cpcommon.users.PREFIX_MARKER_FILENAME` and `PREFIX_MARKER_FILENAME` in
  `apps/portal/src/features/file-browser/fileBrowser.constants.ts`, and the body equals that file's
  `PREFIX_MARKER_BODY`, byte for byte. Two writers of one key are safe only while both write the same
  bytes (§3.12).
- **The wiring.** The auth module gains a `user_space_bucket_name` variable, passed from
  `local.user_space_bucket_name`. The function's environment gains `USER_SPACE_BUCKET`, read with
  `os.environ` in `post_confirmation.py` and not through `cpcommon.config`. The role gains
  `s3:PutObject` on `arn:aws:s3:::{bucket}/*/DO_NOT_DELETE.txt` in
  `infra/modules/auth/policies/post-confirmation-permissions.json.tftpl`, and nothing else on the
  bucket. Its constructed ARN (`local.post_confirmation_exec_role_arn`) joins the allowlist in
  `infra/modules/data/policies/user-space-bucket-policy.json.tftpl`, threaded through
  `infra/modules/data/variables.tf`, `s3.tf` and the `module "data"` call in `infra/main.tf`, and
  `lambdas/test_user_space_bucket_allowlist.py`'s `EXPECTED_PRINCIPALS` gains it. Without the
  allowlist entry the bucket policy's explicit deny refuses the write at runtime with a green plan.
- **The timeout goes from 3 to 5 seconds.** One more request on a cold start is unmeasured at 3, and
  a trigger that times out fails the user's confirmation, which the handler's `except` cannot catch.
  Five seconds is the most Cognito waits for a trigger, so there is nothing to gain above it.
- **The backfill.** `backfill.py`'s docstring gains the reconciliation: list the pool's confirmed
  users, list the bucket's top-level prefixes that hold a marker, and run the backfill over the
  difference with `USER_SPACE_BUCKET` exported. It runs as the deploy role, which is both on the
  bucket's allowlist and a Lake Formation admin; an operator's own credentials are on neither. That
  run writes to the production bucket, so the build hands Andrew the exact commands rather than
  running them, and the PR records the run as owed until it is done.

#### Acceptance Criteria:

- [ ] `provision_user` against fakes writes the marker before the database, asserted as an order of
      calls, and a second run with the marker present succeeds on the `412` and writes nothing.
- [ ] A `409` followed by a `412` succeeds with exactly two write attempts. Any other write failure
      makes `provision_user` raise, and no Glue call is made.
- [ ] The mirror test fails when any one of the constants is edited alone (mutated once during the
      build and reverted).
- [ ] Rendered, the post-confirmation role grants exactly `s3:PutObject` on the marker pattern in the
      user-space bucket, the bucket policy's allowlist contains its ARN, and the function's
      environment contains `USER_SPACE_BUCKET` and its timeout is 5.
- [ ] A live sign-up in this account leaves a marker under the new user's prefix before they open
      the file browser, and the function's `REPORT` line for that cold start is recorded.
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

    Returns False for a name failing CATALOG_IDENTIFIER_RE.fullmatch (no request) or a 404.
    Raises TransientError on any other outcome, a 403 included.
    """
```

## Environment Variables

- `USER_SPACE_BUCKET` is added to the post-confirmation function, read with `os.environ`. The control
  planes already have it.
- `COGNITO_USER_POOL_ID` is removed from the file-send and table-share planes. The shared-spaces
  plane keeps it for its slot code.

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
├── post-confirmation/                  (provision_user, backfill docstring, tests, mirror test)
├── file-send-common/test_state_machine_file_send.py           (patch site)
├── control-plane-common/test_one_run_one_trace.py             (patch site)
├── control-plane-common/test_state_reads_match_verb_returns.py (patch site)
├── test_absence_is_answerable.py       (new disposition)
├── test_user_space_bucket_allowlist.py (new principal)
├── test_pool_id_reaches_its_readers.py (new reader set)
└── test_file_send_portal_grant.py      (no cognito-idp action)
infra/
├── control-planes.tf                                 (user_pool_arn deleted)
├── plane-file-send.tf, plane-table-share.tf          (pool id removed)
├── planes/file-send/execution.json.tftpl             (RecipientUserCheck deleted)
├── planes/table-share/execution.json.tftpl           (RecipientUserCheck deleted)
├── planes/shared-spaces/execution.json.tftpl         (marker read added)
├── main.tf                                           (auth and data module inputs)
├── modules/auth/lambda.tf, variables.tf              (bucket variable, environment, timeout)
├── modules/auth/policies/post-confirmation-permissions.json.tftpl  (marker write added)
├── modules/data/variables.tf, s3.tf                  (post-confirmation ARN threaded)
└── modules/data/policies/user-space-bucket-policy.json.tftpl       (post-confirmation role allowed)
```

## Implementation Phases

### Phase 1: The marker write (FR-004)

- `provision_user`'s new first step, its mirror test, the auth module's variable, environment,
  grant and timeout, and the bucket-policy allowlist entry. This is its own PR, deployed first,
  because an operator step sits between it and Phase 2: the backfill must have given every existing
  user a marker before any check reads one, or existing users read as unknown in the window. The
  backfill commands go to Andrew with it.

### Phase 2: The lookup and its callers (FR-001, FR-002, FR-003)

- `cpcommon/users.py`, the three callers, the deleted modules, the IAM changes on three planes, the
  updated guard tests, and SPEC-265's allowance. One PR: deleting `cpcommon/cognito.py` follows its
  last caller, so splitting it leaves either a dead module or a broken import.
- The end-to-end checks in FR-002, run after the deploy and after the backfill.

### Phase 3: Close-out

- The completion ritual. Rewrite SPEC-146's decision in place with a dated History entry: its fence
  names `admin_get_user` as where existence checks stay, and its body cites a directory tripwire test
  that #540 deleted. Mark the same existence claim at each other site that states it:
  `lambdas/info/planes/standalone.md`, `lambdas/info/planes/shared-spaces.md`,
  `infra/planes/file-send/README.md`, and the docstrings of `membership.py` and the file-send verb.
  Mark §3.12's item 1 and the Phase 1 provisioner bullet in `docs/transition_plan.md` as carrying the
  marker write in `provision_user` already, and strike the recipient-check bullet in SPEC-265's Out of
  Scope as done.
