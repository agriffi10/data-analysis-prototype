---
type: Decision
title: "The bucket the browser has no relationship with"
description: "The browser reaches the vault only by a restore request: no CORS, no `connect-src`, no portal-role statement, and a bucket Deny that includes `s3:RestoreObject`; it also may not write to the archive receipt folders."
---

No CORS configuration, no entry in the SPEC-140 `connect-src`, and the portal role holds **zero**
statements naming the ARN. The only route to archived bytes is a restore request through this plane.
The bucket's own policy is a `StringNotLike aws:PrincipalArn` Deny admitting the archive execution
role, the deploy role and the account root — so an identity policy that later grew a statement here
would still be refused. It denies `s3:RestoreObject` as well as the four ordinary actions:
`RestoreObject` is what makes a `GLACIER` object readable and is not covered by `GetObject`, so a
policy without it would leave any principal able to start a **billed** retrieval on someone's
archive.

What the browser *does* get is a **Deny** on `PutObject` / `DeleteObject` / `AbortMultipartUpload`
under `archive/` in both space buckets (FR-006). A user who can rewrite a receipt can misreport what
was archived. `AbortMultipartUpload` is included even though a `PutObject` Deny already blocks
multipart writes: without abort, a half-started upload cannot be tidied and its parts sit billed and
invisible. `GetObject`/`ListBucket` are untouched — the receipt is deliberately a plain text file
the user downloads and reads themselves, which leaves the no-preview rule intact. **The UI mirror is
owed and lands in SPEC-172**; an IAM Deny with no UI counterpart produces a bare `AccessDenied` for
a rule this application itself authored.

All of this is a **negative** claim, which is the kind that rots without anything looking wrong, so
`lambdas/test_archive_bucket_isolation.py` asserts it against the IaC rather than describing it.

## History

### 2026-08-12

- **Settled:** entered the register.
