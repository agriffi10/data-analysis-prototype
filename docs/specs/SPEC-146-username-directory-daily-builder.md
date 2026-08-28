# Spec: Username Directory — Daily Builder Lambda & Published Index

**ID:** SPEC-146
**Status:** Completed
**Last Updated:** 2026-08-03
**Depends On:** SPEC-107 (`cpcommon` — `observability`, `clients`, `config`), SPEC-126 (the scheduled-sweep Lambda pattern this copies), SPEC-137 (the singleton-Lambda shape and its cold-start trap), SPEC-013 (the user-space bucket policy and its principal allowlist)

> **Reference:** first of the username-directory arc (146 → 147 → 148).
>
> **This is a new AWS resource type in a new module, so the `CLAUDE.md` infra rule binds:** the deploy role's IAM expands as in-scope work, and `docs/architecture.md` → *Deploy-role IAM — adding a new resource type* and *Lambda code/infra split* are read **first**. **This spec ships as two PRs** — the deploy-role grant applies before the module's resources, the same sequencing every foundation spec in this repo has used.
>
> **Source decision, settled 2026-08-03 (user decision, after reading `docs/transition_plan.md`).** The directory is built from **S3 common prefixes on the user-space bucket**, not from Cognito `ListUsers`. FR-001 carries the reasoning, and it is worth reading before proposing the alternative, because the obvious objection to S3 today is real and stops being true after the transition.
>
> **Rulebooks:** `lambdas/info/best-practices/lambdas/lambdas.md`.

## Overview

Everywhere the portal asks a user to name another user — adding members to a shared space, choosing who to share a table with — it asks by free text. The user types a username into a box, the browser drops anything failing the catalog-safe pattern, and the request goes to a control plane that checks the name against the User Pool.

What happens next is better than it is usually described. `add_members.py` catches `UserNotFoundException` and **notifies the space owner by name** — *"Couldn't add ‘bob' to ‘sales': no such user."* — and table-share reports unresolved recipients too. So a typo is not silently lost. But it is learned **late, asynchronously, and by the wrong person**: the notification lands minutes later, only the owner sees it, and the colleague you were trying to add is still not in the space. Every typo costs a full round trip through an async control plane to discover something the browser could have flagged as you typed.

(Worth fixing while here: `add_members.py`'s **module docstring still says unknown users are "silently ignored"**, which the code has not done since the notification was added. `parseMemberInput`'s docstring says the same. Both are stale and are corrected as part of this arc — a wrong comment about error handling is how a design gets built on a premise that is no longer true. This spec was very nearly one of them.)

The fix is to let people pick a name rather than remember one. That needs a list of existing usernames, available to the browser cheaply. This spec builds the list: a Lambda that runs once a day, enumerates the personal workspaces, and publishes a small sorted JSON document to a reserved location the portal role can read. SPEC-147 turns it into a search; SPEC-148 puts it in front of users.

The list is deliberately **advisory**. It is up to a day stale, it never becomes an authorization input, and it never gates what a user may type. Its only job is to make the common case — the person you are adding exists and you nearly know how to spell their name — fast and correct the first time.

---

## Scope

### In Scope

- **A new module `infra/modules/user-directory/`** with one Lambda, one EventBridge schedule rule, one role, one log group.
- **A daily `rate(24 hours)` schedule.**
- **`lambdas/user-directory-build/build_directory.py`** — list the user-space bucket's top-level common prefixes, filter to catalog-safe names, sort, publish.
- **The published document** at `s3://{user-space-bucket}/_directory/usernames.json`.
- **One new statement on the portal role** granting `s3:GetObject` on `_directory/*` and nothing else.
- **The builder role added to the user-space bucket policy's principal allowlist.**
- **Deploy-role IAM** — a new `.tftpl` under `infra/modules/base/policies/`, attached in `infra/modules/base/iam.tf`.
- **The deploy-matrix row.**
- **Observability** per SPEC-130's rules, with an event count that is O(1) in users.
- **Correcting the two stale docstrings** in `lambdas/shared-space-add-members/add_members.py` and `apps/portal/src/features/shared-spaces/memberInput.ts` — both still claim unknown users are silently ignored.
- **A manual-invoke path** so the directory can be rebuilt on demand without waiting a day.

