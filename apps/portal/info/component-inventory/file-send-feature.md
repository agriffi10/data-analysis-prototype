# File-send feature (`apps/portal/src/features/file-send/`)

Part of the component inventory (`INDEX.md`, beside this file, is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.

SPEC-164 shipped the enqueue surface; SPEC-167 added the "Send to…" control, its dialog and the
hook. The outcome notifications are produced in Python (`lambdas/file-send-notify/`) and are not
part of this surface.

| Symbol | File | Purpose |
|---|---|---|
| `enqueueFileSend(req)` | `fileSend.service.ts` | The browser's only file-send call: builds the SPEC-164 envelope (`requestId` + `actor` **raw ID token, top level** + `source.{space,items}` + `recipients[]`) and FIFO-sends to `VITE_FILE_SEND_QUEUE_URL` via `getSqsClient`. `MessageGroupId` = SHA-256 of `"{bucket}/{space}/"` (a hash: SQS caps the group id at 128 chars, an S3 key reaches 1024); `MessageDeduplicationId` = the caller's `requestId`. **It is NOT the double-submit guard** (SPEC-167 amended FR-003 AC5): the id is minted per SUBMIT, because reusing it across a failed attempt makes the queue swallow the retry — `useFileSend`'s in-flight ref and busy lock are the guard. Refuses over-cap selections locally (200 items / 96 KiB serialised, mirroring `fscommon.config`) with code `SelectionTooLarge`, because a request too large for `StartExecution` never reaches the verb that would refuse it. `ServiceResult<void>` (enqueued ≠ sent), never throws (SPEC-164). |
| `SendFilesDialog({items, busy?, submitError?, onSubmit, onCancel})` | `SendFilesDialog.tsx` | The "Send to…" modal (SPEC-167): a read-only summary of the selection **by item name** (what the recipient will see, not the sender's key), a Users / Shared spaces toggle driving ONE `UsernameCombobox` whose `SuggestionSource` is a **prop**, and a combined removable chip list with kind badges. Neither kind blocks an unlisted name. The Send control stays ENABLED with no recipients so the refusal is inline rather than a dead button; the entry CLEARS with the kind toggle. With `sharedWorkspaces` off the toggle does not render at all. |
| `useFileSend(space, notify)` | `useFileSend.ts` | Dialog + enqueue state. `open(items)` / `close()` / `submit(recipients)` → **`Promise<boolean>`**: the caller clears the selection from the RETURN VALUE, because `error` read from the enclosing closure is the value from before the submit. Mints the `requestId` **per submit** (it is the FIFO dedup id, so reusing it makes a retry a silent no-op). Never wedges: `busy` clears in `finally` and a throw becomes a user-safe error. Refuses to close while busy; ignores a second submit via a ref, not `busy` (SPEC-167). |
| `FileSendRequest`, `SendItem`, `SendRecipient`, `SendSourceSpace` | `fileSend.types.ts` | The send-request shapes matching the SPEC-164 contract. `SendItem.key` is the full S3 key as the browser lists it; a folder may be sent with or without its trailing slash (the verb normalises it) (SPEC-164). |
