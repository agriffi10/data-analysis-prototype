# Completed Spec — SPEC-125: Fold `shared-space-common` onto the `cpcommon` layer

## What was completed?

The last control-plane layer still carrying its own copy of the JWT-verification /
boto-client / notification path now shares `cpcommon`. **No user-visible change.**

- **`cpcommon.auth` is the one JWKS path.** `verify_id_token(token) -> claims` raises the
  new `cpcommon.errors.AuthError`; `verified_username` maps it to `TerminalError` for
  table-builder / table-share / data-quality, and `shared-space-common/auth.py` maps it to
  `AuthorizationError`. The **exception seam** is what let both models survive: the
  shared-space Standard Step Function Catches `AuthorizationError` and has no transient
  concept at all, so sharing the *logic* could not mean picking a winner on the *type*.
- **`shared-space-common` is domain-only.** `clients.py` deleted (not shimmed);
  `config.py`'s shared core removed; `notify.emit_notification` and `casio.error_code`
  re-exported from `cpcommon`. `registry`, `cache`, `membership`, `teardown`, the CAS retry
  loop, the domain config constants and the seven lifecycle emitters stay.
- **`ATHENA_WORKGROUP` on all 8 shared-space Lambdas** (PR 1, applied first) — required by
  `cpcommon.config` **at import**, so attaching the layer without it would have crashed all
  eight at cold start. `cpcommon.clients` also gained `lf()`, completing the union.
- **CI**: the 8 rows are `cpcommon: true`; the `shared-space-common` layer no longer
  pip-installs anything (PyJWT is declared once, in `cpcommon`) and no longer copies
  `clients.py`.

**Deviations, all technical:**

- **The shared values are read from `cpcommon.config` directly**, not re-exported through
  the domain `config`. A re-export reads as one source of truth and is really a second
  copy with a second attribute to patch — the drift this spec exists to remove.
- **`test_config_shared_space.py` was rewritten rather than re-pointed.** Its five
  shared-var cases now duplicated `test_config_cpcommon.py` exactly. It keeps what this
  module still owns (`PORTAL_ROLE_ARN`, `MAX_SHARED_MEMBERSHIPS`) and gains the case
  neither file had: the **union** a shared-space verb needs at cold start is still required
  by *one of its two layers* — the PR #196 lesson made executable.
- **`casio`'s CAS retry loop stays domain-side**, per the spec's own exclusion. So
  `dqcommon`'s duplicate CAS is **not** resolved by this spec; `decisions.md`'s SPEC-123
  entry, which said 125 was where they merge, is corrected.

## What changed from earlier specs?

- **`cpcommon.auth` (SPEC-107)** is restructured around `verify_id_token`. `verified_username`'s
  external behaviour is unchanged and pinned by test, including that it still enforces expiry.
- **`cpcommon.errors` (SPEC-107)** gains `AuthError` — internal; callers translate it.
- **SPEC-126's `verified_username_ignoring_expiry`** is now layered on
  `verify_id_token_ignoring_expiry`, keeping the relaxation a **separately named** entry
  point rather than a flag on the function every authorization path calls.
- **Test plumbing only** (FR-004): import paths, and `fakes.install()` + 12 setup lines
  patching `cpcommon.config` instead of the domain `config`. **No assertion changed.**

## Verification

`pytest lambdas/` 1021 passed · `ruff check lambdas` clean · `tofu fmt -check` ·
`tofu validate`.

**4 mutations, 4 guard failures** on the security-critical path: rewording `"not an ID
token"`, rewording the shared-space adapter's message, disabling expiry enforcement
outright, and deleting the `cognito:username` claim check — none of which was pinned by
anything before this spec.

**Deferred:** FR-004's live smoke run (create → add-member → leave → delete). It is the
only thing that exercises a **cold start** with the new layer attached, which is the one
failure mode no unit test reaches — and the exact shape of the PR #196 production break.
