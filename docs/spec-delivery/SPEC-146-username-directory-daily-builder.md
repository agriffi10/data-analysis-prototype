# Completed Spec — SPEC-146: Username Directory — Daily Builder & Published Index

## What was completed?

The first of the username-directory arc: a list of existing usernames, published cheaply where the
browser can read it. Nothing user-visible ships here — SPEC-147 makes it searchable, SPEC-148 puts it
in front of people.

- **`infra/modules/user-directory/`** — one Lambda, one execution role, one 14-day log group, and a
  `rate(24 hours)` EventBridge rule + target + `aws_lambda_permission`. No queue, no state machine,
  no verbs; the closest sibling is `module.observability`'s sweep.
- **`lambdas/user-directory-build/build_directory.py`** — pages `ListObjectsV2(Delimiter="/")` over
  the user-space bucket, keeps the prefixes matching `CATALOG_IDENTIFIER_RE`, sorts, de-duplicates,
  and publishes `{version, generatedAt, count, usernames}` to `_directory/usernames.json`.
- **The portal role gained exactly one statement** — `s3:GetObject` on `${bucket_arn}/_directory/*`.
  The prefix-conditioned `ListBucket` was **not** widened, so the file browser needs no change.
- **The builder role joined the user-space bucket policy's allowlist**, as a constructed string in
  root `locals` (`user_directory_build_role_arn`); the module exposes **no `role_arn` output**.
- `_directory` added to `dqcommon.RESERVED_PREFIXES` and to **both** `protectedFolders.ts` lists;
  `transition_plan.md` §6.3 updated.
- **Two stale docstrings corrected** — `add_members.py` and `parseMemberInput` both claimed unknown
  users are "silently ignored", untrue since the owner notification landed.

### Deliberate deviations

- **`publish()` carries its own empty-list guard even though `handler` already decides.** The
  refusal is a property of publishing, not of one call site; a second caller added later would
  otherwise inherit no protection against silent wholesale erasure.
- **The FR-007 tripwire allowlists `dqcommon/config.py`.** That module names `_directory` as a
  *reserved* prefix — the opposite of reading it — so it is exempted by name rather than by
  weakening the pattern. The pattern matches `_directory/` **with its slash**, because a bare
  `_directory` is a substring of `test_every_lambda_directory_is_in_the_deploy_matrix`.
- **No `PLANES` entry in `test_instrumentation_coverage.py`**, as FR-008 requires. `Plane.modules()`
  globs the four control planes, so `user-directory-build` matches none and is asserted by nothing —
  the same as every other singleton. The decorator and `init` are pinned by this module's own tests.

## What changed from earlier specs?

- **`infra/modules/data`** takes a new `user_directory_build_role_arn` variable, threaded into the
  bucket-policy template's principal allowlist and into `portal-role-permissions.json.tftpl`.
- **`deploy-lambdas.yml`'s singleton comment block** was corrected: it claimed the singletons attach
  `cpcommon` for `observability` alone and therefore set none of the six required variables.
  `user-directory-build` also imports `config` and `clients`, so the layer's import-time `_require`
  **does** run for it and all six variables are set in its Terraform environment.

## Verification

`tofu validate`/`fmt` clean; **1772 Python tests** and **1301 SPA tests** pass; `ruff check lambdas/`
clean. Shipped as **two PRs** (#366 deploy-role grant, #367 the module), the grant applied before the
resources per FR-009 — the deploy-perms-before-resources rule.

**`aws iam simulate-custom-policy` was run against the DEPLOYED portal role**, not only the rendered
template: `GetObject` on `_directory/usernames.json` **allowed**; `PutObject`, `DeleteObject` and
`ListBucket` with `prefix=_directory/` all **implicitDeny**; `ListBucket` with the caller's own prefix
**allowed**. That last row is the control that makes the denials real refusals rather than "your ARN
matched no statement". The builder role was checked the same way: `ListBucket` and `PutObject` to
`_directory/` allowed, every `GetObject` and `DeleteObject` denied.

### The live check (discharged 2026-08-05)

```bash
aws lambda invoke --function-name dat-prod-user-directory-build --payload '{}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

Returned `{"published": true, "username_count": 12, "bytes_written": 225}`. **Corroborated
independently**: the User Pool holds exactly 12 users, so every confirmed user has a workspace prefix
today and FR-001's residual gap is currently empty.

**Two things the CloudWatch log showed that are worth keeping straight:**

1. **A `rate()` rule fires on creation, not one interval later.** The schedule's first invocation
   landed ~65 s before `Deploy Lambdas` finished and hit the placeholder zip
   (`user-directory-build Lambda code not yet deployed by CI`). EventBridge invokes asynchronously,
   so Lambda's own async retry re-ran it after the code landed and it succeeded. Self-healing, but a
   red first invocation on any future singleton of this shape is expected, not a defect.
2. **Only the `logger.info` line reaches CloudWatch** — the structured events go to the logs queue
   and from there to `logs/service=user-directory/`, by design.

**Still owed:** confirming the read end-to-end from a real signed-in browser session (an actual SigV4
`GetObject` as the assumed portal role). The policy half is discharged above; SPEC-147's
`useUserDirectory` exercises the request itself, so that spec's own live pass covers it.

**Not verifiable from a developer laptop, and worth knowing why:** the local CLI identity is the IAM
*user* `tofu-deploy-user`, which is **not** on the bucket policy's allowlist, and `dat-deploy-role`
trusts only the GitHub OIDC provider. So `get-object` and `list-objects-v2` against the user-space
bucket both return `AccessDenied` from a laptop — that is the isolation working, not a fault.
