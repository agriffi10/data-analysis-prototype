# Spec: Structured Logging — Instrument the Singleton Lambdas

**ID:** SPEC-137
**Status:** Completed
**Last Updated:** 2026-07-23
**Depends On:** SPEC-130 (the emitters and `step`), SPEC-134 (the coverage harness), SPEC-133 (the infra pattern)

## Overview

The last three functions outside the pipe, and the only three that are not control-plane verbs:
`notifications-writer`, `pre-signup` and `post-confirmation`. They are grouped because they share
one problem that none of the control planes has — **they do not attach the `cpcommon` layer**, and
attaching it is the exact shape of this repo's worst production break.

`cpcommon.config` calls `_require` on six environment variables at **import**, so every function
attaching the layer needs the union of them or it crashes at cold start, at the entry point rather
than at the line that would have used the variable. That is PR #196, and it took down a whole
control plane. `notifications-writer` has three of the six; the Cognito triggers have fewer.

The way through is verified rather than assumed: `cpcommon.observability` imports and emits with
**zero** environment variables set, because `cpcommon/__init__.py` is a docstring with no imports
and `clients` lazy-imports boto3, so `config` is never reached along that path. That makes the
layer safe to attach — and makes the invariant load-bearing, because one `from cpcommon import
config` added to `__init__.py` later would arm the bomb for these three. FR-001 pins it with a
test.

The stakes are not symmetric. `notifications-writer` is the **delivery channel for every failure
notification in the system**, and the notifications DLQ is deliberately left undrained because
draining it would ask the queue that just failed to deliver to deliver the news about itself
(SPEC-126 FR-006). A message that dies in the writer dies silently, by design. Its structured
events would be the only account of it.

## Scope

### In Scope

- `cpcommon` layer attachment for all three functions, with the import-safety invariant pinned.
- `observability.init(service="notifications")` on the writer; `service="auth"` on both triggers.
- `@observability.traced(<verb>)` and narrative for each.
- **Email added to the excluded-fields rule** alongside tokens (user decision, 2026-07-23).
- The infra pair on the `notifications` and `auth` modules, and harness entries for both services.

### Out of Scope

- **Any behavior change.** No change to the single-writer model, the FIFO group key, the inbox
  cap, dedup, the username rule, database provisioning, LF grants, or the `portal-managed` tag.
- **Draining the notifications DLQ.** Still deliberately undrained (SPEC-126 FR-006). This spec
  makes the writer's own failures visible; it does not add a second delivery channel.
- **Importing anything else from `cpcommon`** into these three. FR-001 restricts them to
  `observability` on purpose; adopting `cpcommon.auth` or `cpcommon.config` here is a separate
  decision with a cold-start cost.
- **Logging email addresses** — excluded by FR-005.

---

## Functional Requirements

### FR-001: The layer is safe to attach, and that is proven

#### Description

These three functions gain the `cpcommon` layer solely to reach `observability`. The layer's
`config` module `_require`s `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`, `ADMIN_BUCKET`,
`USER_SPACE_BUCKET`, `SHARED_SPACE_BUCKET` and `ATHENA_WORKGROUP` at import time; none of these
three has all six, and giving the Cognito triggers an Athena workgroup to satisfy an import would
be config theatre.

It is unnecessary, because `import cpcommon.observability` never reaches `config`. That holds
today by a structural accident worth converting into a maintained property: the package
`__init__` has no imports, and `clients` imports boto3 lazily.

#### Acceptance Criteria:

- [ ] All three functions attach the `cpcommon` layer, added in `deploy-lambdas.yml` — CI owns
      layer attachment, not Terraform (the SPEC-012 code/infra split).
- [ ] Each imports **only** `from cpcommon import observability`. A test asserts by AST that no
      other `cpcommon` submodule is imported in these three modules.
- [ ] A test imports `cpcommon.observability` **in a subprocess with a scrubbed environment** and
      asserts it succeeds. In-process will not do: `conftest.py` sets an environment baseline that
      would satisfy `_require` and hide exactly this failure — the way it was hidden before PR
      #196.
- [ ] The same subprocess test emits one event through `observability` with no environment set,
      proving the stdout fallback path works rather than only that the import did.
- [ ] A comment in `cpcommon/__init__.py` records that it is deliberately import-free and that
      three functions depend on it staying that way.
- [ ] None of the six `config` variables is added to any of the three functions' environments.

