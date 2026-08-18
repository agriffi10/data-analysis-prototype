# Completed Spec — SPEC-167: Send Files — "Send to…" UI & Notification Producer

## What was completed?

A user can hand someone a file. The arc's last piece is a way to ask and a way to find out: a
**Send to…** control on the file browser's selection toolbar, a dialog that names recipients with
the same typeahead Add members and Share table use, and one Python producer that tells the sender
every outcome and the recipient that something arrived, with a link that lands them on it.

- **`lambdas/file-send-notify/`** — the plane's only outcome producer, and `NotifyOutcomes`
  between `ShapeSummary` and `Succeeded`.
- **`fscommon.notify.received_files_link`** — the in-app path, mirroring `dqcommon`'s
  `report_link`; **`fscommon.messages`** — the success, recipient and space-owner wording;
  **`fscommon.paths.inbox_label`** — `shared_files/{sender}/` as a person reads it.
- **`features/file-send/`** — `SendFilesDialog`, `useFileSend` (the service shipped in SPEC-164).
- **`SelectionToolbar`** — **Send to…** beside Copy / Move / Delete.
- **Five `GATED_SURFACES` rows** and a **Help guide**.
- **Three PRs**: the producer (#428), the browser (#429), then completion (#430).

## One producer, and why nothing upstream emits

Table share notifies from its guard, its collector and its create verb, because each is the only
place its outcome is known. Here every per-recipient outcome reaches one flat list — SPEC-166's
terminal summary — before anything is said, so one producer can say each thing once. That is why
the guard and the collector on this plane deliberately emit nothing, and why the guard returns its
expected refusals as records: the colliding item name has to survive to the producer, and a
`TerminalError` cannot carry one to a user.

The whole-**request** verbs still carry `@notifies_on_failure` and must: a request that dies in
validate-authorize never reaches this state, and the machine's `NotifyFailure` suppresses a
terminal error precisely because it assumes the decorator spoke.

**A failed recipient is the sender's business alone.** Someone who was never reached is not told
that a send was attempted — they have no part in it, nothing to do about it, and being told would
leak that the sender tried.

## The link is the part that drifts silently

The prefix is the **full key including the recipient's own space root**. `FilesPage` keeps a
`?prefix=` only when it starts with the resolved space's `rootPrefix`, so a root-relative
`shared_files/{sender}/` is discarded and the recipient lands at their space root — a link that
looks like it worked. A `space` recipient needs `?space=` as well, or the browser resolves the
personal space and drops the prefix for the same reason.

Two tests hold the two languages together: one reads the route's `startsWith` gate **and**
`rootPrefix`'s own definition out of `useFileSpace.ts`, the other reads `isSafeInAppPath`'s accept
rule. The first version pinned only the route's gate and compared against a hardcoded value, which
would have stayed green through exactly the rename it existed to catch.

**The link is feature-gated too**, and that was a review finding rather than a design: with
`files` off it was a live anchor into the unavailable page, and with `sharedWorkspaces` off the
space-owner link silently resolved the personal space and dropped the prefix — the failure FR-005
exists to prevent, reachable from flag state alone. `NotificationRow`'s single hard-coded
prefix test is now a map of flag→match, with registry rows for both. (One arm is a substring test
on `?space=`, not a prefix: the space variant differs from the user one in its query, not its
path.)

## What the reviews caught that the tests did not

Every one of these was live, and none was visible to the suite as written:

- **The inline "no recipients" refusal was unreachable.** `submitDisabled` meant `FormDialog`'s
  guard returned before the handler ran, so the banner could never render — dead code where
  FR-002 AC7 was supposed to be. The test asserted only that the button was disabled and passed
  straight over it. The control now stays enabled and the refusal is real, which is also the
  better answer: a disabled button explains nothing to the user who typed a name and forgot to
  commit it.
- **A throw during submit wedged the dialog permanently** — `busy` stayed true, so the submit read
  "Sending…", Cancel was disabled, the modal refused to dismiss and swallowed Escape, and `close()`
  refused because it was busy. Reachable outside a secure context, where `crypto.randomUUID` and
  the service's SHA-256 digest are both undefined, which is the documented dev-preview shape.
- **A failed send cleared the selection under its own dialog.** The handler read `send.error` from
  the enclosing closure — the value from *before* the submit — so the retry had nothing to send.
  `submit` now returns whether it worked. Only the end-to-end journey test sees this; the dialog
  and the hook are each correct in isolation.
- **The busy-lock test was vacuous**: it mounted a second, empty dialog whose submit was disabled
  for having no recipients, so it passed against an implementation where `busy` locked nothing.

## Deliberate deviations

- **FR-003 AC5 is not delivered as written, and this is the one worth reading.** The AC says a
  double submit is "a no-op at the queue (the explicit dedup id)". The `requestId` is minted **per
  submit** instead, so the queue guard is gone and the real guard is an in-flight ref plus the busy
  lock. The reason is that the id is also what makes a RETRY possible: reused across a failed
  attempt, the second send is silently swallowed by the queue and the user gets an error, presses
  the button again, and nothing at all happens. The trade is a first send that reached SQS but
  whose response was lost being retried as a new request — which the conflict guard then refuses
  per recipient, telling the sender. The spec's AC text is amended to match.
- **The success toast says the send was REQUESTED** (FR-003 AC3), not that it was sent. The plane
  copies in the background and every outcome arrives as a notification; "sent" would be a lie for
  the minutes a large send takes and simply wrong for one that conflicts.
- **The dialog shows item names and a count, not the object count.** The browser does not know how
  many objects a folder holds; the expansion is inspect-source's. The notification carries the
  real number.
- **No "sent items" history, no progress, no cancellation** — Out of Scope, unchanged.
- **A send to a space you own gets two messages** (the sender's outcome and the owner's arrival).
  Table share does the same; deduplicating would mean the producer knowing the sender owns the
  space, which is a registry read per outcome for a cosmetic gain.

## What changed from earlier specs?

- **`NotificationRow`** gates a MAP of link prefixes rather than one hard-coded `/data-quality`.
- **`SelectionToolbar`** takes an optional `onRequestSend`.
- **Five registry rows**: the toolbar control, the guide, the two notification links, and the
  dialog's own `Shared spaces` toggle — a SECOND instance of a surface whose only existing row
  renders the share dialog, so nothing would have noticed if this one stopped being gated.

## Live check (owed)

`docs/testing/e2e.md`, *SPEC-167* — the Safari pass. It is the only thing that exercises
the browser half against the real plane, and the notification link is the half that cannot be
checked offline: the producer mints it in Python and a route rule in TypeScript honours it.
