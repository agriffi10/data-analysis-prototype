# SPEC-168 — Archive: Foundation Infrastructure, the Archive Bucket & validate-authorize

**Completed:** 2026-08-12
**Spec:** `docs/specs/SPEC-168-archive-foundation-and-validate-authorize.md`

## What shipped

The vault and the front door of the archive arc (168 → 172). Nothing is listed, copied or
deleted; the machine validates and stops at a placeholder terminal.

**Infrastructure — `infra/modules/archive/`**

- **The archive bucket (Bucket 5)**, `{project}-prod-archive`: SSE-S3, public access blocked,
  `BucketOwnerEnforced`, versioning off, **no CORS configuration**, and a bucket policy admitting
  only the archive execution role, the deploy role and the account root. A bucket-wide, unfiltered
  7-year expiry rule plus the abort-incomplete-multipart rule.
- The plane: FIFO request queue + DLQ (content dedup **off**), an EventBridge Pipe
  (`FIRE_AND_FORGET`), a **Standard** state machine, one shared execution role, the SFN role and
  the Pipe role.
- The state machine: `ValidateAuthorize → Validated → ChooseMode →` `ArchivePlaceholder` /
  `RestorePlaceholder` / `UnknownModeSeed`, with the SPEC-152 failure path
  (`ValidateFailureSeed → RecordFailure → NotifyFailure → Failed`) complete from day one.

**Lambdas**

- `arcommon` (new layer): `config`, `paths`, `authz`, `messages`, `notify`.
- `archive-validate-authorize` — verifies the token, authorizes the source space, checks every
  selected item, enforces the caps, resolves the archive prefix and the receipt key.
- `archive-notify-failure` — SPEC-152's notifier of last resort, one door.

**Grants and wiring**

- Portal role: `sqs:SendMessage` on the new queue and **nothing else**; the two `archive/` write
  Denies in both space buckets; `VITE_ARCHIVE_QUEUE_URL` in `.env.example` and `deploy-app.yml`.
- Deploy role: a new `{project}-deploy-archive` managed policy.
- The execution role ARN added to the user-space bucket policy's principal allowlist.
- The new DLQ registered with SPEC-126's drain sweep.

## What changed outside this plane

- **`cpcommon.paths` is new**, holding `assert_inside_root` / `has_dot_segment` /
  `normalize_root`, moved out of `fscommon.paths` (which now re-exports them). SPEC-156's rule:
  archive is the third plane to ask this question, and it is the one place a second copy is a
  cross-tenant read. No file-send call site or test changed.
- **`cpcommon.config.require()` is new** — the private `_require` made public so a domain layer
  reaches for the fleet's one fail-fast env reader instead of writing a second.
- `arcommon` joined the **mypy ratchet at zero** (`pyproject.toml`), on SPEC-164's precedent.
- Fleet registries updated: the DLQ drain's `SOURCES`, `test_deploy_matrix.py`'s
  `LAYER_PACKAGES`, `test_state_machines_cpcommon.py`'s `_EXPECTED_ARCS`,
  `test_notify_failure_import_safety.py`'s verb map and layer roots,
  `test_user_space_bucket_allowlist.py`'s `EXPECTED_PRINCIPALS`, and `conftest.py`.

## Two corrections made during the build

**`ARCHIVE_BUCKET` was first added to `cpcommon.config._REQUIRED_VARS`.** The reasoning — that
lazy `__getattr__` resolution makes it free for planes that never read it — is true of
*resolution* and false of the *contract*: that set is a fleet-wide one every plane's Lambda
environment must supply, and `test_the_common_environment_satisfies_every_import_time_require`
failed for table-builder immediately. It is `arcommon.config.archive_bucket()` now, a function so
the layer stays import-safe.

**The `mode` branch was first written on the Pipe's SQS message attributes**, which would have
invented an unverified contract about the record shape. It reads `$.mode` on the *validated*
request instead, where the field is a plain key of a parsed object.

## Owed

**One live check, and it is two halves of one session** (Phase 5):

1. Enqueue one hand-crafted valid archive request and one with an unauthorized source. Confirm
   the first reaches the placeholder terminal, the second notifies the actor, and both appear in
   `logs/service=archive/`. A shared layer's import-time failure only shows at **cold start**
   (PR #196), so this is the only thing that proves the layer attaches.
2. Signed in as a real user, attempt a `PutObject` into your own `archive/` prefix and confirm
   `AccessDenied` — **an IAM Deny is only proven by a denied call.** Repeat in a shared space.

Note the recorded identity constraint: a laptop IAM user cannot read or write
`dat-prod-user-space` at all (the bucket policy allowlists the portal, deploy and execution roles
only), so half 2 needs the portal UI.

**No user-facing surface shipped, so no Help change** — SPEC-172 owns the UI, the `archive/` write
gate that mirrors the IAM Deny, and the feature flag that gates the whole feature.
