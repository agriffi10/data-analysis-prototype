---
type: Decision
title: "The credential cache is keyed on the whole tag set (SPEC-196)"
description: "**The credential cache is keyed on the WHOLE tag set** — never the username alone, which freezes membership until the next cold start, and never nothing, which serves B the session of A. **A presigned URL is not a request** and takes `signing_client(covering=…)`, forcing a fresh session rather than clamping against a near-dead one. A short window is *correctly clamped*, so no clamp test can see it."
---

**A warm Lambda serves many callers in sequence and nothing about it is per-user.** Trace baggage is *cleared* at the start of every invocation precisely so one invocation's identity cannot leak onto the next; a credential cache deliberately **survives** the invocation, so it must be **keyed** instead — on the username *and* the ordered membership slots.

**Never the username alone**: that pins a caller to whichever membership set their first request of the hour happened to carry, turning refresh-to-propagate into refresh-and-nothing-happens. **Never nothing at all**: that serves the second caller the first caller's session, which succeeds against the wrong identity with the right-looking data. **None of this is visible to a single-user test**, which is why the assertion is a sequence in one process — request A, then B, then A again inside the margin — and why each clause is load-bearing: without the credential check a shared cache passes; without the call count a cache keyed on the request id, safe but useless, passes; without the tag check a cache that re-assumes with the previous caller's tags passes. It is measured on the access key the **client constructor** recorded, because reading it back out of the cache measures the cache rather than the thing a route can call.

**The expiry margin is the life of one REQUEST, derived from the function's own timeout** — the schedulable unit — with the longest downstream call subsumed by the same bound rather than omitted from it. No clock-skew literal is invented on top: the single forced re-assume **is** that allowance. The retry runs on a **new** client, because boto3 binds credentials at construction, so a proxy that re-assumes and re-calls the object it already holds fails again — fail-closed, but decorative, and green.

**And a PRESIGNED URL is not a request, so it does not take that margin.** The schedulable unit for
a URL is the window it is signed for, which outlives the invocation that minted it — so `_usable`'s
one-request margin, applied to presigning, hands back any session with half a minute left and the
clamp signs for whatever remains. The window a user gets is then a draw from roughly the whole hour
rather than the number the route asked for: on a uniform model, **about a quarter of mints land
under 900 s and about one in a hundred under a minute.** `signing_client` therefore takes
`covering=` and forces a fresh session when the cached one cannot span it. One `AssumeRole`, tens of
milliseconds, on the minority of mints that draw short.

**It is not visible in a passing test, which is why it needed one of its own.** Every offline
assertion about the clamp is satisfied by a short window, because a short window *is* correctly
clamped — the clamp and the draw are different questions and only the clamp had a test. The clamp
stays as the last line of defence for the case the force cannot fix: an AWS ceiling shorter than the
ask, which role chaining makes real at one hour.

**What this does NOT fix.** An upload slower than the configured window still depends on S3
evaluating a presigned expiry when it **receives** the request rather than when the transfer
completes — SPEC-198 FR-005 AC8, read from AWS's documentation and unmeasured. This change makes
that check *interpretable*: a failed multi-GiB upload can now only mean the premise is false, where
before it could equally have meant a short draw. The real answer to a transfer longer than any
window is multipart, which is SPEC-216.

## History

### 2026-08-27

- **Settled:** SPEC-196.
