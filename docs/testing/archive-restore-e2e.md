# Archive & restore — live checks

The archive arc's owed live checks, as a script. Everything here needs real AWS and cannot be
proved offline.

**Read the identity note first.** A laptop IAM user cannot read or write `dat-prod-user-space` at
all — the bucket policy allowlists the portal, deploy and execution roles — so **every step touching
a user's space needs an assumed role or the portal UI**. The archive bucket is stricter still: only
this plane's execution role can reach it, and the deploy role, so `aws s3 ls` on it from a laptop
identity fails and that is the isolation working.

**There is no UI yet.** SPEC-172 builds it. Until then every request is a hand-crafted message onto
the FIFO queue, which is also the only thing that proves the layer attaches at cold start.

## Fixtures

| Name | Value |
|---|---|
| Queue | `dat-prod-archive-requests.fifo` |
| Archive bucket | `dat-prod-archive` |
| User-space bucket | `dat-prod-user-space` |
| Admin bucket | `dat-prod-athena-admin` |
| Logs | `s3://dat-prod-athena-admin/logs/service=archive/year=…/month=…/day=…/data.jsonl` |

Two UUIDs per run, and **they must be different values** — the plane refuses a restore whose
`requestId` equals its `archiveId`:

```bash
python3 -c "import uuid; print('requestId', uuid.uuid4()); print('archiveId ', uuid.uuid4())"
```

An ID token, from the browser's dev tools after signing in (Application → Local Storage → the
`...idToken` key), or from a Cognito auth call. It is the `actor` field, **flat and raw** — never
`{"idToken": …}`, which the front door refuses.

---

## SPEC-168 — the front door

See `docs/spec-delivery/SPEC-168-archive-foundation-and-validate-authorize.md`. One valid and one
unauthorized hand-crafted request through the queue, then a `PutObject` into your own `archive/`
prefix refused, personal and shared.

## SPEC-169 — the transfer, the gate and the deletion

See `docs/spec-delivery/SPEC-169-archive-transfer-and-source-deletion.md`. Four steps; the third —
a Deny on ONE key, confirming the source survives — is what the whole spec exists for.

**Keep the `archiveId` (= that run's `requestId`) and the folder you archived.** SPEC-170's checks
below restore exactly that archive.

---

## SPEC-170 — the lookup and the destination guard

Runs on the archive SPEC-169 just produced. **Do the two in one session, 169 first.**

Every request below is the same shape; only `requestId` and the space change:

```bash
aws sqs send-message \
  --queue-url "$(aws sqs get-queue-url --queue-name dat-prod-archive-requests.fifo --query QueueUrl --output text)" \
  --message-group-id "$(printf 'dat-prod-archive/personal/%s/archive/%s/' "$USERNAME" "$ARCHIVE_ID" | shasum -a 256 | cut -d' ' -f1)" \
  --message-deduplication-id "$REQUEST_ID" \
  --message-body "$(jq -nc --arg r "$REQUEST_ID" --arg t "$ID_TOKEN" --arg u "$USERNAME" --arg a "$ARCHIVE_ID" \
      '{requestId:$r, mode:"restore", actor:$t, space:{kind:"personal", name:$u}, archiveId:$a}')"
```

The `MessageGroupId` above is the contract **SPEC-172 owes** (SHA-256 of
`{archiveBucket}/{archiveRoot}`); nothing enforces it yet, so type it correctly here and the check
also exercises the rule the browser will have to reproduce.

### 1. The clear path

Submit the request as above, against the archive SPEC-169 produced, with its source folder **still
absent** from your space (it was deleted by the archive).

Expect:

- The execution **SUCCEEDS**, ending at `RestoreReady`.
- Its output names `objectCount` and `totalBytes` **equal to the receipt's**
  (`{you}/archive/{archiveId}/receipt.txt`).
- `s3://dat-prod-athena-admin/archive/{requestId}/restore-plan.json` exists, and every entry's
  `destKey` is the original path — check two by eye against the folder you archived.
- `logs/service=archive/` carries `restore plan built` and `destinations clear` for this
  `request_id`, with `manifest_present: true`.
- **No notification** — this spec emits none on success (SPEC-172 owns that).

### 2. The refusal, and the assertion that matters

Put **one** of the archived files back at its original path — upload it through the portal, at the
exact key the receipt implies. Then submit a **new** restore with a **new `requestId`** and the same
`archiveId`.

Expect:

- The execution **FAILS**.
- The notification in your inbox starts **"Couldn't restore that:"** — not "Couldn't archive
  that" — **names that file's path relative to your space root** (`reports/q1.csv`, not
  `alice/reports/q1.csv` and not an `s3://` URI), and says **there may be more**.
- **THE ASSERTION THIS STEP EXISTS FOR — a negative one.** `head-object` an archived object and
  confirm there is **no `Restore` header** on it:

  ```bash
  aws s3api head-object --bucket dat-prod-archive \
    --key "personal/$USERNAME/archive/$ARCHIVE_ID/<some/archived/key>"
  ```

  A refusal that had already initiated retrieval looks **identical** from the UI, and costs the user
  3–5 hours and a real bill. `StorageClass: GLACIER` and no `Restore` key is the pass.

### 3. Not found, and not an oracle

Submit a restore naming an `archiveId` that does not exist (a fresh UUID), then one naming the
**real** archive id but a shared space you are a member of.

Expect **the same refusal both times**: `archive_not_found`, wording that names the id and the space
and points at the `archive/` folder. The second case must not hint that the archive exists
elsewhere.

### 4. The pasted id

Submit with `archiveId` set to each of: a value with a trailing space, one containing `/`, and the
id in **UPPER CASE**.

Expect: the first two refused as malformed **before any bucket is touched** (no listing in
`logs/service=archive/` for that request), and the third to behave exactly as step 1 or 2 did — the
id is lowercased, so a receipt retyped in caps still resolves.

### 5. Shared space

Repeat step 1 against a shared space you are an active member of, using the shared archive SPEC-169
step 2 produced. The archive prefix must carry `shared/`, and the destinations must rebuild under
the space root rather than your own.
