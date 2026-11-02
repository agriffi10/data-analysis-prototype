---
type: Decision
title: "Two things the fleet's own guards caught while this was being written"
description: "Path containment lives in `cpcommon.paths` and is not copied into `arcommon`; `ARCHIVE_BUCKET` stays out of `_REQUIRED_VARS` and is read through the function `arcommon.config.archive_bucket()`."
---

**Containment moved to `cpcommon.paths` rather than being copied into `arcommon`** (SPEC-156).
`assert_inside_root` / `has_dot_segment` / `normalize_root` arrived on `fscommon.paths` with
SPEC-164; archive is the third plane to ask the identical question, and it is the one place where a
second copy that drifts is a **cross-tenant read**. `fscommon.paths` re-exports the three names, so
every file-send call site and test is unchanged. A test asserts `arcommon.paths` defines none of
them.

**`ARCHIVE_BUCKET` is not a `cpcommon.config` required variable.** The first attempt added it to
`_REQUIRED_VARS`, reasoning that the lazy `__getattr__` made it free for planes that never read it.
That is true of resolution and false of the contract: `_REQUIRED_VARS` is a **fleet-wide** set each
plane's Lambda environment must supply, and the change failed table-builder's guard immediately.
The value is `arcommon.config.archive_bucket()` instead — a **function**, not a module attribute, because a
constant resolved at import time in a layer runs for every attaching function and an unset variable
then crashes at **cold start**, where no test and no deploy can see it (PR #196). `cpcommon.config`
gained a public `require()` so a domain layer reaches for the fleet's one fail-fast reader rather
than writing a second.

> **Superseded in part (2026-09-01) — the CHECK, not the decision.**
> `test_the_common_environment_satisfies_every_import_time_require` was retired in #540. It also
> never had the reach its name implies: it read `infra/modules/table-builder` alone, so the
> paragraph above overstates it, as several other doc sites did. Keeping `ARCHIVE_BUCKET` out of
> `_REQUIRED_VARS` is unchanged and still right.
>
> **Restored, and this time across the fleet (2026-09-01).** `lambdas/test_fleet_environment.py`
> checks all 86 deployed functions. It does not demand the whole set on every plane, because that
> was never true — archive, file-ops and file-send reach no Athena workgroup on any branch and
> correctly omit it — so it refuses only a name a function's own import closure can reach while
> its Terraform withholds it. **That reachability is not what catches THIS decision, and the
> distinction is worth keeping straight:** `ARCHIVE_BUCKET` is read only by archive, whose
> Terraform sets it, so the reachability half stays green. What reddens is the pair of tripwires
> either side of it — the fleet guard's assertion that the required set is still exactly the four,
> and `user-directory-build`'s mirror of that set against its own block. Verified by adding the
> variable and watching exactly those two fail. The read itself is genuinely seen rather than
> merely absent: delete `ARCHIVE_BUCKET` from `infra/modules/archive/lambda.tf` in the same breath
> and seventeen of archive's eighteen verbs redden with it — all but `copy-objects`, the one whose
> closure never reaches `archive_bucket()`.

## History

### 2026-09-01

- **Changed:** The test guarding import-time required variables was retired in #540; keeping `ARCHIVE_BUCKET` out of `_REQUIRED_VARS` was unchanged.
- **Changed:** The check was restored across the fleet by `lambdas/test_fleet_environment.py`, which refuses a name a function's import closure can reach while its Terraform withholds it.

### 2026-08-12

- **Settled:** entered the register.