### Out of Scope

- **Any browser code**, with two named exceptions: the stale `parseMemberInput` docstring, and the one-line addition of `_directory` to `protectedFolders.ts` in FR-003. Both are listed in In Scope. Anything else under `apps/portal/` belongs to SPEC-147 or SPEC-148.
- **The stale user-facing copy in `AddMembersDialog.tsx`** — "Unknown usernames are ignored." is the same false claim as the two docstrings, but it is rendered text in a dialog SPEC-148 rewrites, so **SPEC-148 FR-005 owns it**. Fixing it here would mean touching a component this arc replaces two specs later.
- **Cognito `ListUsers`.** FR-001 records why. Do not add it as a union "to be safe" — a second source with different completeness properties is a second thing to reason about every time the directory looks wrong.
- **Display names, email addresses or any profile data.** The document holds usernames and nothing else. An email is not metadata under this repo's field rule (`decisions/`) and has no place in a document every authenticated user can read.
- **Shared-space names.** Bucket 2's prefixes are spaces, not users. `TableShareDialog` can target either, and a space directory is a reasonable follow-up, but it is a different list from a different bucket with different membership semantics — and shipping both at once would make the "what am I looking at" question harder in exactly the component that must be unambiguous.
- **Removing a user from the directory when their prefix is deleted.** The document is rebuilt from scratch every day; there is no incremental state and nothing to reconcile.
- **Any authorization use.** The directory is never read by a control plane and never becomes a membership check. A test enforces this.
- **Changing how unknown users are handled server-side.** The notifications `add_members` and table-share already emit stay exactly as they are.
- **Notifications.** Nobody is told when the directory is rebuilt.

---

## Functional Requirements

### FR-001: The source is S3 common prefixes on the user-space bucket

#### Description

**The decision, and why it changes.** Today, Cognito is the complete record of who exists and S3 is not: the personal prefix is created **by the browser**, by `ensurePrefixMarker` on the first visit to `/files` (SPEC-014, a deliberate decision to avoid a backend). A confirmed user who has never opened the file browser has no prefix and would be invisible to an S3-derived list. On that reading, Cognito wins.

The transition reverses it. `docs/transition_plan.md` §2 item 7 settles that **sign-in provisions nothing**: the sync pre-creates every existing user's space and database, the client's automation creates them for new users, and `ensurePrefixMarker` is deleted outright (§6.3). At the same time, federated login makes `cognito:username` a **synthetic** `identitycenter_<subject>` value rather than the catalog-safe username (§6.1), and users appear in the User Pool only after their first sign-in. So after the transition S3 becomes complete and Cognito becomes both incomplete and wrong-keyed.

Choosing the source that is right on the far side of a migration already in flight beats choosing the one that is right today, particularly when today's gap is bounded: pre-production, no production users, and the failure mode is a name missing from a suggestion list that still accepts free text.

**The residual gap is stated rather than engineered around.** Until the transition lands, a confirmed user who has never opened the Files browser is absent from the directory. They can still be added — every consumer accepts a name that is not in the list (SPEC-147 FR-005) — and the pipeline still validates against the User Pool and still notifies on an unknown name exactly as it does today. The directory makes the common case fast; it does not become the definition of who exists.

#### Acceptance Criteria:

- [ ] The Lambda pages `ListObjectsV2(Bucket=USER_SPACE_BUCKET, Delimiter="/")` and collects `CommonPrefixes`.
- [ ] Each prefix has its trailing `/` stripped and is kept only if it matches `cpcommon.config.CATALOG_IDENTIFIER_RE`. Anything else — including `_directory` — is dropped, and the count of dropped entries is logged as a field.
- [ ] The result is sorted ascending and de-duplicated.
- [ ] The Lambda makes **no Cognito call**. A test asserts `cognito` is never imported or clientised in this module.
- [ ] A comment at the top of the module records the source decision and points at `transition_plan.md` §2 item 7 and §6.1, so the next reader does not "fix" it back to `ListUsers`.
- [ ] Pagination is exercised by a test with more than one page of common prefixes.

### FR-002: The published document

#### Description

