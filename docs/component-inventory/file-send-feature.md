# File-send feature (`apps/portal/src/features/file-send/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.

**No UI yet.** SPEC-164 shipped the enqueue surface only; the "Send to…" control, its dialog and
the notifications land in SPEC-167.

| Symbol | File | Purpose |
|---|---|---|
| `enqueueFileSend(req)` | `fileSend.service.ts` | The browser's only file-send call: builds the SPEC-164 envelope (`requestId` + `actor` **raw ID token, top level** + `source.{space,items}` + `recipients[]`) and FIFO-sends to `VITE_FILE_SEND_QUEUE_URL` via `getSqsClient`. `MessageGroupId` = SHA-256 of `"{bucket}/{space}/"` (a hash: SQS caps the group id at 128 chars, an S3 key reaches 1024); `MessageDeduplicationId` = the caller's `requestId`, which is the ONLY double-submit guard because the queue has content dedup off — so mint it per submit, not per dialog. Refuses over-cap selections locally (200 items / 96 KiB serialised, mirroring `fscommon.config`) with code `SelectionTooLarge`, because a request too large for `StartExecution` never reaches the verb that would refuse it. `ServiceResult<void>` (enqueued ≠ sent), never throws (SPEC-164). |
| `FileSendRequest`, `SendItem`, `SendRecipient`, `SendSourceSpace` | `fileSend.types.ts` | The send-request shapes matching the SPEC-164 contract. `SendItem.key` is the full S3 key as the browser lists it; a folder may be sent with or without its trailing slash (the verb normalises it) (SPEC-164). |
