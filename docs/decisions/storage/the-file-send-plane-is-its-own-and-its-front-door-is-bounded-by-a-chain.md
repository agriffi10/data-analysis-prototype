---
type: Decision
title: "The file-send plane is its own, and its front door is bounded by a chain (SPEC-164)"
description: "File send is its own control plane, never a mode on table share, and its front door keeps two caps, item count and serialised bytes, with the byte cap measured along the chain through `StartExecution`; do not reintroduce a single cap."
---

**Decision.** "Send these files to Bob" gets its **own control plane** — its own FIFO queue, DLQ,
Pipe, Standard state machine, execution role and `fscommon` domain layer — rather than becoming a
mode on table share's.

**Why not a mode.** The two features share an *algorithm* (`cpcommon.transfer`) and nothing else:
different request contract, different authorization question, different failure vocabulary. Folding
them together would put one queue and one DLQ under two unrelated user features, and the DLQ drain,
which names the feature by the DLQ a request lands on, would report a dead-lettered send as a
share. The pattern is reused; the resources never are.

**The envelope is flat, and that is a contract with a shared security path.** `actor` is the raw ID
token at the **top level**, not `actor.idToken`. The spec was written nested and was amended during
the build, because SPEC-126's drain reads `body.get(token_field)` flatly and `_redacted` replaces
**top-level keys only** — a nested token would have (1) resolved no recipient on every
dead-lettered send, silently, since the drain swallows and returns, and (2) written the raw JWT to
CloudWatch, whose audience is far wider than the queue's. One envelope shape across five planes
beat teaching a shared security path a second one.

> **Still true, and no longer about a token (SPEC-201, 2026-08-30).** The reasoning holds and its
> conclusion was right twice over: the flat field is what the drain redacts, and the *reason* it
> had to be flat is exactly why the API's `identity` block is **nested** — a flat verified `actor`
> would have overwritten the very field four planes were verifying. The flat field itself is now
> a legacy carrier: no plane reads it, the drain blanks it as a stale-message token, ~~and it is
> removed from the wire when the API stops writing one. It stays in each plane's allowed-field set
> until then, deliberately~~ **— superseded by SPEC-201's second step:** the API no longer writes
> it, and it stays in each plane's allowed-field set anyway, deliberately — tightening it turns a
> pre-cutover message into `malformed_event` instead of the `unauthorized` refusal that path is
> meant to produce.

**Source authorization is about the space's status, never the member's join chip.** A `personal`
source must equal the verified username; a `shared` source needs `cpcommon.registry
.is_active_member`. The spec's original wording ("`pending`, `leaving`, absent") named a status
that does not exist and one that is a *member* concept — reading it that way would have reversed
**SPEC-073**, denying a send for files the same user can already browse, download and table-share.

**Containment is three rules, and the third was found by review.** (a) the root comparison is
trailing-slash-normalised, so `alice2/` is not inside `alice/`; (b) any `.`/`..` **path segment** is
refused, because `"alice/../bob/x".startswith("alice/")` is `True` — not exploitable against S3
today, but the same string becomes the item name in the destination key; (c) `athenaresults/` is
refused as the folder, as anything beneath it, **and as any folder that CONTAINS it**. (c) exists
because selecting the space root passes (a) and (b), and SPEC-165 expands a folder by listing its
prefix — in a shared space that is other members' query results leaving with the send. Folder keys
are normalised to a trailing slash for the same reason: `ListObjectsV2(Prefix="alice/athenaresult")`
matches `alice/athenaresults/…`. The results rule is **new for this plane**, not a reuse:
`protectedFolders.ts` keeps three deliberately divergent lists and in none of them is copying *out*
of that folder refused.

**Two caps, because there are two quantities, and the byte one is bounded by a CHAIN.**
`SEND_MAX_ITEMS` (200) bounds per-item work — two containment checks now, one `ListObjectsV2` per
folder in SPEC-165. `SEND_MAX_ITEM_BYTES` (96 KiB) bounds the serialised selection. **A count cap
cannot bound bytes**: S3 keys are arbitrary UTF-8 and JSON escaping expands `"` to two bytes and a
control character to six, so 200 items at a 1024-byte key measure 216 KB of ASCII or 1.2 MB of
`\x01`. And **a byte cap measured against the state alone is not enough either**: the browser's SQS
body carries the selection, the Pipe re-escapes that body into the record it hands to
`StartExecution`, and that input is capped at 256 KB too — so a quote-heavy selection arrives at
**twice** its measured size, and an over-limit request cannot start an execution at all. Both wrong
models shipped in review and each read as satisfied. The producer mirrors both caps (a request too
large for `StartExecution` never reaches the verb that would refuse it) and a test holds the
TypeScript numbers against the Python ones.

**Do NOT** reintroduce a single cap, and do not raise either without re-running
`test_config_fscommon`, which computes all three links.

**The failure path reads the request from the context object.** `validate-authorize`'s input is the
Pipe's JSON *array*, so its Catch has no object to merge a `ResultPath` into and the error
**replaces** the state — taking the only copy of the caller's token with it. The seed therefore
reads `$$.Execution.Input`, which survives whatever the Catch did; reading `$$` in a **Pass** state
is SPEC-157's recorded shape. Without it `NotifyFailure` takes its no-recipient branch on every
single failure — SPEC-152 satisfied on paper and silent in practice, on exactly the cold-start and
timeout failures it exists for. **Threading the request through the state instead was tried and
rejected**: the Pipe record carries the same selection again as an escaped string, so it roughly
doubles the payload for the whole run.

**FR-006 — the user-space bucket policy's allowlist is hand-maintained, and this is the shape that
rots.** An explicit resource-policy Deny beats an identity-policy Allow, so a plane whose execution
role is missing from `user-space-bucket-policy.json.tftpl` is denied by the bucket however correct
its own grants are. For a send the failure is asymmetric enough to read as a code bug: every
`space` recipient succeeds (the shared-space bucket has no bucket policy) and every `user` recipient
fails `AccessDenied`. The change is three parts — a variable in `modules/data`, the
`templatefile()` argument, root wiring — with the ARN a **constructed string**, because an
unknown-at-plan ARN inside a list silently drops the change.
`lambdas/test_user_space_bucket_allowlist.py` pins it three ways and was verified against a
deliberate omission.

## History

### 2026-08-30

- **Changed:** SPEC-201 made the flat `actor` field a legacy carrier no plane reads; the API no longer writes it, and it stays in each plane's allowed-field set so a pre-cutover message is refused as `unauthorized`.

### 2026-08-11

- **Settled:** SPEC-164.
