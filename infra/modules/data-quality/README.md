# `data-quality` — the profile-a-table control plane

The standard control-plane shape — see [`../../info/control-plane-shape.md`](../../info/control-plane-shape.md)
for the files, roles and traps every plane shares. What follows is what is distinct here.

A linear pipeline **around an Athena query**:

`validate-authorize → inspect-source → create-temp-tables → start-profile-query →
[WaitForQuery ⇄ CheckQuery] → byte-scan → assemble-report → drop-temp-tables`

The Lambda side is [`lambdas/info/planes/data-quality.md`](../../../lambdas/info/planes/data-quality.md).

## Standard is mandatory here, not a preference

A Standard execution runs for up to a year, **which is what lets the query poll live in the state
machine rather than inside a 900 s Lambda**. `FIRE_AND_FORGET` matters more on this plane than
anywhere else in the codebase — an Athena query can run for tens of minutes, far beyond any
synchronous invocation.

## ⚠ The zero-catalog-access property is deliberately surrendered here

This is a decision, not drift, and it is **the largest privilege this plane spends**. The role holds
Glue catalog access because the pipeline's whole design is **"let Athena read the 250 GB, not a
Lambda"**, and Athena reads through a Glue external table.

The temp tables are created in the **actor's own** database (personal) or the **shared space's**
(shared) — both **dynamic**, one per user and one per space — so they cannot be statically LF-granted
in Terraform, which is why the role is an **LF admin rather than a grantee**. Identical reasoning to
the table-builder and table-share roles, and why the Glue database and table ARNs are wildcards.

**What still bounds it:** Glue is `CreateTable`/`GetTable`/`DeleteTable`/`GetDatabase` only — no
`DeleteDatabase`, no catalog-wide data grant beyond `lakeformation:GetDataAccess` (which is not
scopable to a resource); Athena is scoped to the workgroup; and the two permanent boundaries below.

## Two boundaries that must survive every later spec

**1. `s3:DeleteObject` is granted nowhere on this plane.** `drop-temp-tables` touches **Glue only**,
which is what makes it safe to reach from **every** failure path — including a validator failure,
where the body-supplied location is still untrusted. **The sibling file-converter arc had to remove a
delete grant for exactly this reason: its cleanup was an authenticated cross-user file-delete
primitive.**

**2. The explicit Deny on `s3:PutObject` to `*/user_settings/*` and `*/DO_NOT_DELETE.txt`.**

**Why that Deny is not optional:** the user-space policy denies `s3:DeleteObject` on
`user_settings/*` but leaves **`s3:PutObject` wide open**. So any role that can write in a user's
space can overwrite `user_settings/notifications.json` and **permanently destroy the notification
inbox** — the user cannot even delete the corrupt file to recover, **because deleting it is itself
IAM-denied**. The Deny is what makes the guarantee; `validate-authorize`'s destination validation is
defence in depth.

**`ReadWriteReports` grants `GetObject` as well as `PutObject`**, deliberately: `assemble-report`
**reads back** the intermediate results it wrote, so a write-only grant would fail at the very last
verb, after all the work was done.

The notification grant is one action on one queue ARN — scoped to the **notifications** queue and
nothing else: **not** the data-quality request queue (a verb that could re-enqueue its own work is a
loop), and not the DLQ.

## The workgroup is the SHARED portal one, and that was measured

This plane originally had its **own** workgroup, to escape the portal workgroup's 10 GiB scan cutoff.
**Athena ties Lake Formation to the workgroup: a dedicated one fails LF's Create/Describe checks even
for an LF-admin role** — measured live.

The cutoff is the tradeoff: **a data-quality check over a source larger than the cutoff fails until
it is raised.**

## Every verb sets memory explicitly, and that is fixing a precedent

**Both `timeout` and `memory_size` are set for every verb.** The precedent this fixes, precisely: the
shared-space verbs set `timeout = 60` but **never set `memory_size`**, leaving it at the AWS default
of **128 MB**. It is the *memory* default that was left implicit there, not the timeout — and **an
unset memory tier is invisible in the plan and only shows up as an OOM in production**.

**No verb here streams bulk data** — Athena does the heavy work — which is why nothing needs the
maximum tier. `byte-scan` is the **only** function that touches file bytes, and its budget is bounded
**per request** (`DQ_SCAN_TOTAL_BYTES`, default 2 GiB); 300 s / 1024 MB is sized against that.