### FR-002: The notifications writer

#### Description

`service="notifications"`, `verb="write"`. The function whose silence costs the most: it is how
every other plane's failures reach a person, and its own dead letters are deliberately undrained.

It is also a read-modify-write on a JSON document with a cap, and the cap **silently drops the
oldest notifications** once an inbox passes `NOTIFICATIONS_MAX`. A user asking where an old
notification went currently has no record to consult.

#### Acceptance Criteria:

- [ ] Events for: the action (`create` / `markRead` / `markAllRead`), the target username, the
      inbox size before and after, and the outcome.
- [ ] Capping emits `warning` naming how many notifications were dropped and the cap. A silent
      drop is a silent data loss, and this is the only place it is recorded.
- [ ] A failure to verify the ID token emits `error` with a stable reason — this is the anti-spoof
      boundary (SPEC-058→061), and an attempt to write to another user's inbox is the single event
      here most worth having permanently.
- [ ] The username is logged; the **inbox contents are not**. Notification message bodies can
      carry values a verb interpolated from a user's request, so the count is logged and the text
      is not.
- [ ] A failed inbox write emits `error` naming the username and the reason, since the message
      then dead-letters to a queue nothing drains.

### FR-003: pre-signup

#### Description

`service="auth"`, `verb="pre-signup"`. It enforces the catalog-safe username rule
`^[a-z][a-z0-9_]{2,62}$` (SPEC-033) — the rule that makes username, S3 prefix, principal tag and
Glue database name the same string. A rejection here is the first thing a new user experiences.

#### Acceptance Criteria:

- [ ] One event per invocation carrying the attempted username and the verdict.
- [ ] A rejection carries a stable reason token distinguishing the ways the rule can fail: too
      short, too long, bad first character, disallowed character.
- [ ] **No email address appears in any field** (FR-005).
- [ ] The Cognito trigger event is never logged wholesale — see FR-005, where that is the concrete
      hazard rather than an abstract one.

### FR-004: post-confirmation

#### Description

`service="auth"`, `verb="post-confirmation"`. It provisions the user's Glue database, applies the
`portal-managed` LF-Tag and grants the portal role. A failure here produces a signed-up user with
no database, discovered much later when they open the Query workspace and it is empty.