A plain sorted array. Not a serialised trie: the trie belongs in the browser, where it is built once per session from this list (SPEC-147 FR-002). Shipping a serialised trie would make the artifact several times larger, unreadable to a human debugging it, and coupled to one consumer's data structure — and the browser has to walk the whole document anyway to build any index at all.

#### Acceptance Criteria:

- [ ] The object is written to `s3://{USER_SPACE_BUCKET}/_directory/usernames.json` with `ContentType: application/json`.
- [ ] The body is `{"version": 1, "generatedAt": "<ISO-8601 UTC>", "count": <n>, "usernames": [...]}` — sorted ascending.
- [ ] `version` is present from day one so SPEC-147 can refuse a shape it does not understand rather than crashing on it.
- [ ] The write is a plain `PutObject` — **no ETag CAS**, because there is exactly one writer on a 24-hour schedule and the correct behaviour on a concurrent write is last-wins. A comment records this so it does not get "hardened" into the CAS pattern the log sweep and the shared-space registry correctly use for a different reason.
- [ ] **No `Cache-Control` is set.** The browser fetches this through the S3 SDK with SigV4, not through CloudFront, and whether an HTTP cache directive affects an SDK-issued request is not a property this repo should be relying on. SPEC-147's TanStack `staleTime` is the caching mechanism, and it is the only one.
- [ ] **An empty result never overwrites a non-empty document.** If the listing yields zero usernames, the Lambda logs an error event and exits without writing. A bucket-listing failure returning an empty page would otherwise erase the directory, and an empty directory is indistinguishable to a user from a broken feature.
- [ ] A test covers the empty-result guard.

### FR-003: `_directory/` is a reserved root prefix

#### Description

The user-space bucket has an invariant worth naming before breaking it: **every top-level prefix is a username**. This spec adds the first exception, and it is safe for one specific reason — `CATALOG_IDENTIFIER_RE` requires a leading lowercase letter, so `_directory` can never *be* a username. It is chosen precisely because it cannot collide.

#### Acceptance Criteria:

