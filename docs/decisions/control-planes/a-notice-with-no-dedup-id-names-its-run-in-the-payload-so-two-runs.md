---
type: Decision
title: "A notice with no dedup id names its run in the payload, so two runs ending alike stay two notices (control-plane-wide)"
description: "A notice with no dedup id carries `payload: {\"requestId\": …}` because the queue deduplicates it on its body, and a sweep refuses an `emit_notification` passing neither `dedup_id` nor `payload`; file-send and table-share successes take a token instead."
---

**The queue deduplicates such a notice on its body, and a body can name nothing about the run.**
Archive's and file-send's failure notices passed no dedup id and relied on content dedup to make a
verb's retry safe, the shape both inherited from table-share. Their generic sentences — "something
went wrong", a timeout — carry no count or file, so two runs by one user failing alike inside five
minutes rendered byte-identical bodies and were delivered once, and the second run's failure was
never told. It was the third time a notice shipped naming no run, after archive's success notices
and file-operations' failure rows — whose missing id an in-flight reader noticed rather than the
queue — each found late and repaired one plane at a time.

**Each such notice now carries `payload: {"requestId": …}`**, built by
`cpcommon.notify.request_payload`, which reads the id through `observability.request_id_of` from
every shape a failure reaches an emitter in: a verb's event, validate-authorize's own refusal, the
forwarded request where the error replaced the state, and the raw input of a timed-out execution —
never the state, which the timeout event does not carry. A retry of one run composes the same body, so content
dedup still collapses it. The browser keeps a payload whose `requestId` is well formed and renders
no control for one without conflicts, so the only thing a user sees change is the second notice.
`lambdas/test_failure_notices_name_their_run.py` drives every door through the real sender to a
recording queue, and with the id removed its positive control still shows the two runs collapsing.

**Rejected: a dedup token per failure outcome.** It would merge the verb decorator's
unexpected-error notice with notify-failure's engine-error notice. The two sentences differ and both
are sent on purpose; a token that collapsed them is a behaviour change this repair does not make.

**File-send's success notices take a token, not a payload**, and a review found them in the same
class: after a conflict the recipient moves the first delivery, the re-send succeeds with the first
send's sentence, and the sender, the recipient and the space owner each lost the second notice.
They pass `dedup_id(requestId, "sent:{kind}:{name}")` and `"received:{kind}:{name}"`, one per
recipient and per addressee. A payload would put the sender's request id in another user's inbox,
where it names nothing they did; a token never leaves the queue.

**Table-share names its run with a token built from the execution's name**, having no request id
in its API body. `StampExecution` runs directly after validate-authorize, so every notifying verb
holds `execution.name`; `RecordFailure` copies it from `$$.Execution.Name`, a read no seed has to supply;
the timeout door reads the event's `detail.name`. Validate-authorize runs before any state exists to
carry the name and uses the SQS message id, and its notices never meet another door's.
**The failure token carries the reason** — `failure:{reason}`, plus `:{kind}:{name}` for a
recipient — because the merge rejected above is live on this plane: the decorator's crash notice
("something went wrong. Please try again.") and notify-failure's engine notice ("something went
wrong.") are both sent, and an explicit id replaces the body as what the queue compares, so a token
of `failure` alone would merge them, and one run's refusals of two recipients alike with them.
Successes take file-send's `sent:` and `received:{kind}:{name}`.
`lambdas/test_table_share_notices_name_their_run.py` drives every door through the real sender and
holds those in-run pairs apart, and the machine's own test pins the paths the name is read from.

**A sweep holds the class rather than the planes.** `lambdas/test_notification_sends_name_their_run.py`
reads every `emit_notification` call and refuses one passing neither `dedup_id` nor `payload`,
against a counted exemption list, now empty. The sweep
cannot see a name that is None at run time — it refuses the send that forgot to name the run at
all, which is how every instance so far was written.

## History

### 2026-09-16

- **Settled:** entered the register.