The tag step deserves particular attention. `portal-managed` is the linchpin of the TBAC model
that replaced the false "LF admin implies `CREATE_TABLE`" assumption (SPEC-070 → SPEC-111, PRs
#243–246). If tagging silently fails for one user, **every** control plane will later fail to
create tables in that user's database — which is precisely the silent, per-user version of the
failure that took four PRs to find the first time.

#### Acceptance Criteria:

- [ ] `step` spans on `ensure-database`, `tag-database` and `grant-role`, each with its own status
      and duration.
- [ ] Each step emits its outcome with the database name; a failure emits `error` with the reason
      and does not hide behind a partially provisioned user.
- [ ] The `tag-database` outcome is logged explicitly on the success path too, not only on
      failure — its absence is what would need to be noticed, and an absent event is only
      noticeable if its presence is the norm.
- [ ] `backfill.py`'s path, when exercised, is instrumented the same way.
- [ ] A partially provisioned user — database created, tag or grant failed — emits a distinct
      `error` naming which steps completed, since that state is recoverable by re-running and
      indistinguishable from success without the record.

### FR-005: Email is excluded

#### Description

Usernames are not sensitive in this system — the username *is* the S3 prefix, the principal tag
and the Glue database name (SPEC-033), so it is already the primary key of every operator record.
An **email address is not**: it is a contact identifier that appears nowhere else in this store,
carries no operational meaning here, and would be the only personal contact detail in a prefix
retained forever. It joins tokens on the never list (user decision, 2026-07-23).

The hazard is specific and mechanical. A Cognito trigger event carries
`request.userAttributes.email`, so a single `observability.info("signup", event=event)` — the
most natural line anyone would write while debugging a trigger — publishes it.

#### Acceptance Criteria:

- [ ] SPEC-130 FR-005's excluded list gains **email addresses**, with this reasoning, so the rule
      lives in the shared module docstring rather than only in this spec.
- [ ] No field in either trigger carries an email, an attributes map, or the raw trigger event.
- [ ] A test drives both triggers with an event containing a recognisable email and asserts the
      address appears in **no** emitted event, checked against the serialized event rather than
      against a field allowlist — the leak would arrive nested inside a dict, where a field-name
      check cannot see it.
- [ ] The contents denylist in the coverage harness gains `event`, `attributes`,
      `user_attributes` and `email`.

### FR-006: Two services, and the harness

#### Description

Three functions, two services: `notifications` for the writer, `auth` for both triggers. The
triggers are two ends of one flow — validate the username, then provision for it — and share a
service so a signup's whole story is one query.

#### Acceptance Criteria:

- [ ] Both `"notifications"` and `"auth"` match `log_sweep.SERVICE_RE`; a test asserts it.
- [ ] Two harness entries are added, each declaring its function count and the expectation that
      `@traced` is the only decorator on these handlers.
- [ ] With these entries the harness covers **every** Lambda in the repo. A test asserts the
      harness's registered function count equals the number of handler modules under `lambdas/`,
      minus an explicitly named exclusion set — so a future Lambda cannot be added without either
      instrumenting it or naming why not, the same enumerate-don't-list posture SPEC-126 used for
      queue descriptors.

### FR-007: The infrastructure the events need

#### Description

Two modules this time — `notifications` and `auth` — and a layer attachment in CI.

#### Acceptance Criteria:

- [ ] `logs_queue_url` variables on `modules/notifications` and `modules/auth`, wired in `main.tf`,
      set as `LOGS_QUEUE_URL` on all three functions.
- [ ] `EmitStructuredLogEvents` statements granting `sqs:SendMessage` on the logs queue ARN in
      both modules' execution policies, matching the data-quality Sid and shape.
- [ ] `LOGS_QUEUE_URL` optional by construction — `environ.get`, never `_require`.
- [ ] `deploy-lambdas.yml` attaches the `cpcommon` layer to all three, and the workflow's comment
      records that these three attach it for `observability` **only**.
- [ ] The deploy-role check is performed and its finding recorded for both modules.
- [ ] IAM, environment and layer attachment land before the instrumented code deploys. The
      ordering matters more here than anywhere: the first function to break would be the one that
      tells users when anything else breaks.

---

## Data Model

Events follow SPEC-127's schema, landing at `logs/service=notifications/…` and
`logs/service=auth/…`. Field vocabulary:

```
# notifications
username: str       action: "create" | "markRead" | "markAllRead"
before: int         after: int          dropped: int        cap: int
link: bool          dedup: bool         reason: str

# auth
username: str       verdict: "accepted" | "rejected"
database: str       tagged: bool        granted: bool
reason: "too_short" | "too_long" | "bad_first_char" | "bad_char"
      | "ensure_database_failed" | "tag_failed" | "grant_failed"
```

No email field exists in either vocabulary, and none may be added (FR-005).

## File & Folder Structure

```
lambdas/notifications-writer/notifications_writer.py
lambdas/pre-signup/pre_signup.py
lambdas/post-confirmation/{post_confirmation,backfill}.py
lambdas/control-plane-common/cpcommon/{__init__,observability}.py   # comment + excluded list
lambdas/control-plane-common/test_instrumentation_coverage.py       # + two entries, full coverage
lambdas/control-plane-common/test_observability_import_safety.py    # the subprocess test (FR-001)
infra/modules/{notifications,auth}/{variables,lambda}.tf
infra/modules/{notifications,auth}/policies/*.json.tftpl
infra/main.tf
.github/workflows/deploy-lambdas.yml                                # cpcommon on three functions
```

## Implementation Phases

### Phase 1: Import safety, proven first

- The subprocess scrubbed-environment test and the `cpcommon/__init__.py` comment. This lands
  before anything attaches the layer, because it is the thing that says attaching is safe.

### Phase 2: Infrastructure

- Both modules' variables, wiring, `LOGS_QUEUE_URL` and IAM; the CI layer attachment; the recorded
  deploy-role findings.

### Phase 3: The writer

- `init` + `@traced` + narrative, including the silent-cap warning and the token-verification
  failure event.

### Phase 4: The auth triggers

- Both triggers, the provisioning steps, and the email-exclusion test driven with a recognisable
  address.

### Phase 5: Full coverage and live verification

- The harness entries plus the every-Lambda-registered assertion.
- Sign up one test user and confirm the `auth` service's events tell the whole signup: the
  username verdict, the database, the tag and the grant.
- Trigger one notification and confirm the writer's events show the inbox before and after.