- [ ] A comment on the bucket resource in `infra/modules/data/s3.tf` records the exception and its reasoning.
- [ ] The builder excludes `_directory` from its own output (covered by FR-001's regex filter; a test names it explicitly).
- [ ] `_directory` is added to the **three** reserved-name lists that govern what a user may create or see inside their own space: `dqcommon.config.RESERVED_PREFIXES`, and **both** SPA lists in `apps/portal/src/features/file-browser/protectedFolders.ts` — `PICKER_LOCKED_FOLDERS` **and `HIDDEN_BROWSER_FOLDERS`** (that file's own header argues an internal folder needs both: hiding it from the listing alone leaves it a valid move/copy paste target). These are per-user-prefix rather than bucket-root, so the addition is defensive rather than necessary — but `transition_plan.md` §6.3 records that the lists have already diverged from each other, and adding to both is cheaper than reasoning about which one matters. (§6.3 names a third, the SPEC-116 file-converter blocklist; **that arc is Cancelled and the list does not exist in code**, so there is nothing to update there.)
- [ ] `transition_plan.md` §6.3's reserved-prefix table gains `_directory` in the relevant **Contents** cells — its rows are locations, not prefixes, so this is not a new row. The sync must not land client data there.
- [ ] The portal role's existing `ListBucket` grant is **conditioned on the caller's own prefix** and is not widened, so `_directory/` is invisible to the file browser's listing. A comment records that the file browser therefore needs no change.

### FR-004: The browser can read it, and nothing else

#### Acceptance Criteria:

- [ ] `infra/modules/data/policies/portal-role-permissions.json.tftpl` gains **one** statement: `s3:GetObject` on `${bucket_arn}/_directory/*`.
- [ ] No `ListBucket` is added, no `PutObject`, no access to any other new prefix. A user cannot enumerate `_directory/` and cannot write to it.
- [ ] The existing prefix-conditioned `ListBucket` and the `Deny` on `DO_NOT_DELETE.txt` are untouched.
- [ ] `aws iam simulate-custom-policy` confirms the portal role can `GetObject` on `_directory/usernames.json`, cannot `PutObject` there, and still cannot `GetObject` under another user's prefix.
- [ ] The document is readable by **every authenticated portal user**, and that is the intended and accepted disclosure: a username is already the S3 prefix, the principal tag and the Glue database name (SPEC-033), it is already visible on every shared-space roster (SPEC-075), and a prefix-search feature discloses the set by construction. Recorded in `decisions/` rather than left implicit.

### FR-005: The builder role and the bucket policy

#### Description

`infra/modules/data/policies/user-space-bucket-policy.json.tftpl` denies every S3 data action except for an explicit `aws:PrincipalArn` allowlist. A new writer that is not on it fails with an opaque `AccessDenied` that looks like an IAM problem and is not. The comment recording that this has bitten the repo three times (#241) lives in `infra/modules/observability/iam.tf:48-52` — **not** in `data/s3.tf`, which carries the allowlist rationale instead.

#### Acceptance Criteria:

- [ ] A dedicated role `{project}-{env}-user-directory-build` is created in the new module, with a permission policy rendered from a `.tftpl`.
- [ ] Its permissions are exactly: `s3:ListBucket` on the user-space bucket; `s3:PutObject` on `${bucket_arn}/_directory/*`; `sqs:SendMessage` on the logs queue; and `logs:CreateLogStream` + `logs:PutLogEvents` on its own log group — the two-action pair every comparable role in this repo grants, **not** `logs:*`, which the SPEC-139 rendered-plan Checkov scan would flag in the same PR that FR-009 requires to stay green.
- [ ] The `ListBucket` grant is **deliberately unconditioned**, and what that actually grants is stated rather than minimised. `Delimiter="/"` is a property of the Lambda's *code*, not of the grant, so an unconditioned `ListBucket` lets this role **enumerate every object key under every user's prefix** — not merely the top-level common prefixes it asks for. That is accepted, for three reasons taken together: the role holds **no `s3:GetObject` anywhere**, so it can list key names and read nothing; key names are metadata, which this repo's field rule already treats as loggable and non-sensitive; and it is a Lambda role with no user-assumable path. A comment records both the capability and the acceptance.
- [ ] The obvious tightening — a `s3:prefix` condition scoped to the empty string — is **rejected, not overlooked**. Whether botocore serialises an empty `Prefix` into a condition key at all is an AWS implementation detail; if it does not, a `StringEquals` on `""` fails closed and the role's only listing call breaks. And `simulate-custom-policy` will agree with whatever context key the author supplies, so the check would confirm an assumption rather than test it. If a future change makes this grant uncomfortable, the sound fix is a separate bucket for the directory, not a condition key whose presence cannot be verified.
- [ ] It carries **no** `s3:GetObject` and **no** `s3:DeleteObject` anywhere.
- [ ] The role's ARN is added to the allowlist in `user-space-bucket-policy.json.tftpl` as a **constructed string in root `locals`**, not a module output — an unknown element in that list silently drops the change, the same trap the analytics LF-admin list documents. The module therefore exposes **no `role_arn` output** for this purpose.
- [ ] `aws iam simulate-custom-policy` confirms the role can list the bucket and put to `_directory/`, and cannot get any object anywhere.

### FR-006: Schedule and manual invocation

#### Acceptance Criteria:

- [ ] An `aws_cloudwatch_event_rule` named `{function_name}-schedule` with `schedule_expression = "rate(24 hours)"`, an `aws_cloudwatch_event_target` pointing at the function, and an `aws_lambda_permission` with `principal = "events.amazonaws.com"` and `source_arn` set to the rule — the resource-policy path, matching SPEC-126, with no invoke role.
- [ ] The handler ignores its event payload entirely, so a manual `aws lambda invoke` with `{}` produces a full rebuild. The delivery doc records the exact command.
- [ ] The function is idempotent: two runs in a row produce the same document apart from `generatedAt`. A test asserts this.
- [ ] Timeout 300 s, memory 512 MB, `runtime = "python3.12"`, log group at 14-day retention, `archive_file` placeholder zip whose body raises, and `lifecycle { ignore_changes = [filename, source_code_hash, layers] }`.

### FR-007: The directory is never an authorization input

#### Acceptance Criteria:

- [ ] No control-plane verb reads `_directory/usernames.json`. A test greps the Lambda tree and fails if any module outside `user-directory-build` references the path or the object name.
- [ ] Every existing existence check stays as it is — `admin_get_user` against the User Pool, in `shared-space-common/membership.py` and `tscommon/cognito.py` — and so does every unknown-user notification.
- [ ] A comment in `build_directory.py` states plainly that the document is advisory and that a name's presence in it grants nothing.

### FR-008: Observability

#### Acceptance Criteria:

- [ ] `cpcommon.observability.init(service="user-directory")` and `@observability.traced("build-directory")` as the outermost decorator.
- [ ] The event count is **O(1) in the number of users** — one root span plus a bounded number of `info` events. A test fails if a per-username emitter is added, mirroring SPEC-131's guard for the same reason: a fleet that logs per item turns a growing directory into a growing log bill.
- [ ] Fields: `prefix_count`, `username_count`, `dropped_count`, `bytes_written`, `pages_listed`. Usernames are metadata and permitted under the field rule, but the **list itself is not logged** — it is the whole document, it is already durable in S3, and `logs/` is retained forever.
- [ ] `LOGS_QUEUE_URL` is optional (`environ.get`, never `_require`), so a missing variable logs to stdout rather than crashing at cold start.
- [ ] The function's environment carries every variable `cpcommon.config._require`s, asserted by a test — the PR #196 / PR #317 cold-start trap, which broke `pre-signup` for nine days.
- [ ] `echo=` appears nowhere.
- [ ] **Nothing in the instrumentation harness covers this function, and that is the accurate statement.** `test_instrumentation_coverage.py`'s `Plane.modules()` globs `lambdas/{data-quality,shared-space,table-builder,table-share}-*`, so a directory named `user-directory-build` matches **no** plane and is asserted by nothing — the same as every other singleton (`notifications-writer`, `log-sweep`, `control-plane-dlq-drain`, `pre-signup`, `post-confirmation`). Do **not** add a `PLANES` entry: `PLANES` models control planes, and a one-function pseudo-plane would misrepresent the fleet. The decorator and `init` are verified by this module's own unit test instead.

### FR-009: Deploy-role IAM and the deploy matrix

#### Acceptance Criteria:

- [ ] `infra/modules/base/policies/github-actions-deploy-user-directory.json.tftpl` is created, modelled on `github-actions-deploy-observability.json.tftpl`. Sids are **function-prefixed**, matching that file's convention: `UserDirectoryLambdaManage` on `function:${project_name}-*-user-directory-build`, `UserDirectoryRolesManage` including `iam:PassRole` on `role/${project_name}-*-user-directory-build`, `UserDirectoryLogs` on the group **and** `:*`, and `UserDirectoryScheduleManage` on `rule/${project_name}-*-user-directory-build-schedule`.
- [ ] **No new S3 statement is added.** The deploy role already holds `s3:*` on the user-space bucket and its objects via `S3UserSpaceBucketManage` in `github-actions-deploy.json.tftpl`, which `data/s3.tf` explicitly relies on. A comment records that the omission is deliberate.
- [ ] It is attached in `infra/modules/base/iam.tf`.
- [ ] **PR 1 applies the deploy-role policy; PR 2 applies the module.** The delivery doc records this, and the second PR is not opened until the first has applied — a deploy role cannot create a resource it has no grant for, and it also cannot always revert its way out (the refresh-deadlock lever in `CLAUDE.md`).
- [ ] `.github/workflows/deploy-lambdas.yml` gains `{ name: user-directory-build, layer: false, polars: false, tbcommon: false, cpcommon: true }` and `lambdas/test_deploy_matrix.py` passes.
- [ ] The Checkov plan scan (SPEC-139) stays green, or any new finding is dispositioned in `docs/security-baseline.md` by check ID.

### FR-010: Tests and lint

#### Acceptance Criteria:

- [ ] The Python suite passes.
- [ ] Tests cover: multi-page listing; the regex filter dropping `_directory` and any non-conforming prefix; sorting and de-duplication; the document shape including `version`; the empty-result guard not writing; idempotence across two runs; the absence of any Cognito import; the O(1) event-count guard; the `_require` environment assertion; and the tripwire that no other Lambda references the directory path.
- [ ] A live check is owed and recorded in the delivery doc: invoke manually, confirm the object exists with the expected usernames, and confirm from a browser session that the portal role can `GetObject` it and cannot `PutObject` to it.

---

## Data Model

```jsonc
// s3://{user-space-bucket}/_directory/usernames.json
{
  "version": 1,
  "generatedAt": "2026-08-03T04:00:11Z",
  "count": 3,
  "usernames": ["alice", "bob_smith", "cara"]   // ascending, deduped, all catalog-safe
}
```

```python
# lambdas/user-directory-build/build_directory.py — the shape, not the implementation.

def list_workspace_usernames(bucket: str) -> tuple[list[str], int]:
    """Return (sorted usernames, dropped_count).

    Every top-level common prefix on the user-space bucket is a personal workspace.
    `_directory` is the one deliberate exception and is dropped by the regex filter
    rather than by a special case, because CATALOG_IDENTIFIER_RE requires a leading
    lowercase letter — which is precisely why that name was chosen.
    """


def publish(bucket: str, usernames: list[str]) -> int:
    """Write the document. Returns bytes written.

    Plain PutObject, no CAS: one writer, one schedule, last-wins is correct.
    Refuses to write an empty list — see FR-002.
    """
```

## Environment Variables

New Lambda environment (not `VITE_`):

```
USER_SPACE_BUCKET      # already required by cpcommon.config
LOGS_QUEUE_URL         # optional by construction
# plus the rest of the cpcommon.config._require block: COGNITO_USER_POOL_ID,
# COGNITO_APP_CLIENT_ID, ADMIN_BUCKET, SHARED_SPACE_BUCKET, ATHENA_WORKGROUP
```

No `VITE_*` variable anywhere in this arc. SPEC-147 derives the object's location from the existing `userSpaceBucket()` helper, so none of the four-point `VITE_` wiring dance is needed.

## File & Folder Structure

```
lambdas/
├── user-directory-build/                     # NEW
│   ├── build_directory.py
│   └── test_build_directory.py
├── shared-space-add-members/add_members.py   # docstring correction only
└── test_deploy_matrix.py                     # + row

infra/modules/user-directory/                 # NEW
├── locals.tf
├── lambda.tf                                 # function, log group, schedule rule, target, permission
├── iam.tf
├── variables.tf
└── policies/
    ├── build-permissions.json.tftpl
    └── build-trust.json.tftpl
# NOTE: no outputs.tf role_arn — the allowlist takes a constructed string (FR-005).

infra/
├── main.tf                                   # + module block, + the role ARN in the allowlist locals
└── modules/
    ├── base/
    │   ├── iam.tf                            # + attach the new deploy policy
    │   └── policies/github-actions-deploy-user-directory.json.tftpl   # NEW
    └── data/
        ├── s3.tf                             # + the reserved-prefix comment
        └── policies/
            ├── portal-role-permissions.json.tftpl      # + one GetObject statement
            └── user-space-bucket-policy.json.tftpl     # + the builder role in the allowlist

apps/portal/src/features/
├── shared-spaces/memberInput.ts              # docstring correction only
└── file-browser/protectedFolders.ts          # + _directory

docs/transition_plan.md                       # + _directory in §6.3's Contents cells
```

## Implementation Phases

### Phase 1: Deploy-role IAM (PR 1)

- Write and attach `github-actions-deploy-user-directory.json.tftpl`.
- Apply and confirm green before starting Phase 2.

### Phase 2: The module (PR 2, part 1)

- `infra/modules/user-directory/` — function, role, log group, schedule, permission.
- The builder role into the bucket-policy allowlist as a root-`locals` constructed string.
- The portal role's `GetObject` statement.
- **Tests:** the two `simulate-custom-policy` checks (FR-004, FR-005).

### Phase 3: The Lambda (PR 2, part 2)

- `build_directory.py`, its tests, its matrix row and its observability.
- The reserved-name additions, the `transition_plan.md` edit, and the two docstring corrections.
- **Tests:** the full FR-010 list.

### Phase 4: Live check and closing out

- Manual invoke; confirm the document and the two IAM behaviours from a real browser session.
- Completion ritual: `INDEX.md` status, delivery doc (including the manual-invoke command), component-inventory rows if any reusable surface appeared, and a `decisions/` entry covering **both** settled calls — the S3-not-Cognito source with its transition reasoning, and the accepted all-users disclosure — with one line each in `CLAUDE.md` Key Decisions. **No help-content change** — nothing user-visible ships until SPEC-148.