**A per-file budget would have been impossible**: 256 MiB × up to 1000 files ≈ 276 GB needs ~920 MB/s
sustained through one Lambda — **it would pass on a three-file fixture and time out in production**.

## Module names are `dq_<verb>.py`, never a uniform `handler.py`

An earlier version chose the uniform name on the grounds that "the verb directory already
disambiguates". **It was true of the zip packaging of the day — each function was its own zip — and
false for pytest, which flattens every verb directory into one module namespace.** With nine
`handler.py` files the first `import handler` wins for the whole session, so **the tests silently
imported one handler and asserted against the wrong module**. Reversed by user decision,
2026-07-16, before the remaining seven verbs inherited it.

**The container image removed the half of that reasoning that was ever true.** All 86 functions
share one task root, so a module name repeated across two verb directories does not collide — it
silently wins for the whole fleet. `lambdas/test_image_layout.py` refuses that at build time, and
the matrix asserts it against the built image; the `dq_` prefix is what keeps either from having to
fire.

**The `dq_` prefix is required on top of that**: table-builder already owns the bare `inspect_source`
and `validate_authorize` module names, and table-share prefixes its own for the same reason.

**The `handler` string here is the image's `command`**, so this map and
`lambdas/data-quality-<verb>/dq_<verb>.py` **must move together** — a mismatch deploys a function
whose entrypoint does not exist. The deploy's cold-start probe is what catches it now; before the
container arc, nothing but a live invoke would have.

## `MessageGroupId` is a hash, and content dedup is OFF

The SHA-256 hex digest of the canonical target location, so two checks of the **same** location
serialize while different locations run in parallel. **The digest rather than the raw location is
deliberate: SQS caps `MessageGroupId` at 128 characters and S3 keys reach 1024**, so a raw location
would be rejected outright. The other producers get away with raw ids only because they group by a
bounded catalog identifier.

**Content dedup would be actively wrong here.** Two different requestIds checking the same location
are byte-different anyway — but **a re-check of the same location with the same body is a legitimate
re-run the user asked for**, and content dedup would collapse it into a no-op inside the 5-minute
window.

## The two shared modules, and why polars is one of the plane's costs

`dqcommon` carries the **domain surface only** — no polars, no Excel engine, and **no
PyJWT/cryptography** (those live once, in `cpcommon`).

**polars is unavoidable for `inspect-source`:** Athena requires an **explicit column list** for a
Parquet or JSON external table and does **not** auto-detect a Parquet schema, so that list must come
from `inspect-source`'s per-file probe — and reading a Parquet footer needs a Parquet reader. "This
arc needs no polars" would make its own Parquet support impossible to build.

**It used to be a layer attached to that one verb, and it is now installed once in the image**, so
every function in the fleet can import it. That is the strictly wider import surface the container
arc names as the one thing it makes worse, and what pays for it is an AST sweep over what each verb
imports rather than the packaging.

**No `fastexcel`:** this plane does not support Excel. Convert it first, then check the Parquet.

## The registry list grant is what makes "no such space" answerable

`RegistryList` lets this role run `s3:ListBucket` on the admin bucket, conditioned to
`shared-spaces/*` — the prefix `cpcommon.registry.load` reads and nothing wider.

It is there because this plane's authorize step branches on that function returning None for "no
such space", and S3 reports a missing object as absent only to a caller that can list the bucket.
Without the grant the None is unreachable and a request naming an unregistered space fails as a
fault instead of taking its refusal. Found in production on 2026-08-17, under a role that held the
`GetObject` grant and no list statement at all.

**Do not widen it to an unconditioned list.** This role reads `${admin_bucket_arn}/shared-spaces/*`,
so a bucket-wide list would hand it every shared space's name and then every roster, and the space
name is the only thing gating that read.

Why a conditioned grant is sufficient, why the IAM simulate suggests otherwise, and the production
evidence settling it: `docs/decisions/infrastructure.md` → *A role that cannot list a bucket cannot
be told an object is absent*. `lambdas/test_absence_is_answerable.py` holds every registry-reading
directory to this, and fails closed on one it cannot map to a role.
