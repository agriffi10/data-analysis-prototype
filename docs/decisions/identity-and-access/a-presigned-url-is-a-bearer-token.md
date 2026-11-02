---
type: Decision
title: "A presigned URL is a bearer token (SPEC-198)"
description: "**A presigned URL is a BEARER TOKEN** — minted only after exactly the authorization the direct call would have had, signed by the **caller's own assumed session**, and in **no emitted record** (the span carries the key's *length*). Its lifetime is clamped to the **credential that signed**, read in the same call — never to `DurationSeconds`, which agrees today and will not under Access Grants, and never by assuming a second time."
---

AWS's own words: presigned URLs "are bearer tokens that grant access to those who possess them". The
capability **is** the URL, so everything true of a credential is true of it.

**Minted only after exactly the authorization the direct call would have had** — the same space
resolution from claims, the same membership check, the same protected-location rules — and signed
with the **caller's own assumed session**, never the API's execution role. A test asserts the
signing credentials come from `user_client`; the wrong one mints a working URL against the wrong
identity, which is the isolation question turned inside out.

**It appears in no emitted record.** The span carries `route_id`, the space kind and the key's
**length** — never the URL and never the query string. The obvious wrong implementation is a debug
field stamping the response body, and it would look like good telemetry. The `error.stack` scrub
covers these routes, and the assertion is a sentinel in an exception **message** or a log **field**,
not a URL-shaped local: `traceback.format_exception` renders each frame's source line and never its
locals, so a test that binds a URL to a local and raises can never fail whatever the code does. The
live exposure is this repo's own code interpolating a signed URL into a message.

**The lifetime is clamped to the SIGNING SESSION's remaining life, read from the credential that
signed.** Not from `DurationSeconds`: the two agree today and will not later — `transition_plan.md`
§3.9 signs from Access-Grants-vended credentials in the target environment, whose maximum differs,
and a clamp computed as `min(900, DURATION_SECONDS)` passes every test here and mints URLs that
outlive their own signature there. The trap that cost this an implementation: `user_client()` assumes
internally, so a clamp that assumes *again* is a **second read**, and the cache refuses a session
with under ~30s left — read 2 returns a fresh hour-long session while read 1's near-dead one signed
the URL. Measured: signed by a credential with 20 seconds left, `expiresAt` came back 15 minutes
out. `identity.py` therefore exposes **one accessor returning the client and the credentials backing
it**.

**The expiry is evaluated when S3 RECEIVES the request, not when the transfer completes.** That is
the premise the whole single-`PUT` design rests on, it is read from AWS's documentation rather than
measured, and it is recorded as **owed** — if it were false, every large upload would fail at the
tail with an opaque 403 after the user had waited.

## History

### 2026-08-29

- **Settled:** SPEC-198.
