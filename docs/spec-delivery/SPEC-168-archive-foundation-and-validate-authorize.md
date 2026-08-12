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

## Corrections made during the build

**`ARCHIVE_BUCKET` was first added to `cpcommon.config._REQUIRED_VARS`.** The reasoning — that
lazy `__getattr__` resolution makes it free for planes that never read it — is true of
*resolution* and false of the *contract*: that set is a fleet-wide one every plane's Lambda
environment must supply, and `test_the_common_environment_satisfies_every_import_time_require`
failed for table-builder immediately. It is `arcommon.config.archive_bucket()` now, a function so
the layer stays import-safe.

**The `mode` branch was first written on the Pipe's SQS message attributes**, which would have
invented an unverified contract about the record shape. It reads `$.mode` on the *validated*
request instead, where the field is a plain key of a parsed object.

**The envelope was drafted NESTED (`actor: {"idToken": …}`) and is FLAT** — `actor` is the raw
ID token at the top level. `cpcommon.auth.verified_username` takes a JWT *string*, so every
request in the drafted shape would have failed `unauthorized` **before the actor was bound** —
notifying nobody, and then being suppressed by `NotifyFailure` as a verb's own `TerminalError`.
And SPEC-126's drain reads and redacts `body["actor"]` **flatly**, so a dead-lettered archive
would have written the raw JWT to CloudWatch. **This is SPEC-164 FR-002's own amendment, for the
same reason**; the spec's FR-004 AC1 and Data Model now carry it. Found in review: both suites
stubbed `verified_username` itself, so the fixture's shape was never exercised — they now stub
`verify_id_token` *below* it, and one test captures what actually reaches the verifier.

## Review findings addressed

The fresh-context review found one blocker (the envelope above) and a set of tests that could
not fail. Each was **proven** by mutating the source and re-running, then reverted:

- The CSP `connect-src` check scanned line by line for the word `connect_src`; the enumerated
  list puts each host on its own line, so inserting an archive host left every check green. It
  now slices and parses the list, and a guard-the-guard proves the scan can see one.
- The "failure seed does not carry the selection twice" test was arithmetic over two literal
  strings and never read the ASL; and **nothing** caught a seed reading a path its own input
  lacks (the fleet guard walks *forward* from a seed, not at it) — adding `"source.$"` to
  `ValidateFailureSeed`, which would raise an uncatchable `States.Runtime`, left the fleet suite
  green. Both are now asserted against the machine, in its own suite.
- A receipt-path test compared a call with itself; the archive-bucket policy was checked by
  *count* of allowed principals rather than by name; the "no S3 grant yet" test forbade two
  actions rather than scoping by resource (the role legitimately holds `GetObject` on the
  registry); the `Resource: "*"` sweep missed the two portal templates this spec actually
  edited. All four are fixed.
- `{itemName}` was documented as filled from the raise site and appeared in no message body —
  `protected_marker` now names the file, and a new test holds **every** marker to having a
  supplier, because `blank_unfilled=True` renders an unsupplied one as a silent gap.
- The item cap was "proven" by `200 % 25 == 0`. It now computes the per-item round-trip cost
  against validate-authorize's own timeout, **read back from `locals.tf`**.

## Deviations from the spec text, recorded rather than silent

- **FR-002 AC4 is a forward tripwire, not a met criterion.** Nothing on the plane references
  `ARCHIVE_STORAGE_CLASS` outside `config.py` yet, so there is no restore machinery for a
  `GLACIER_IR` switch to bypass. The test is honest about being a guard on SPEC-171.
- **FR-003 AC6 ("every catch carries `ResultPath`") is not literally met**, deliberately.
  `ValidateAuthorize`'s input is the raw SQS **array**, and `ResultPath: "$.error"` on an array
  raises `States.ResultPathMatchFailure`. The error replaces the state and the actor is
  recovered from `$$.Execution.Input` — file-send's identical shape.
- **FR-005 AC4's "`pending` fails" is not implemented and should not be.**
  `cpcommon.registry.is_active_member` checks the *space's* provisioning status; a member whose
  join chip reads pending is authorized, per SPEC-073 and SPEC-164. Denying here would make this
  the only plane refusing a member for files they can already browse, download and share.
- **FR-001 AC1's "its ARN is constructed in root locals" is not met**; root constructs the
  **name**. The deploy policy builds both ARNs from it, and `modules/base/variables.tf` records
  why a name is the right thing to pass.
- **The shared-space `archive/` Deny is broader than its personal twin** —
  `${bucket}/*/archive/*`, and IAM `*` matches `/`, so it also denies writes under a nested
  `{space}/reports/archive/`. It follows the two existing denies in that file
  (`SharedResultsNoDelete`, `SharedMarkerNoDelete`) rather than introducing a second pattern; the
  consequence is that a user-made `reports/archive/` is writable in a personal space and not in
  a shared one. Accepted, noted here so it is a decision rather than a surprise.

## The merge apply went red, and the fix is structural

`Deploy Infrastructure` failed on the merge commit: `CreateBucket`, `CreateRole`, `CreateQueue`
and `CreateLogGroup` all returned `AccessDenied` for the archive resources. **The identical apply
succeeded on a re-run two minutes later with no change at all**, which is the whole diagnosis:
the deploy policy authorizing those creates is attached in the *same* apply, `module.archive`
does carry `depends_on = [module.base]` so the attachment genuinely happened first, and IAM is
eventually consistent anyway.

Every other plane dodged this by **splitting the work across two PRs** — grants in one, resources
in the next, which is the recorded deploy-perms-before-resources rule and is what those modules'
comments mean by "no `time_sleep` guard is required here". That rule holds only while somebody
remembers to split, and this spec shipped as one PR.

`modules/base` now carries a `time_sleep.wait_for_archive_grant` on the attachment, so the
existing `depends_on = [module.base]` covers it with no wiring in the child module. It matters
again the moment **SPEC-169** extends this policy (`events:`, plus S3 on the space and archive
buckets) in the same PR as the EventBridge rule and verbs that use them — the exact shape that
just failed. A red *first* apply of a new plane remains expected rather than a defect; a re-run
is still the remedy if AWS is slower than the floor.

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
