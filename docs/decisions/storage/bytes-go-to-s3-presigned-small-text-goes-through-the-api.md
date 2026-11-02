---
type: Decision
title: "Bytes go to S3 presigned; small text goes through the API (SPEC-198)"
description: "**Bytes go to S3 presigned; small text goes through the API**, and the document route's **byte cap is what holds the line** — without it it is a second upload path that works perfectly to 6 MB. The cap is on the **stored** body and the response escapes it twice — Cyrillic goes out at 3.5 times its size — so the routes **measure the response**, and a write as the read it enables. The routes never parse and never re-serialise. Bytes go over **`XMLHttpRequest`**, which is a requirement: `fetch` fires no upload-progress event, so it uploads correctly and leaves the bar at 0% — assert an **intermediate** value. **The SERVER decides whether an upload is one `PUT` or multipart**, so the browser holds no threshold; a URL is minted immediately before redemption, **per file or per part, never batched**, and a retried part **re-mints**. Aggregate progress is the per-part **maximum**, monotonic across a retry. The 5 GiB ceiling is a refusal on the **declared** size — a courtesy, not enforcement, since the API keeps no record of an upload."
---

Every S3 call the browser made is a route now, with one split running through the middle of it: a
**document** — a JSON settings file, a `.sql` saved query, a folder marker — travels **in the
response body**, and a **file** travels **directly between the browser and S3** under a presigned
URL. Compute never touches a file's bytes.

**The document route's byte cap is what holds that line.** Without it the content route is a second
upload path that bypasses presigning entirely and works perfectly up to Lambda's 6 MB synchronous
response ceiling — which is to say, for every document the app actually authors, and for a good
number of files too. `MAX_DOCUMENT_BYTES` is half that ceiling, and it is a line on the **stored**
body, checked before the bytes are read — **not the fit**. The response escapes the body twice:
`envelope.success` renders it at `ensure_ascii=True`, and the runtime serializes the whole proxy
response again, escaping every quote and backslash the first pass wrote. Per stored byte that is one
for ASCII, three for a newline or tab, four for a quote or backslash and seven for any other control
character; two-byte text such as Cyrillic or Greek goes out at 3.5 times its stored size, CJK at
2.33 and an emoji at 3.5. So a document under the cap can still pass the ceiling — two megabytes of
Cyrillic goes out at seven — and would fail as a **fault** rather than as the refusal the route
promises. Both read routes (`objects.readContent`, `featureFlags.get`) therefore measure the
response they would send, through `envelope.servable`, and refuse one over the ceiling as
`PayloadTooLarge` with no `limit`, since no stored size corresponds to it; `objects.writeContent`
measures a body as the read it would make possible, so nothing is written that the route could only
fail to return. The per-character costs are pinned by
`test_a_response_is_measured_after_the_runtimes_second_escape`, counted by hand, and were checked
against `awslambdaric`'s marshaller in the pinned base image. Its `ensure_ascii` depends on the
runtime bootstrap's `AWS_EXECUTION_ENV`, and neither setting moves the number, since nothing
non-ASCII survives the first pass.

**The cap used to be the ceiling divided by two as the worst-case escape**, reasoned from the
three-byte case alone: a CJK character stored as three bytes becomes a six-byte `\uXXXX`. That
missed two-byte text (3.5x), control characters (7x) and the runtime's second pass. **Rejected:** a
divisor of seven, the true worst case. It would cut the cap to a seventh of the ceiling and refuse
ASCII documents — JSON settings files, the data-quality report — that fit with room to spare, and it
would still be a model of the wire rather than a measurement of it.

**The document routes never parse.** Parsing server-side is the wrong implementation that looks
identical: it works for every healthy document and turns an unparseable one into a 500 — which puts
SPEC-159's whole quarantine path out of reach, because the classifier never sees the body it must
classify as unreadable. Re-serialising on write is the same defect from the other side: it changes
key order and whitespace, which breaks nothing visible and breaks byte-identity.

**An upload is one `PUT` over `XMLHttpRequest`, and the transport is a requirement.** *(The
transport requirement stands; "one `PUT`" was superseded by SPEC-216 — see the note below.)* `fetch` fires
no upload-progress event, so a `fetch` implementation uploads correctly and leaves the progress bar
at 0% until it jumps to 100% — a shipped feature deleted by a transport choice, with every "the
upload succeeded" test still green. The assertion is on an **intermediate** value, and
`XMLHttpRequest` is confined to one module by a sweep that widens the existing `fetch` one: a rule
forbidding `fetch` and silent about `XMLHttpRequest` permits the same escape hatch under another
name.

**Three consequences of one `PUT` where `lib-storage` auto-multiparted, stated rather than
discovered.** (1) The 5 GiB ceiling **does not move** — it is exactly the single-`PUT` cap and
exactly what the configured maximum already clamped to, and `maxUploadBytes()` now clamps to it so
an operator who raises the configured value gets a refusal rather than an `EntityTooLarge` from S3
at the end of a long transfer. (2) There is **no part-level retry** any more: a dropped connection
restarts the whole file. Accepted; the route trio a later spec would add is
`create-multipart` / `sign-part` / `complete-multipart`, named here so it is added rather than
rediscovered. (3) `MULTIPART_PART_SIZE` and `PART_CONCURRENCY` are gone.

> **Superseded in part by SPEC-216 (2026-09-01).** (2) is reversed — part-level retry exists again,
> and the route trio named above was built with a fourth for abort. (1) still holds, but for a
> different reason and it is worth knowing which: S3 used to enforce the ceiling *unforgeably* by
> refusing an over-size single `PUT`, and multipart has no such limit, so the ceiling is now a
> server-side refusal in the create route. (3) still holds — the names came back in
> `multipartUpload.ts` — only `PART_CONCURRENCY`, and meaning what it always meant, though at a
> different value and against a different budget. `MULTIPART_PART_SIZE` did not come back; the
> only live constant of that name is `cpcommon/transfer/copy.py`'s, which is 1 GiB and is a
> server-side `UploadPartCopy` range, unrelated. Full entry: *An upload's shape is the server's
> decision, and a part is sized so the expiry premise stops mattering*, below.

**The URL is minted per FILE, at the moment that file starts.** A batch mint ages while the queue
drains: with three files in flight and a 15-minute window, the fiftieth file's URL would be signed
long before it was redeemed, pass preflight cleanly and 403 at the end. The mint therefore lives
*inside* `uploadFile`, which is what makes "per file" structural rather than a convention.

A URL is minted immediately before redemption, per file or per part, never batched, and a retried part re-mints.

## History

### 2026-09-01

- **Changed:** SPEC-216 reversed the no-part-level-retry consequence and brought multipart back, so the 5 GiB ceiling is now a server-side refusal in the create route rather than S3's own single-`PUT` limit.

### 2026-08-29

- **Settled:** SPEC-198.
