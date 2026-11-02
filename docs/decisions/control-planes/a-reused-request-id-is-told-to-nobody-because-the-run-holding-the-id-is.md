---
type: Decision
title: "A reused request id is told to nobody, because the run holding the id is the one that reports (data quality, file operations, archive)"
description: "`request_id_reused` sends no notice on data quality, file operations or archive, because the run holding the id reports; `SILENT_REASONS` and `is_silent` live in `cpcommon`, and a `Resolver` refuses a domain that words a silent reason."
---

**All three planes that refuse `request_id_reused` refuse it silently.** Each decides that an id is
held its own way — data quality by a claim naming another execution, file operations by a plan naming
another execution ARN, archive by an archive prefix that already holds objects **or by another
execution holding its create-only claim** — and in each the id
belongs to a run that reports under it: data quality's report notice, file operations'
`{requestId}:outcomes` row, archive's `archived` row — only an archive raises it, since a restore's
own id may not be its archive's. A notice from the refused run could
only contradict that run. On file operations it said *"that looks like a repeat of a request already in
flight. Nothing was changed"* and carried `{requestId}` with no `operation`, so landing ahead of the
first run's outcome row it could settle the browser's in-flight card as *Refused* — a card settles
once — for an operation that then finished. That was read from the code, not observed. On archive it said nothing was
archived, beside *"Archived N files"*. Neither dropped the first run's notice — its success rows carry
explicit dedup ids and the failure text differed — so this was wording, not a lost message.

**Decided 2026-09-16 (Andrew): silent on file operations and archive, as on data quality.** Rewording
the notice to say a duplicate was ignored was the alternative, and it would still land a row carrying
the card's id. Who actually sends a reuse is argued in [the data-quality entry](a-data-quality-request-id-is-claimed-by-one-execution-before-anything.md): the browser
mints an id per submit, and reusing an execution name was measured to return the running execution
rather than start another, while that a redelivery reuses its name is only inferred. So the likely
sender is a hand-built request, which is now told nothing and finds its refusal on the execution.

**The mechanism is one vocabulary and one predicate, both in the shared layer.**
`cpcommon.messages.SILENT_REASONS` holds the code and registers it at import, and
`cpcommon.notify.is_silent` is what each plane's `emit_failure` reads before it sends.

- **The shared layer registers the code, not each plane.** The suite imports every domain into one
  process, so a plane that forgot to register a code another plane registers passes locally and raises
  `ValueError` in its deployed function, where the error is no longer a `TerminalError` and the user is
  told that something went wrong — twice on file operations and archive, whose two generic sentences
  differ, and once on data quality, whose two share a dedup id. Data quality's first version registered its own copy. A test
  in a fresh interpreter holding only `cpcommon` holds the new home.
- **A `Resolver` refuses a domain that words a silent reason.** File operations and archive each
  carried a body for it, now deleted, and a sentence nobody is told reads to the next person in the
  table as what the user sees.

**The other half of the silence is `notify-failure`, and it differs by plane.** File operations' and
archive's drop every `TerminalError` as already handled, so what keeps a silenced reason silent there
is that name check; they read `is_silent` only to log the suppression as a silent refusal rather than
a duplicate of a notice nobody sent. Data quality's decides on `is_silent` itself. A test on each of
the first two pins that half, because narrowing their name check would send the fallback *"something
went wrong"* while every verb test stayed green.

**A plane that adds the refusal gets the registration for free and the silence only by asking** — file
send is due one. A fleet test derives the planes from where a silent code is named in their source,
and holds each one's `emit_failure` to sending nothing for it, so a plane that starts raising the code
without asking is red before it deploys.

**Rejected.** *A copy of `SILENT_REASONS` and `is_silent` in each domain*, data quality's first shape:
three copies of one policy, each carrying the registration trap. *The check in `notifies_on_failure`
alone*: the validators call `emit_failure` directly, and would tell what the decorator keeps quiet.

## History

### 2026-09-16

- **Settled:** entered the register.
