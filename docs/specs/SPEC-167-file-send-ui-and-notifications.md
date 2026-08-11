# Spec: Send Files — "Send to…" UI & Notification Producer

**ID:** SPEC-167
**Status:** Completed
**Last Updated:** 2026-08-11
**Depends On:** SPEC-166 (terminal per-recipient summary), SPEC-147/148/158 (`UsernameChipsField`, `SuggestionSource`, `useSpaceSuggestions`), SPEC-093 (the Share-table dialog as the pattern), SPEC-058→061 (notifications), SPEC-155 (`FormDialog`, Escape depth, Enter-to-submit), SPEC-163 (the gated-surface registry)

## Overview

The last piece: a way to ask, and a way to find out. The file browser's selection toolbar gains
**Send to…** beside Copy, Move and Delete; the dialog names the recipients with the *same* typeahead
that Add members and Share table use — usernames from the directory, shared spaces from the user's
own connections cache. When the plane finishes, the sender hears every per-recipient outcome and the
recipient is told something arrived, with a link that lands them on the folder holding it.

Nothing here is new machinery. The recipient field is SPEC-147's combobox with SPEC-158's
prop-supplied source, the dialog is `FormDialog`, the enqueue is the FIFO helper, and the messages
go through the same notifications queue as every other plane. What is new is that a user can hand
someone a file.

## Scope

### In Scope

- `features/file-send/`: `enqueueFileSend`, `useFileSend`, `SendFilesDialog`, the request types.
- The **Send to…** entry point in the file browser's selection toolbar (labelled at ≥ tablet,
  icon-only on mobile, matching its neighbours), for one or many selected items.
- The dialog: a read-only summary of what is being sent, the Users / Shared spaces kind toggle, one
  combined removable chip list with kind badges, busy lock, inline submit error, axe-clean.
- The **notification producer**: sender per-recipient outcomes and whole-request failure; the
  recipient told on success, with a deep link to the receiving folder.
- Registration in SPEC-163's gated-surface registry.
- The Help & guides entry for the feature.

### Out of Scope

- A "sent items" history or an outbox. The notification is the record, exactly as for table share.
- Progress reporting, cancellation, or a resend control.
- Sending from anywhere but the file browser — no Query-rail or details-panel entry point in v1.
- Telling a space's whole membership. A space recipient is announced to its **owner only**, matching
  table share.
- Any new AWS grant. The browser's only privilege is the `sqs:SendMessage` SPEC-164 already granted.

---

## Functional Requirements

### FR-001: The entry point

#### Acceptance Criteria:

- [ ] The selection toolbar shows **Send to…** whenever one or more items are selected in a space the
      user can read, alongside Copy / Move / Delete; labelled at ≥ tablet, icon-only below.
- [ ] It is offered for files, folders and mixed selections.
- [ ] It is **not** offered in the dev-unauth path or in a read-only listing.
- [ ] The control is registered in SPEC-163's gated-surface registry under `files`, and its absence
      when that flag is off is covered by the registry test.

### FR-002: The dialog

#### Acceptance Criteria:

- [ ] Built on `FormDialog`; the body names what is being sent — item names and a count — read-only.
- [ ] A Users / Shared spaces toggle drives **one** `UsernameCombobox`, keyed on the kind so a note
      never outlives a toggle: usernames from `useUsernameSuggestions()`, spaces from
      `useSpaceSuggestions()` — the source is a **prop**, and this dialog calls neither hook from
      inside the field (SPEC-158).
- [ ] Committed recipients render as one combined removable chip list with kind badges; both kinds
      may be mixed in a single send.
- [ ] An unlisted name is **never blocked** — it is noted, and only when the source is `ready`. A
      space the sender is not a member of is a valid target, and the note under the space kind says
      so in the softer wording SPEC-158 established.
- [ ] Enter in the recipient field commits a chip and does **not** submit the dialog; only
      `submitOnEnterRef` submits (SPEC-155's measured rule — a dialog that submits from a
      mid-edit field files the wrong request).
- [ ] Escape closes the combobox list first and the dialog second, via the Escape depth registry; a
      busy dialog swallows Escape.
- [ ] Submitting with no recipients is refused inline, with no request sent.
- [ ] The dialog is axe-clean **in its open, driven state** — asserted against the driven container,
      not a re-render.

### FR-003: Enqueue

#### Acceptance Criteria:

- [ ] `enqueueFileSend` builds the SPEC-164 envelope from the current space, the selection and the
      chips, and FIFO-sends to `VITE_FILE_SEND_QUEUE_URL` with `MessageGroupId` = the SHA-256 digest
      of `{bucket}/{sourceRoot}` and `MessageDeduplicationId` = `requestId`.
- [ ] It returns `ServiceResult<void>` and never throws; a failure keeps the dialog open with an
      inline `Banner` and the recipients intact.
- [ ] Success closes the dialog, clears the selection, and raises a toast saying the send was
      **requested** — enqueued is not sent, and the wording must not claim otherwise.
- [ ] No raw AWS or SQS error text reaches the user; wording comes from `toUserMessage`.
- [ ] Double-submitting the same dialog state sends once. **AMENDED IN BUILD:** the guard is the
      in-flight ref plus the busy lock, NOT the queue's dedup id — the `requestId` is minted per
      SUBMIT because it is also what makes a retry possible. Reused across a failed attempt, the
      second send is swallowed by the queue and the user gets an error, presses the button again,
      and nothing happens. See the delivery doc.

### FR-004: Sender notifications

#### Acceptance Criteria:

