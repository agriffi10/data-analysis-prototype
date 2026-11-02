---
type: Decision
title: "The metadata fix: a latent bug on all three planes, surfaced by a round trip"
description: "Copies keep content type and user metadata on both paths, with the multipart path re-stating them from a `HeadObject`; tag sets are still lost above 5 GiB, so any plane that starts tagging must fix that."
---

FR-003 AC5 asked for `MetadataDirective: COPY` on both copies. `CopyObject` has that directive and
defaults to it; **`CreateMultipartUpload` has no such directive at all**, and `UploadPartCopy` moves
bytes and nothing else. So every object over `MULTIPART_COPY_THRESHOLD` (5 GiB) came out of a copy
as `binary/octet-stream` with its user metadata gone — silently, and on table-share and file-send as
much as here.

It surfaced on this spec because an archive round trip is the first operation in this repo that
copies an object **twice** and hands it back to the user expecting it unchanged; a shared table is
read through Athena, which does not care about a content type. The fix is explicit on the single
path (stated rather than assumed, because the path beside it proves the default is not universal)
and a `HeadObject` on the multipart path whose headers are re-stated on the create call, skipping
anything the source does not carry so the two existing callers' requests are unchanged below 5 GiB.

**One thing `MetadataDirective` carries that the multipart path still does not: the object's TAG
SET.** `CopyObject` copies tags by default; `HeadObject` does not report them, so parity would cost
a `GetObjectTagging` per object over 5 GiB. Nothing in this portal tags an object, so it is
**recorded in `copy.py` rather than bought** — the moment a plane starts tagging, every object over
the threshold will start losing them silently.

**A test that fixtured only a small object would have passed while the bug lived on**, so the round
trip runs at both copy strategies. That is the same shape as SPEC-163's recipes that re-implemented
the gate they were testing: the fixture, not the assertion, is what decided whether the test could
fail.

## History

### 2026-08-12

- **Settled:** entered the register.
