---
type: Decision
title: "Table-share's dedup id is keyed on the verified actor, not the token (SPEC-200)"
description: "Table-share's FIFO dedup id hashes the verified actor in position 0 and no token, so a token refresh cannot defeat the double-submit guard; the actor must stay in it, or one user's share collapses into another's."
---

This is the one FIFO derivation the port deliberately changed; the other nine are reproduced
byte-for-byte against golden vectors captured from the browser before it was deleted.

The browser hashed `[idToken, source, tableName, sortedRecipients, minuteBucket]`. Table-share is the
only plane with **no `requestId`**, so that digest is the entire double-submit guard — and because the
token was an input, two submits a minute apart with a token refresh between them produced two
different digests and therefore **two shares**. The guard lapsed silently, and it would have stopped
working entirely once the token went away.

It now hashes the verified actor in position 0. Two properties evidence the change rather than assert
it: the browser's own digest **moves** across a refresh where the new one does not, and two different
users submitting the identical share in the same minute still get **different** ids — dropping the
actor from the canonical form entirely, which is the obvious simplification, would collapse one user's
share into another's and deliver nothing.

The canonical form is pinned field by field, because the vector replay cannot cover the one derivation
whose whole point is that it no longer matches. `ensure_ascii` is off so a non-ASCII space name
digests the way `JSON.stringify` would — a divergence no ASCII fixture can show.

## History

### 2026-08-29

- **Settled:** SPEC-200.
