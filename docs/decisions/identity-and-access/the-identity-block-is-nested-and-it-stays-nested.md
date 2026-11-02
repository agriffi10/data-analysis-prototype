---
type: Decision
title: "The identity block is nested, and it stays nested (SPEC-200)"
description: "Every control-plane message from the API carries a nested `identity` block `{actor, delegated_by, assurance}`, and it stays nested; `delegated_by` is present as null, and nothing secret goes in it because the drain redacts top-level keys only."
---

Every control-plane message the API sends carries one extra top-level key, `identity`, holding
`{actor, delegated_by, assurance}` — the verified username, `null`, and the literal `interactive`.

**Nesting is forced, not stylistic.** On table-share, file-send, archive and file-ops the top-level
field named `actor` ~~**is the raw ID token today**~~ **— superseded by SPEC-201:** was the raw ID
token when this was decided, and now holds one only in a message enqueued before the API stopped
sending one. A flat verified `actor` would have overwritten the very field those four planes then
verified, which is precisely the ordering failure the two-spec rollout existed to avoid. It stays
nested after the cutover: SPEC-201 took the token off the wire rather than moving the block into its
place, so there is no second migration and no window in which one plane's `actor` is a username
while another's is still a JWT.

`delegated_by` is **present rather than omitted** — an absent key and a null key are different to a
strict parser, and the planes are written to refuse the absent one. `assurance` names the assurance
**kind**, not the mechanism: `verified-id-token` would need renaming the day the provider changes or a
machine-facing caller mints a delegated one.

**Nothing in the block is secret, and that is load-bearing.** The dead-letter drain's redaction
replaces TOP-LEVEL keys only, so anything nested here reaches CloudWatch verbatim when a message
dead-letters. A key set is asserted rather than the absence of a token inspected by eye.

## History

### 2026-08-29

- **Settled:** SPEC-200.
