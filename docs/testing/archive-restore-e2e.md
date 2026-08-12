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

---

## SPEC-171 — the retrieval, the wait and the copy-back

**This is the only step in this file that cannot be compressed.** A `Standard` retrieval takes
**3–5 hours** and is **billed and uncancellable** the moment it starts, so plan on starting step 1
and coming back the same day. Nothing in CI exercises a real Glacier retrieval — the tier's latency,
the `Restore` header's exact format and the `InvalidObjectState` boundary are only observable here.

Run SPEC-170's steps first. They are free, they take minutes, and step 2 of that section is the one
that proves this section will not charge you for a restore that cannot land.

### 0. The policy simulation, post-apply (FR-007 AC4)

Run this **after `Deploy Infrastructure` is green on main**, not before. The pre-apply baseline is
recorded below it for comparison — every new grant read `implicitDeny` then.

```bash
ROLE=arn:aws:iam::696000197480:role/dat-prod-archive-execution-role
run() { printf '%-28s %-64s ' "$1" "$2"; aws iam simulate-principal-policy --policy-source-arn "$ROLE" --action-names "$1" --resource-arns "$2" --query 'EvaluationResults[0].EvalDecision' --output text; }
run s3:RestoreObject "arn:aws:s3:::dat-prod-archive/personal/alice/archive/x/q1.csv"
run s3:PutObject     "arn:aws:s3:::dat-prod-user-space/alice/reports/q1.csv"
run s3:PutObject     "arn:aws:s3:::dat-prod-shared-space/team-x/reports/q1.csv"
run s3:GetObject     "arn:aws:s3:::dat-prod-archive/personal/alice/archive/x/q1.csv"
run s3:PutObject     "arn:aws:s3:::dat-prod-user-space/alice/user_settings/notifications.json"
run s3:DeleteObject  "arn:aws:s3:::dat-prod-user-space/alice/athenaresults/q.csv"
```

| Action / resource | Pre-apply (recorded 2026-08-12) | Expected post-apply |
|---|---|---|
| `RestoreObject` on the vault | `implicitDeny` | **`allowed`** |
| `PutObject` anywhere in user space | `implicitDeny` | **`allowed`** |
| `PutObject` anywhere in shared space | `implicitDeny` | **`allowed`** |
| `GetObject` on the vault (**control**) | `allowed` | `allowed` |
| `PutObject` under `user_settings/` | `implicitDeny` | **`explicitDeny`** |
| `DeleteObject` under `athenaresults/` (**control**) | `explicitDeny` | `explicitDeny` |

**Every denial is paired with an `allowed` control on the same bucket on purpose.** An
`implicitDeny` alone cannot tell an ungranted action from a wrong resource ARN — SPEC-149's trap,
where `dat-prod-athena-admin` mistyped read as a pass. The `user_settings/` row is the one that
must **change class**, from implicit to explicit: that is the new Deny working rather than the old
absence of a grant.

### 1. The restore that works (FR-001, FR-002, FR-003, FR-005, FR-006)

Restore the archive SPEC-169's step 2 created, having cleared whatever SPEC-170's step 2 put in the
way. Note the **archive id** and the **start time**.

**Immediately (within a minute), before you walk away:**

- Download `{space}/archive/{ARCHIVE_ID}/receipt.txt` from the file browser. `Restore requested`
  must already carry a timestamp and `Restored to` must still read `-`. **That is FR-006 AC4** — the
  marker is written before the bill, so if it is absent here it never runs before the money is spent.
- `logs/service=archive/` must carry `build-restore-manifest` and a `batch retrieval requested`
  event per Map child.

**Then wait.** Check back after ~1 h, ~3 h and ~5 h.

- **The loop must actually loop.** `logs/service=archive/` carries multiple `retrieval polled`
  events, **hours apart**, with `poll_count` climbing and `complete: false`. One poll and done means
  the `Wait` is not doing what it says.
- While it is running, confirm the retrieval is real rather than inferred:

  ```bash
  aws s3api head-object --bucket dat-prod-archive \
    --key "personal/$USERNAME/archive/$ARCHIVE_ID/reports/q1.csv"
  ```

  Expect `Restore: ongoing-request="true"` while it works, and `ongoing-request="false", expiry-date=…`
  once it finishes. **`StorageClass` stays `GLACIER` throughout** — that is the whole reason the poll
  reads the header and not the class, and seeing it not move is the confirmation.

**When it completes:**

- Every file is back in the space at its original path, **including any empty folder** the archive
  carried (FR-003 AC6).
- **By `head-object`, never by inference** (FR-003 AC2):

  ```bash
  aws s3api head-object --bucket dat-prod-user-space --key "$USERNAME/reports/q1.csv"
  ```

  Expect **no `StorageClass` field at all** (which is `STANDARD`) and **no `Restore` header**. A
  restored object still reading `GLACIER` is the silent failure this AC exists for: it looks
  identical in the browser and becomes unreadable again in seven days.
- **Content type survived** (FR-003 AC5). Use a fixture with a non-default type — upload a `.csv` and
  confirm `ContentType: text/csv` on the same `head-object`. If you can stage a **>5 GiB** object,
  do; that is the path the metadata fix was for and the only one a unit test cannot fully stand in
  for.
- **Byte-identical.** Download one file and `shasum` it against what you archived.
- **The archive prefix is gone** (FR-005):

  ```bash
  aws s3api list-objects-v2 --bucket dat-prod-archive \
    --prefix "personal/$USERNAME/archive/$ARCHIVE_ID/" --max-keys 5
  ```

  Expect `KeyCount: 0` — `_manifest.json` included.
- **The receipt survived the archive's deletion** and now reads both fields: `Restore requested` with
  the timestamp from step 1, `Restored to` with `s3://dat-prod-user-space/{username}/`. **Its
  `Requested`, `Request ID`, `Total size` and `Files archived` lines must be exactly what they were
  before the restore** — that is the rewrite-not-re-render rule, and a blanked `Requested` line is
  how you would know it broke.

### 2. Shared space (Phase 4's second half)

Repeat step 1 against the shared archive SPEC-169's step 2 produced. The destinations rebuild under
the **space** root, the receipt is in the shared bucket, and `SpaceDataWrite`'s shared-bucket arm is
what makes the copy land at all.

### What is NOT worth staging

- **The partial restore (FR-004).** Forcing one item to fail mid-copy means denying a single
  destination key, which the guard would have refused up front. The branch is asserted from the ASL
  graph and driven from a fixtured `ResultWriter` export; **`restore_incomplete` reaches a user only
  in SPEC-172**, which is where its wording should be read back.
- **The timeout (`restore_timed_out`).** Seven hours of waiting to observe a counter.
- **A never-requested object.** It needs an archive whose retrieval was deliberately half-issued,
  which no reachable path produces.