- [ ] The sender receives one notification per recipient outcome: success names the recipient and the
      object count; `conflict` names the recipient **and the colliding item**; `copy_failed` and
      `unknown_user`/`unknown_space` each say what happened in plain words.
- [ ] A whole-request failure (bad source, caps exceeded, timeout, or the SPEC-152 pre-verb path)
      notifies the sender once, with a reason that never contains raw AWS text.
- [ ] Dedup tokens are one per **outcome**, not per verb — the rule SPEC-114 settled.
- [ ] Message text comes from `fscommon.messages` rendering whole sentences through the `cpcommon`
      `Resolver` (SPEC-156); no verb assembles a sentence from fragments.

### FR-005: Recipient notification and its link

#### Acceptance Criteria:

- [ ] On success a `user` recipient is notified directly; a `space` recipient's **owner** is
      notified, and no other member is.
- [ ] The message names the sender, the item names and the count.
- [ ] It carries a `link` to `/files?prefix=…` for a user recipient and
      `/files?space={space}&prefix=…` for a space recipient, where the prefix is the **full key
      including the recipient's space root** — `{recipientRoot}shared_files/{sender}/`, e.g.
      `bob/shared_files/alice/`. The route keeps `prefix` only when
      `prefixParam.startsWith(target.rootPrefix)`, so a root-relative `shared_files/{sender}/` is
      silently discarded and the recipient lands at their space root instead.
- [ ] The link is minted by the **Python producer** through a shared builder mirroring
      `dqcommon.notify.report_link`, and its safety rule is reproduced there — `isSafeInAppPath` is
      browser TypeScript and cannot run at mint time. The browser's render-time validation stays as
      the second gate, unchanged.
- [ ] A test pins the built link against the route's own `startsWith` rule, so the two cannot drift.
- [ ] Following the link lands the recipient in the folder holding the received files.
- [ ] A recipient failure notifies the **sender only**; a recipient is never told about a send that
      did not reach them.
- [ ] Notifications are best-effort: a notify failure never fails the request (`sqs:SendMessage` on
      the notifications queue is the producer's only privilege).

### FR-006: Help & guides

#### Acceptance Criteria:

- [ ] A guide describes the shipped flow: select items → Send to… → pick users and/or spaces → what
      the recipient sees and where it lands (`shared_files/{sender}/`).
- [ ] It states plainly that a send is a **copy** (the sender keeps theirs), that it never
      overwrites, and that the recipient is not asked to accept.
- [ ] It documents only what is wired end to end (SPEC-074 FR-005), and is gated by the `files` flag
      through SPEC-163's registry.

---

## Data Model

```ts
// src/features/file-send/fileSend.types.ts

// AS SHIPPED (SPEC-164 named these; this spec consumes them unchanged).
export type SendRecipient = {kind: 'user' | 'space'; name: string};

export type SendItem = {kind: 'file' | 'folder'; key: string};

export type SendSourceSpace = {kind: 'personal' | 'shared'; name: string};

export type FileSendRequest = {
  requestId: string;
  space: SendSourceSpace;
  items: SendItem[];
  recipients: SendRecipient[];
};
```

## API / Interface Contract

```ts
// AMENDED IN BUILD to what shipped. `enqueueFileSend` is SPEC-164's, and takes the requestId
// rather than minting one — the hook mints it PER SUBMIT (see FR-003 AC5).
enqueueFileSend(req: FileSendRequest): Promise<ServiceResult<void>>;

useFileSend(
  space: SendSourceSpace | null,
  notify: (toast: {variant: 'success'; message: string}) => void
): {
  items: SendItem[] | null;
  open: (items: SendItem[]) => void;
  close: () => void;
  // RETURNS whether it worked: the caller clears the selection from this, because `error` read
  // from the enclosing render is the value from BEFORE the submit — which cleared the selection
  // under a dialog whose retry then had nothing to send.
  submit: (recipients: SendRecipient[]) => Promise<boolean>;
  busy: boolean;
  error: string | null;
};
```

## File & Folder Structure

```
apps/portal/src/features/file-send/
├── SendFilesDialog.tsx
├── SendFilesDialog.test.tsx
├── useFileSend.ts
├── useFileSend.test.ts
├── fileSend.service.ts
├── fileSend.service.test.ts
├── fileSend.types.ts
└── index.ts
lambdas/file-send-notify/          # the producer verb
```

## Implementation Phases

### Phase 1: Service + hook

- `enqueueFileSend` on the shared FIFO helper, `useFileSend`, and their tests (mocking only the AWS
  boundary).

### Phase 2: Dialog + entry point

- `SendFilesDialog` over `FormDialog` with the shared combobox; the toolbar control; the registry
  row; axe on the driven container.

### Phase 3: Notification producer

- The verb, `fscommon.messages`, the sender and recipient paths, the Python link builder (full-key
  prefix, `report_link`'s safety rule reproduced), wired into the SPEC-166 terminals.

### Phase 4: Verification

- A journey test that performs the send end to end in the browser layer (SPEC-154's discipline: test
  the wires, not the halves).
- **Live check (owed), Safari:** sign in, select a folder and a file, send to one user and one shared
  space at 400px and desktop. Confirm suggestions appear under **both** kinds, several chips still
  leave the confirm control reachable, the sender gets one notification per recipient, the recipient
  gets one with a working link, and the files are at `shared_files/{sender}/…`. Then repeat the same
  send and confirm the `conflict` notification names the item.

### Phase 5: Completion ritual

- Delivery doc, INDEX status, component-inventory rows in a new `file-send-feature.md` area file plus
  a router row, one Key Decisions line (push semantics, owner-only space announcement, the
  `shared_files/{sender}/` inbox), and the **Help & guides** entry FR-006 requires.
