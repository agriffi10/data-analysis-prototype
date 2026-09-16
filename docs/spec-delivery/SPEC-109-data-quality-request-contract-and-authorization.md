# Completed Spec — SPEC-109: Data Quality — Request Contract, Browser Enqueue & `validate-authorize`

The request envelope, the browser's enqueue path, the first real verb, and the S3 grants —
plus the `Deny` that stops any bug in this pipeline from permanently destroying a user's
notification inbox. Shipped in one PR (#227); the deploy-role IAM this needed already
applied in SPEC-108 PR1.

## What was completed?

- **The envelope** (`features/data-quality/dataQuality.types.ts`) —
  `{ requestId, idToken, space{kind,bucket,prefix}, location }`. It carries **no actor or
  username field at all**: the actor is derived server-side from the verified token claim,
  so a body cannot assert an identity. A test asserts the sent body has neither `actor` nor
  `username`.
- **The enqueue service** (`dataQuality.service.ts` → `enqueueQualityCheck`) — returns
  `ServiceResult`, never throws. **`MessageGroupId` = the SHA-256 hex digest (64 chars) of
  `{bucket}/{normalizedLocation}`**, never the raw location: SQS caps the group id at 128
  characters while S3 keys reach 1024, so a raw id would fail the send **in the browser**,
  for exactly the users with the deepest folders. (The other producers get away with raw ids
  only because they group by a bounded catalog identifier.) Tests pin: a >128-char location
  still yields a 64-char group id and sends; the same location → same group id (serializes **—
  superseded 2026-09-15: ordered starts only, and the runs overlap; `docs/decisions/control-planes.md`
  —**); different locations → different ids (parallel); trailing-slash variants collapse.
  `MessageDeduplicationId = requestId` (content dedup is OFF on the queue).
- **`validate-authorize`** — the real verb. Verifies the ID token via `cpcommon.auth`
  (offline JWKS, RS256, `exp`/`iss`/`aud`, `token_use == "id"`), derives the actor from
  `cognito:username`, authorizes personal (own prefix, user-space bucket) and shared
  (`cpcommon.registry.is_active_member` + shared bucket + space prefix), normalizes the
  location (`posixpath.normpath`, so `..` cannot escape a space), rejects reserved source
  prefixes, and derives + validates the report destination. 18 tests, including the ones the
  spec insists on: **a Pending member is authorized** (SPEC-073 grants access at add time —
  "active" is the SPACE's status, not the member's join chip), a traversal attempt is
  `forbidden`, an unknown space and a non-member are indistinguishable (no membership
  oracle), and the body can never assert the actor.
- **Reason codes** — `dqcommon.messages` registers the domain table with `cpcommon.messages`
  (SPEC-107 FR-005), so every code it raises is a valid `TerminalError` reason at the raise
  site and a typo fails loudly instead of degrading to a generic message. Codes are exported
  constants; no bare literals at raise sites.
- **IAM (FR-006)** — the execution role gains `s3:GetObject`/`ListBucket` on both source
  buckets, registry read, and **`PutObject` + `GetObject`** on `_data-quality-reports/`
  (the read matters: `assemble-report` reads back the intermediate results it wrote, and a
  write-only grant would fail at the final verb after all the work was done). Plus the
  explicit **`Deny s3:PutObject`** on `*/user_settings/*` and `*/DO_NOT_DELETE.txt` across
  both buckets. Asserted: the rendered policy contains **no** `glue:`/`athena:`/
  `lakeformation:` action (those are SPEC-111's) and **no** `s3:DeleteObject` anywhere.
- **Portal-role grant + all four env wiring points** — `sqs:SendMessage` on the
  data-quality queue only; `VITE_DATA_QUALITY_QUEUE_URL` in the module output,
  `.env.example`, `deploy-app.yml`'s build env, **and set as a GitHub repo variable**
  (confirmed live — that fourth point is the documented "VITE_* deploy gotcha", and correct
  IAM does not save you from it).

## What changed from earlier specs?

- **`cpcommon.events.require` gained a keyword-only `reason` parameter** (default
  `malformed_event`). SPEC-109 FR-004 requires the shared shape-check *and* a domain
  terminal of `invalid_request`; the default keeps every existing caller byte-identical
  (table-builder's tests still pin `malformed_event`). Whatever is passed must be a
  registered reason — `TerminalError` validates it at the raise site.

## Deviations / notes

- ~~The verb file is `data-quality-validate-authorize/handler.py` (handler
  `handler.handler`), not the spec's `validate_authorize.py`: SPEC-108 established one
  uniform `handler.py` across all nine DQ verbs, and the verb directory already
  disambiguates. No FR depends on the filename.~~
  **REVERSED by SPEC-110 (user decision, 2026-07-16).** "The verb directory already
  disambiguates" is true for Lambda (each function is its own zip) but **false for
  pytest**, which flattens every verb dir into ONE module namespace: with nine
  `handler.py` files the first `import handler` wins for the whole session, and this
  file's tests silently imported SPEC-110's handler and asserted against the wrong
  module. It went unnoticed only because validate-authorize was the arc's sole tested
  verb. The verb file is now `data-quality-validate-authorize/dq_validate_authorize.py`
  (handler `dq_validate_authorize.handler`), arc-prefixed like table-share's
  `table_share_validate_authorize.py` because table-builder already owns the bare
  `validate_authorize` module name. No FR depends on the filename.
- The SFN `ValidateAuthorize` state needed no change — SPEC-108's skeleton already points
  it at this function's ARN with the `Catch` → cleanup → failure path wired.
