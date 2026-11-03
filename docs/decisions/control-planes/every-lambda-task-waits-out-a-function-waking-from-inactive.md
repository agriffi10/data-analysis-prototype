---
type: Decision
title: "Every Lambda Task waits out a function waking from Inactive, because the invoke that wakes it is rejected"
description: "**Every Lambda Task in the eight machines carries a second retrier for the three errors Invoke raises on a function not ready to run** — `Lambda.ResourceNotReadyException`, `Lambda.ResourceConflictException`, `Lambda.CodeArtifactUserPendingException` — waiting 75 s in all. An image function idle for weeks goes Inactive and Lambda rejects the invoke that wakes it; **Step Functions matches error names exactly**, so the service errors every Task already retried never matched it. **AWS names no exception for the image case**, so all three are retried and the real one is owed a reading. Each is a refusal before any code runs, which is why `Convert` carries it too. **The three ceiling tests that count retries charge the 75 s once per function, read from the ASL**: raise it and file-ops, whose headroom is the tightest, goes red. An earlier retrier naming `States.ALL` or `States.TaskFailed` would shadow it; `test_state_machines_cpcommon.py` judges each name by the retrier that answers it."
---

After 19 days without a deploy, 86 of the 91 production functions were Inactive, the planes'
functions among them. AWS documents that an image function idle for weeks goes Inactive, that
Lambda rejects the first invocation while it re-optimises the image, and that an invoke reactivates
it; the 2026-11-02 deploy showed an image update wakes it too. The keep-warm decision in
`infrastructure/` wakes the three functions a user reaches first; this one covers the 81 distinct
functions the eight machines invoke.

**What failed.** Every one of the 93 Lambda Tasks retried `Lambda.ServiceException`,
`Lambda.AWSLambdaException`, `Lambda.SdkClientException` and `Lambda.TooManyRequestsException`
for 14 s, except `Convert`, which retried `TransientError` alone. Step Functions matches
`ErrorEquals` by exact, case-sensitive name, with `States.ALL` and `States.TaskFailed` the only
wildcards, so no retrier answered a not-ready rejection. The Task's Catch took the run down its
failure path, whose functions were asleep too. Every function on a plane's path goes Inactive
together, so a user retrying would meet the next sleeping function each time.

**Which error, and why three.** AWS names no exception for an Inactive image function. Invoke
documents `ResourceNotReadyException` (502) as the error for an inactive function, in words written
for a lost VPC connection; `CodeArtifactUserPendingException` (409) tells the caller to wait for
the function to become Active; `ResourceConflictException` (409) is the generic "another operation
is in progress". The one public account of an image function waking, a third party's, caught the
first and the last and does not say which arrived. Production history cannot settle it: no run in
the history Step Functions keeps followed a quiet spell, and a scan of every execution found no
`Lambda.*` platform error at all. So all three are retried, and the reading is owed in
`docs/testing/owed.md`, which also records which retrier answered. If the error turns out to be
`Lambda.ServiceException` or `Lambda.AWSLambdaException`, the existing 14 s retrier answers it
first and is too short, and `Convert` answers it not at all; the fix then is a longer budget on
that retrier everywhere but `Convert`, and on `Convert` a decision, since a service error there
can follow a write.

**Why it is safe everywhere, `Convert` included.** All three are refusals at Invoke, before the
function runs. That is what the service errors are not: they can follow a completed run whose
response was lost, which is why `Convert` refuses them. A converter rejected as not ready has
written nothing, so retrying it cannot meet its own object.

**Why 75 s.** The retrier waits 5, 10, 20 and 40 s. **How long an invoke-triggered wake takes is
not measured on this fleet**, and AWS gives no duration. The one public account, the same third
party's, reports the function Pending for about 20 s while the image is re-pulled, and its own
user-facing text says about 30 s. The nearest thing measured here is an image update: from the
deploy log's "Image-packaged" line to Active took at most 20.3 s on 2026-11-02, with most of the
functions Inactive, and at most 20.4 s the next day with all of them Active. So being Inactive
added nothing measurable to an update, and an update says nothing about the rejected invoke's
wait. 75 s is two and a half times the slowest figure reported anywhere. The guard's floor is
50 s, above that figure with room to spare and below the deployed value so a retune has room; the
wake an invoke actually costs is owed in `docs/testing/owed.md` beside the error name.

**Why not longer.** A wake is charged once per function, as backoff with no timeout: a rejected
invoke never ran, and a function woken for its first attempt is awake for the rest. File-ops
charges every one of its twelve functions, and its worst case already stood about 1,100 s under its
3-hour ceiling, which cannot rise without lengthening the stale-lock window on a shared space. Twelve
wakes at 75 s fit; at the 195 s first proposed they did not. Table-builder's create path and
results-conversion's longest path charge the same wait. Each test reads it from the ASL, so a
longer budget is red there rather than quietly untrue. Archive's, file-send's and table-share's
budgets charge each verb's timeout once and no retries at all, against ceilings of three to
twelve hours, so the wait is left out of them as consistently as the retries are.

**Not a wider wake.** Waking the planes daily would mean invoking 81 handlers with
synthetic events, which are not no-ops in general, and cold-starting them against an account limit
of ten concurrent executions. `.github/lambda-probes.json` names one function per plane safe to
invoke with `{}`, but waking one function wakes only that one, and there are 81 to wake. A retry costs nothing, needs no
event, and covers every function a run reaches, the failure path included. A waiting retrier holds
no concurrency slot.

**What already retries a rejection, and is not changed.** The notifications and feedback writers
sit behind SQS event source mappings with a 60 s visibility timeout and three receives, so a
rejected delivery comes back up to twice more, a minute apart. The timed-out doors are EventBridge
targets with no retry policy set, so EventBridge's default of a day applies; whether a not-ready
rejection reaches that retry or Lambda's own asynchronous one is not documented, and either
retries for longer than any measured wake. Both are inferences from configuration, not
observations. The Pipes start executions directly and run no enrichment function. The scheduled
functions run at least daily and stay Active.

**Do NOT** fold these names into the service-error retrier: `Convert` must keep refusing the
service errors, and one list for both would retry them there. **Do NOT** put `States.ALL` or
`States.TaskFailed` in an earlier retrier on any Task: it would answer these errors first with its
own budget. The guard catches both.

## History

### 2026-11-03

- **Settled:** entered the register.
