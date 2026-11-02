---
type: Decision
title: "An upload's shape is the server's decision, and a part is sized so the expiry premise stops mattering (SPEC-216)"
description: "`MULTIPART_THRESHOLD_BYTES` is `MULTIPART_PART_BYTES`, computed so a part finishes in half its presigned window on the slowest supported uplink; the server alone decides `PUT` or multipart, and the browser writes parts by index and checks the plan's arithmetic."
---

An upload is no longer one `PUT`. `objects.upload` answers **either** a presigned `PUT` **or** a
multipart plan, and three more routes sign each part, assemble them and abandon them.

**The threshold is one quantity, and the browser never learns it.** "What fits inside one presigned
window on the slowest connection this product supports" bounds a part *and* bounds the largest
object that can be trusted in a single `PUT` — so `MULTIPART_THRESHOLD_BYTES` **is**
`MULTIPART_PART_BYTES`, bound by identity rather than restated. It is computed, not chosen:
`clamp(MIN_SUPPORTED_UPLINK_BYTES_PER_SEC × PART_URL_EXPIRY_SECONDS / PART_WINDOW_SAFETY_FACTOR,
5 MiB, 5 GiB)` = 112,500,000 bytes, and its test states that number so moving any input is visible.
The uplink floor (2 Mbps) is a **product decision stated as one**. The generator emits types, not
constants, so a browser-side fork would need a second copy of a policy number — and a drifted copy
sends files down the wrong path with **nothing failing**. Rejected in favour of one decision site.

**This makes the design correct under either reading of the expiry premise, which is not the same as
settling it.** SPEC-198 accepted, unmeasured, that S3 evaluates a presigned expiry at request
*receipt*. A part minted immediately before it is sent and sized to finish in *half* its window is
sound either way. The premise stays owed, because it still governs a presigned **download**.

**Where the design would fail silently, and what holds each one.** A part that cannot be placed by
its number corrupts the object with S3's blessing — every ETag is genuine, the assembly succeeds,
and the user is told it worked; parts are therefore written **by index**, and the guard needs the
one retry shape where a later part settles first. A plan whose parts cannot cover the file
truncates it and reports success; the browser checks the **arithmetic**, not just that the members
are present. Aggregate progress is the per-part **maximum** — never last-value-wins, which makes the
bar fall on a retry, and never a running sum; a failed attempt's high-water mark is deliberately
kept. And every discard is fired **without** the caller's signal and **without** being awaited: the
queue holds the row until the upload resolves, so an awaited discard leaves a user watching a
progress bar for the client's whole timeout on the arm they meet most often.

**Three things the retirement had to preserve rather than delete.** `UPLOAD_URL_EXPIRY_SECONDS` is
**kept** — it stopped being the retiring route's constant the moment the create route's single
branch used it. The marker-key refusal and the window, clamp, content-type and occupied-key
assertions were **re-pointed** at the new route *before* the old one went, because a deletion leaves
nothing for a reviewer to read. And `test_presign.py`'s two parameterised suites cover upload *and*
download, so only their upload case was removed.

**The ceiling is refused here, and refusing is not enforcing.** S3 used to hold it *unforgeably*
by rejecting an over-size single `PUT`. Multipart has no such limit, and nothing replaces it: the
declared `size` is a **planning input** that nothing verifies, `sign_part` cannot bound a part
number by the plan's count and `complete` cannot check what was sent, because by design the API
keeps **no record of an upload** — and a `ListParts` audit per upload was declined. So a client
that deliberately under-declares can still assemble an object above the ceiling. What the refusal
buys is real but narrower than enforcement: an honest over-size upload fails at create rather than
after its bytes, and the ceiling is not silently **209×** what the product states. Closing the gap
needs server-side upload state, which is a different decision from this one. Its arithmetic is integer throughout, because a caller's number is
arbitrary-precision and float conversion turns an expected refusal into a 500 carrying a stack.

## History

### 2026-08-29

- **Settled:** SPEC-216.
