---
type: Decision
title: "Only three outcomes needed a producer, and one of them had to be invented"
description: "Only `archived`, `restored` and `restore_started` come from the outcome producer, the other six from existing failure paths; the ASL seeds which, `restore_started` fires after `RetrieveObjects`, and the producer can never fail the run."
---

FR-006 names nine terminal outcomes. Six were already reason codes in `arcommon.messages`, emitted
exactly once by `notifies_on_failure` or by the machine's `NotifyFailure` — a second producer for
them would be the duplicate SPEC-114's one-token-per-OUTCOME rule exists to prevent. What was
missing was what a failure table cannot carry: `archived`, `restored`, and `restore_started`.

**`restore_started` is the only "started" notification in this application**, and the reason is
specific to this plane rather than a general improvement: every other control plane finishes in
seconds or minutes, so silence until the outcome is honest there. Here it is three to five *billed*
hours, during which silence is indistinguishable from a request that was dropped. It is emitted
**after** `RetrieveObjects`, not before — that Map is where the bill and the wait actually begin, so
announcing earlier would promise a wait that a failed retrieval never starts.

**The producer cannot fail the run, and the ASL enforces it.** On the archive arm the source is
already deleted when it speaks; a raise would turn a completed archive into a reported failure with
the data gone. All three states carry `ResultPath: null` (two sit mid-machine, ahead of a wait, a
poll loop, a second guard and a copy) and a `States.ALL` Catch whose `Next` is the state they were
inserted in front of. The verb carries `@traced` and no `@notifies_on_failure` — that decorator
would report a failure of the NOTIFIER as a failure of the archive.

**The ASL seeds which outcome it is.** All three call sites carry identical keys, so nothing on the
state distinguishes them and inferring would mean guessing — SPEC-171 settled its two destination
guards the same way, for the same reason.

**The restored link is the SPACE ROOT.** A restore puts every object back where it came from, which
for any selection of more than one folder is several places at once; picking the first would send
the user to a folder holding part of what they asked for. The archived link is the receipt's own
folder, and both carry the recipient's full key including the space root — SPEC-167's finding, that
a root-relative prefix is silently discarded by the route and lands the user at their space root
looking like a link that worked.

## History

### 2026-08-12

- **Settled:** entered the register.
