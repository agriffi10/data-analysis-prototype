---
type: Decision
title: "Notifications deduplicate per recipient, so a borrowed request id cannot drop someone else's notice (control-plane-wide)"
description: "**Notifications deduplicate per RECIPIENT.** Most producers key a notice on `{requestId}:{outcome}`, and a request id is the caller's choice, so the requests queue's `deduplication_scope` is `messageGroup` and every sender's group is the recipient: two notices collapse only when they go to the same person. Deduplicated across the queue, a request borrowing another member's id dropped that member's notice. Per recipient. A notice sent with **no** dedup id is deduplicated on its body, and a generic sentence is the same for two runs, so it **names its run in the payload**; a sweep refuses a send that names none. A dedup id **replaces** the body as the key, so a token per outcome merges two notices one run words differently on purpose — a token names the reason and recipient too. Named run (`a-notice-with-no-dedup-id-names-its-run-in-the-payload-so-two-runs.md`)."
---

**A notice's dedup key is built from a value the caller chose.** Most producers pass
`{requestId}:{outcome}` — `cpcommon.notify.dedup_id` — and a request id is whatever the sender of the
request put in it. The requests queue deduplicated across the whole queue, so any notice sent under
another person's key within five minutes was dropped, whoever it was for. Repairing one plane turned
up two instances before the class was named: a data-quality run reusing another run's id and
refused would have been notified under the holder's `failure` key, and table-builder's failure
notices go out under the same shape of key, so a shared-space member who reads an in-flight check's
id from the reports folder listing could send a table-builder request under it and suppress the
check's failure notice — and the dashboard lists completed checks only, so nothing else says it
failed.

**The queue deduplicates within a message group instead, and the group is the recipient.**
`deduplication_scope = "messageGroup"` on the requests queue; `cpcommon.notify.emit_notification`
already sets `MessageGroupId` to the recipient's username, which is what makes the writer
single-threaded per user. A notice can now collapse only with another notice to the same person,
which is every duplicate a producer means to collapse — a verb and the notify state reporting one
failure — and a borrowed id reaches only the borrower's own notices. The shared-space producers that
put a recipient in their keys to survive the old scope are unaffected.
Throughput stays per queue: `perMessageGroupId` is the high-throughput mode, which nothing here
needs. The attribute updates in place — the provider does not replace a queue for it.

**Rejected: fixing each producer.** Keying data quality's failure notices on the execution ARN
closes that plane alone and leaves table-builder, file-ops and archive keyed as before; a key per
producer is the per-site answer the class had already outrun twice.

**What it does not change.** The same person can still lose a notice to another of their own under
the same key — two of their requests sent with one id — because that is what deduplication is for.

## History

### 2026-09-16

- **Settled:** entered the register.
