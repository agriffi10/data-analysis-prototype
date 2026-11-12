# archive-vault

Bucket 5, the GLACIER vault the archive plane writes into and restores from, and its bucket
policy. It sits outside the plane's call to [`../control-plane`](../control-plane/README.md)
because it is not part of the machine, and because this is the one place in the stack where a
mistake is unrecoverable. The plane and the reasoning are `infra/plane-archive.tf` and
`infra/planes/archive/README.md`.

- **The browser has no relationship with this bucket**: no CORS, no `connect-src` entry, and the
  portal role names it nowhere. The only route to archived bytes is a restore request.
- **The bucket policy's Deny excepts the deploy role**, or the deploy role cannot `HeadBucket`, a
  refresh sees the bucket as deleted, and every plan proposes a destructive recreate.
- **The execution role is named by a constructed ARN string** from the root, shared with the
  user-space allowlist entry, so there is one construction of the name.
- **Objects expire at `archive_retention_days`** (seven years). A ceiling, not a WORM floor: Object
  Lock is out of scope.
