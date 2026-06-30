# Completed Spec — SPEC-067: Table Builder Request Contract, Enqueue & Validate-Authorize

## What was completed?

The **request envelope**, the browser's one new grant, and the first **real** pipeline step
(`validate-authorize`, replacing the SPEC-066 echo stub). **One PR (#151)** — it only adds
statements to existing roles + a new CI layer, no new resource type, so no deploy-IAM-first split
(the SPEC-061 precedent).

- **Request contract** (documented in `docs/testing/table-builder-e2e.md`): `{ idToken, space:
  {kind,bucket,prefix,database}, tableName, partitionKeys[], requestId }`. Sent FIFO,
  `MessageGroupId` = `space.database`, `MessageDeduplicationId` = `requestId`. `partitionKeys` empty
  = flat.
- **`validate-authorize` (real logic)** — offline Cognito **ID-token verify → trusted actor** (never
  a body username); **authorize the target space**: personal (`database == actor`, user-space bucket,
  prefix under `{actor}/`) | shared (active member per the shared-spaces registry, shared bucket,
  prefix under `{database}/`); validate `tableName` (`CATALOG_IDENTIFIER_RE`) + the user-declared
  `partitionKeys` (name/type/range/values) + in-space location; emit the normalized
  `{actor, space, tableName, partitionKeys, location, requestId}`. Any failure raises
  `TerminalError(reason)` → SFN `Catch` → `Fail` (`unauthorized` / `forbidden` /
  `invalid_table_name` / `invalid_partition_keys`), no side effects.
- **`tbcommon` layer** — `lambdas/table-builder-common/tbcommon/` (`config`/`clients`/`auth`/
  `registry`/`errors`), a **package, not flat modules**, so its names don't collide with
  `shared-space-common`'s flat `config.py`/`auth.py`/`registry.py` under one `pytest lambdas/`
  process. CI's new `table_builder_layer` job builds + publishes `table-builder-common` (PyJWT + the
  package) and the `tbcommon` matrix flag attaches it to `validate-authorize` (which no longer
  bundles requirements).
- **IaC** — validator role gains `s3:GetObject` on `<admin>/shared-spaces/*` (registry read; the
  admin bucket has no bucket policy → IAM-only). `validate-authorize` gains
  `COGNITO_USER_POOL_ID`/`APP_CLIENT_ID` env via a **per-verb env merge** (`local.table_builder_verb_env`)
  so other verbs are unaffected. **Portal role** gains `sqs:SendMessage` on the table-build queue ARN
  **only** (attached by name, like notifications/shared-spaces). Module gains `portal_role_name`/
  `user_pool_id`/`app_client_id`, wired from root. **No new deploy-role IAM** (PR1 covers role-policy
  writes + the `*-table-builder-*` layer name).
- **App** — `VITE_TABLE_BUILD_QUEUE_URL` documented in `.env.example`. The `deploy-app.yml` + GH-repo
  -var wiring is **deferred to SPEC-071** (when the browser actually sends) — noted inline.

## What changed from earlier specs?

- The SPEC-066 `validate-authorize` **stub** became real; the SFN ASL is unchanged (the linear
  pipeline already routed validate → check).
- `deploy-lambdas.yml` gained the `table_builder_layer` job + a `tbcommon` matrix flag on all rows.
- No behavior change to any other Lambda/module.

## Verification

**20** validate-authorize unit tests (valid personal/shared/partitioned + every terminal reason);
**full suite 115 passed** (no `tbcommon`/`shared-space-common` collision). `ruff check lambdas/`,
`tofu validate`/`fmt` clean; all `*.tftpl` render; layer import simulated; PR `plan` passed (the
portal-role inline-policy aggregate has headroom). Fresh-context review **APPROVE WITH NITS** (no
blockers; nits non-blocking — transient-registry-read terminal-fails not retries, acceptable;
`clients.jwks` url-caching; doc count). **Live check (post-merge):** a bad-token request was rejected
at `ValidateAuthorize` → `TerminalError: unauthorized` (stack through `/var/task/validate_authorize.py`
→ `/opt/python/tbcommon/auth.py`, proving the real code + layer are live), Catch → Fail, no downstream
verb ran. The valid-token path isn't CLI-testable (the app client is SRP/refresh — can't mint an ID
token), consistent with the SPEC-051 precedent.
