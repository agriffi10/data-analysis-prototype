# `analytics` — Athena, the admin bucket, and Lake Formation

The shared Athena workgroup every user queries through, the admin-only results bucket, and **the Lake
Formation bootstrap the whole catalog model rests on**.

| File | Holds |
|---|---|
| `athena.tf` | the shared workgroup and the IAM propagation guard |
| `s3.tf` | the admin bucket, its **nine** lifecycle rules and the `check` that pins them |
| `iam.tf` | the LF registration role, and the portal role's analytics policy |
| `lakeformation.tf` | data-lake settings, hybrid registration, the `portal-managed` LF-Tag and every tag grant |
| `variables.tf` | the module interface |
| `policies/` | the portal-role analytics template |

## Isolation is not at the workgroup layer

One workgroup serves every authenticated user. Per-user isolation is the **Glue database/table ARN
scoped by the `username` principal tag**, plus the per-user results prefix.

**Athena has no built-in per-user result location**, so `enforce_workgroup_configuration` is **off on
purpose** and the app sets a per-user `OutputLocation`
(`s3://<user-space-bucket>/{username}/system_settings/athenaresults/`) on every `StartQueryExecution`. **IAM is what
actually confines each caller.** Do not "harden" this to `true` — it breaks per-user result routing.

The workgroup's **default/fallback** output goes to the admin bucket under `fallback-results/`, not
the bucket root, so the expiry rule can target only transient fallback output and leave the
`shared-spaces/` registry untouched. Any query that omits an explicit `OutputLocation` writes there —
**never to a user-readable place**.

Engine v3 is pinned explicitly rather than `AUTO`, so an engine upgrade is a deliberate, reviewed
change.

The portal role's analytics policy omits **`ListQueryExecutions`** deliberately — it would leak other
users' queries — and carries an explicit **Deny on `DeleteObject`** so results cannot be deleted or
moved out. It needs bucket-level **`s3:GetBucketLocation`** to verify the per-query output location
(without it: *"Unable to verify/create output bucket"*), granted on the bucket itself, **which leaks
only the region, not data**.

## ⚠ Lake Formation is registered in HYBRID mode

**Do not flip to enforced (non-hybrid) without opting in every principal first** — it would break the
file browser's IAM-authorized S3 access to the user-space bucket (the API's calls under the caller's
assumed role, and bytes on URLs that role presigned). Hybrid is what makes the same data reachable
two ways: non-opted-in principals via direct S3 IAM, opted-in ones via LF credential vending.

The registration role is a **custom role, deliberately not the LF service-linked one**, so the trust
and the S3 scope stay explicit and auditable. It is scoped to the user-space bucket only.

The data-lake settings remove the default **`IAMAllowedPrincipals` "Super"** grants, so new databases
and tables get **no** automatic catalog-wide access. That was safe to enable because the file browser
reads through direct S3 IAM rather than LF, and because no per-user databases existed yet.

**Every admin ARN is a constructed string, known at plan time** — **an unknown element inside that
`compact()` silently drops the admins change**. `compact()` also drops empty ARNs so the module still
plans standalone. Some of those roles are created by modules that `depends_on` this one, **so a
from-scratch first apply may need a re-run once they exist**.

The portal role's `DATA_LOCATION_ACCESS` is a **single location-level grant, not per-user**; per-user
gating still comes from IAM. The LF `INSERT` *table* permission is granted later, per-database, by the
post-confirmation Lambda.

## TBAC: being an LF admin does not grant `CREATE_TABLE`

**An LF data-lake admin cannot create a table in a database it did not create.** So table-builder,
table-share and data-quality — all admins — could not create tables in the dynamic per-user and
per-shared-space databases.

Rather than loop a per-database named grant onto each shared role — **exactly the toil LF-Tags exist
to remove** — every managed database carries one **`portal-managed`** LF-Tag, and the roles are
granted **on the tag**. The provisioning Lambdas attach it to each new database; **a table inherits
its database's tag**, so a created table is reachable by the same grant. **Adding a future
control-plane role is then one grant here — no Lambda change.**

**The portal role is deliberately not tag-granted**: its per-user isolation depends on the named
database ARN plus the IAM principal tag, so it keeps its per-database named grant rather than blanket
tag access to every database.

> **`portal-managed` is not `portal.managed`.** This one is a Lake Formation tag on **databases**,
> hyphenated, and it **grants** — it is how the control-plane roles get `CREATE_TABLE` in dynamic
> databases. The other is a table `TBLPROPERTY`, dotted, in `cpcommon/ddl.py`, which only **records**
> that the portal created a table and which nothing reads to decide anything. **One character apart,
> unrelated jobs.**

**Assigning the tag requires `ASSOCIATE` on the tag, and admin status does not implicitly grant it** —
confirmed live: the post-confirmation role, an admin, got *"Required ASSOCIATE on portal-managed"* from
`AddLFTagsToResource`. The tag **creator** (the deploy role) has it implicitly; the two provisioning
roles that call `AddLFTagsToResource` must be granted it explicitly. The control-plane execution roles
do **not** assign the tag, so they are not granted `ASSOCIATE`.

