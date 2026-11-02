---
type: Decision
title: "A notification payload is bounded by BYTES, and the binding case is the PLAIN one (SPEC-191)"
description: "A file-operations notification payload is bounded by bytes as well as count, at 1 KiB, adding conflicted items only while it fits and setting `more` when any are dropped, and the writer rejects rather than truncates an oversize payload."
---

The inbox is capped at 200 rows and the browser fetches and `JSON.parse`s the **whole** document on
every 60-second poll, from the header bell, on every page — so a worst-case inbox is a recurring
per-minute download rather than a one-off read. Against that, one conflicted item is ~200 bytes at
ordinary key lengths and ~12,000 at this plane's caps: S3 keys are 1,024 bytes of arbitrary UTF-8
and JSON escaping turns a control character into six. A count of three is therefore either
negligible or 36 KB, and the count alone cannot tell those apart.

So the payload is bounded by **bytes as well as count**, enforced at mint by adding conflicted items
only while the serialised payload still fits and setting `more` when any are dropped — for either
reason. That is what makes the pathological case *safe* rather than merely small: a run whose keys
are at S3's limit carries fewer items than the count allows, or none, and says so.

**The budget the byte cap is derived from is the MARGINAL one** — the structured field may not add
more to the worst-case inbox than the row already costs without it. An absolute number would be one
chosen and then defended, and the row's own fixed cost (a percent-encoded link, a 1,024-byte
destination prefix) is not something this spec controls.

**The estimate was overturned twice, and both corrections came from measuring rather than
reasoning.** 4 KiB was written down first. The first measurement refused it — and the binding case
turned out to be the **plain** one, not the escape-heavy one, because a control character expands
*six* times inside the JSON payload and only *three* times in the percent-encoded link beside it, so
the row a payload competes against is **smaller** when the keys are hostile. Then a reviewer found
the second error: that measurement compared the budget against a row **that already carried the
payload head**, which weighs the field against itself. Measured against a row carrying no payload at
all, the allowance is **1,674 bytes**, not 3,047. **The cap is 1 KiB.**

**The head is mandatory, so its one unbounded term is capped separately.** Dropping conflicts cannot
help when the head alone is over budget, and nothing validates the LENGTH of a destination prefix on
the way in — only its containment. Left unbounded, a hand-crafted envelope with a multi-kilobyte
prefix would push the payload past the writer's ceiling and lose the **whole message**, on the queue
whose dead-letter queue is deliberately undrained, after the data had already moved.
`FILE_OPS_NOTIFIED_PREFIX_BYTES` is S3's own key limit: a prefix longer than a legal key cannot
produce a legal destination key, so the run it describes copied nothing and a re-submit of it would
be meaningless.

**The producer's bound and the writer's refusal are two numbers in two languages.** A payload the
producer considers fine and the writer refuses does not lose its conflict list, it loses the
**whole message** — on the one queue whose dead-letter queue is deliberately undrained. So
`notifications_writer.MAX_PAYLOAD_BYTES` **rejects** (never truncates) an oversize payload, and a
test reads that ceiling back out of the Lambda and asserts the largest payload this plane can emit
sits under it.

## History

### 2026-08-17

- **Settled:** SPEC-191.