`DATA_LOCATION_ACCESS` on the registered bucket is **the location half LF-Tags cannot express** —
tags cover database and table resources, not S3 locations. One per-bucket grant covers every user
prefix; which user's data a role may touch is gated by `validate-authorize`, not per-prefix IAM.

### ⚠ The `ignore_changes` on the tag grants broke main, and without it every future apply fails

**Lake Formation does not read this grant back the way Terraform wrote it.** The grant is
`ASSOCIATE`+`DESCRIBE` on values `["true"]`; a refresh returns values `["*"]` with
`permissions_with_grant_option ["ALTER","ASSOCIATE","DESCRIBE","DROP"]` — **the principal's effective
permissions, because these two roles are also data-lake admins**.

`values` is **replacement-forcing**, so every plan showed "must be replaced" and every apply tried to
revoke-then-regrant. **The revoke then fails**, because the grant it describes was never explicitly
made:

```
InvalidInputException: No permissions revoked. Revoking Tag permissions on Tags
that grantee does not have permissions on.
```

Observed once on a merge that aborted the apply before it reached the state machine. **Nothing was
revoked, so the grants survived — a louder failure than it looks, and a luckier one.**

The grant itself is correct and is doing its job; **only the read-back diverges**. The tag has exactly
one value, so LF's `["*"]` and our `["true"]` are the same grant described two ways.

**What this costs:** a genuine out-of-band revocation of these grants **would no longer show up as
drift**. That is the accepted trade — the alternative is a permanently red main and an infra pipeline
that cannot deploy anything. **If provisioning ever fails with "Required ASSOCIATE on portal-managed",
check this grant first; Terraform will not.**

## The verification principal gets DESCRIBE and nothing else

On the same `portal-managed` tag, because the databases are created at runtime and nothing static can
enumerate them. **`SELECT` and `DATA_LOCATION_ACCESS` are deliberately absent**: the role reads a
table's **definition** and cannot read a byte of what the table points at — which is what makes it a
verification principal rather than a widening of the data path. The IAM half lives in
`modules/verification`.

## ⚠ The admin bucket's lifecycle rules: `logs/` is retained forever

**Structured logs are retained indefinitely** (user decision, 2026-07-22). The cost, stated plainly so
it is read here rather than discovered on a bill: **unbounded growth, with no ceiling and no decision
point**.

**What makes that safe is structural, not conventional: every rule that can EXPIRE something carries a
prefix filter**, so none can match `logs/` by accident. **S3 lifecycle rules can only INCLUDE a
prefix, never exclude one** — so an expiring rule added later with an empty filter would **silently
begin deleting the logs**.

The `admin_lifecycle_rules_are_prefix_scoped` **`check`** pins exactly that. It is a **plan warning,
not a hard failure**: OpenTofu has no native way to fail on it without restructuring the lifecycle
resource to render its rules from a local via `dynamic`, which is more risk than it is worth on a
working retention config. The failure mode it guards is a code-review moment, and this puts the
evidence in the diff's own plan comment. **It is scoped to rules that can DELETE something** — a rule
with no `expiration` cannot delete an object at all, so requiring a prefix on it bought nothing and
blocked the bucket-wide `CKV_AWS_300` rule.

**Each control plane's copy plan gets its own rule rather than one widened filter**, because **S3
lifecycle takes one prefix per rule, and a prefix broad enough to cover them all (`""`) would match
`logs/`**. All four are execution-scoped — read minutes after they are written — and the retention
that remains is purely so an operator can inspect the plan of a failed run.

Two prefix traps worth naming:

- **`archive/` here is the admin bucket's control-plane scratch space.** It has nothing to do with the
  `archive/` folder in a user's own space (receipts, never expired) or with the archive **bucket**
  (7 years). **Three unrelated things named `archive/`, in three buckets.**
- **`file-ops/` cannot reach `locks/file-ops/`**, because an S3 lifecycle prefix **anchors at the
  start of the key**. It must not: that lock is released by **overwriting** rather than deleting, so
  "free" is a state of the object rather than its absence — **an expiry rule reaching it would turn a
  released lock into a missing one and break the compare-and-set that detects a steal**.

The ALB access-log rule is **not** execution-scoped and has its own knob: those logs are the only
record of a request that never reached a task, so their window is an incident-investigation one. **The
prefix arrives as a variable from root**, which is also where the module pointing the balancer at it
reads the same value — **two literals could disagree, and the symptom would be logs that never
expire**.

The abort-incomplete-multipart rule is **bucket-wide and deliberately unfiltered** (`CKV_AWS_300`):
orphaned parts can appear anywhere, so scoping it to today's prefixes would leave a new prefix
silently unprotected. **Unfiltered is safe here in a way an expiration rule would not be** — it
carries no `expiration` and can only discard the **parts** of an upload that never completed, so **it
cannot reach `logs/`**.

## The admin bucket has no end-user access and no CORS

The portal role is **never** granted anything on it. **User-facing query results and history do not
live here** — they go to `{username}/system_settings/athenaresults/` in the user-space bucket, readable by the user
and delete-protected. This bucket only ever receives a write when a query omits an explicit
`OutputLocation`. **No CORS, because the browser never reads it.**

Its **first and only bucket policy** is written by `modules/spa`, for the ALB access logs — so while
the web tier is switched off, the bucket has no policy at all.
