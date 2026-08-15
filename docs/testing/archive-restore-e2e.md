# Archive & restore — live checks

The archive arc's owed live checks, as a script. Everything here needs real AWS and cannot be
proved offline.

**Read the identity note first.** A laptop IAM user cannot read or write `dat-prod-user-space` at
all — the bucket policy allowlists the portal, deploy and execution roles — so **every step touching
a user's space needs an assumed role or the portal UI**. The archive bucket is stricter still: only
this plane's execution role can reach it, and the deploy role, so `aws s3 ls` on it from a laptop
identity fails and that is the isolation working.

**SPEC-172 has now built the UI**, so every check below can be driven from the file browser instead
— and the SPEC-172 section at the foot of this file is the pass that does exactly that. The
hand-crafted form is kept because it is still the only way to stage a malformed request. Every
request is otherwise a hand-crafted message onto
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
  --message-group-id "$(printf 'personal/%s/archive/%s/' "$USERNAME" "$ARCHIVE_ID" | shasum -a 256 | cut -d' ' -f1)" \
  --message-deduplication-id "$REQUEST_ID" \
  --message-body "$(jq -nc --arg r "$REQUEST_ID" --arg t "$ID_TOKEN" --arg u "$USERNAME" --arg a "$ARCHIVE_ID" \
      '{requestId:$r, mode:"restore", actor:$t, space:{kind:"personal", name:$u}, archiveId:$a}')"
```

The `MessageGroupId` above is the contract **SPEC-172 has now shipped**, and it is the digest of
the **archive root alone** — `personal/{username}/archive/{archiveId}/` — not of
`{archiveBucket}/{archiveRoot}` as SPEC-170 FR-001 first wrote it. The browser deliberately does not
know the archive bucket's name (a test enforces that absence), and the root's own
`personal/`/`shared/` segment already makes it unique, which is the only property a group id needs.
Type it exactly as below and the hand-crafted check exercises the same rule the browser reproduces:

```bash
--message-group-id "$(printf 'personal/%s/archive/%s/' "$USERNAME" "$ARCHIVE_ID" | shasum -a 256 | cut -d' ' -f1)"
```

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
- **THE ASSERTION THIS STEP EXISTS FOR — a negative one, and it is read from the AUDIT RECORD.**

  > **Read this before running it.** `head-object` on `dat-prod-archive` was the original
  > instruction and **no principal can make that call** (measured 2026-08-14): the bucket policy
  > allowlists the execution and deploy roles only, the execution role trusts
  > `lambda.amazonaws.com`, and the deploy role is GitHub-OIDC-only. **Do not proxy it from the
  > UI** — a refusal that had already initiated retrieval looks *identical* there, and being
  > wrong costs the user 3–5 billed, uncancellable hours. SPEC-186 FR-004 added the record this
  > step now reads instead.

  **First, prove the trail is logging.** A trail that is off returns an empty result, which reads
  exactly like a `RestoreObject` that never happened — the mirror of SPEC-138's "did not run is
  never clean", and here the absence *is* the evidence:

  ```bash
  aws cloudtrail get-trail-status --name dat-prod-archive-audit --query 'IsLogging'
  ```

  Expect `true`. If it is `false`, this assertion cannot be made and nothing below counts.

  **Then read the record.** Data events are delivered in batches, so **wait ~10 minutes** after
  the refusal before concluding anything.

  > The read-only verification role (`dat-prod-verification`, SPEC-186 FR-004) exists only once
  > `verification_principal_arns` names a principal — it is empty by default, because those are
  > operator identities and do not belong in the repo. It is set as the
  > `TF_VAR_verification_principal_arns` **repo variable** and applied by CI, **never by a local
  > `tofu apply`**: no human identity here can apply locally without tofu proposing to destroy
  > and recreate the data buckets it cannot read (see `table-builder-e2e.md` for the measured
  > plan). The trail itself ships regardless, so if you have ordinary read access to
  > `s3://dat-prod-archive-audit/` you can run the query below **without the role at all** —
  > which is the path this check should normally take.

  Sweep the trail objects for this archive id:

  ```bash
  aws s3 ls "s3://dat-prod-archive-audit/AWSLogs/" --recursive \
    | awk '{print $4}' | while read -r key; do
        aws s3 cp "s3://dat-prod-archive-audit/$key" - | gunzip
      done \
    | jq -r --arg id "$ARCHIVE_ID" '
        .Records[]
        | select(.eventName == "RestoreObject")
        | select(.requestParameters.key // "" | contains($id))
        | "\(.eventTime)  \(.requestParameters.key)"'
  ```

  **Expect NO OUTPUT.** The archive key layout is `{personal|shared}/{space}/{archiveId}/…`, so
  the id is in every key this run would have touched — a single `RestoreObject` against this
  archive prints a line, and the refusal has to happen before any of them.

  **A UI observation does not substitute for this**, and neither does a successful restore later:
  the question is whether retrieval was initiated *by the refused run*, and only the record
  answers it.

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

### 0. The policy simulation, post-apply (FR-007 AC4) — **DISCHARGED 2026-08-12**

Run after `Deploy Infrastructure` was green on main (run `31648992063`). **Every row below came
back as the table predicts**; kept here as the command to re-run if these grants are ever touched.

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

| Action / resource | Pre-apply | Post-apply (observed) |
|---|---|---|
| `RestoreObject` on the vault | `implicitDeny` | **`allowed`** ✅ |
| `PutObject` anywhere in user space | `implicitDeny` | **`allowed`** ✅ |
| `PutObject` anywhere in shared space | `implicitDeny` | **`allowed`** ✅ |
| `AbortMultipartUpload` in user space | — | **`allowed`** ✅ |
| `GetObject` on the vault (**control**) | `allowed` | `allowed` ✅ |
| `PutObject` under `archive/` — the receipt (**control**) | `allowed` | `allowed` ✅ |
| `DeleteObject` on the vault (**control**) | `allowed` | `allowed` ✅ |
| `PutObject` under `user_settings/` | `implicitDeny` | **`explicitDeny`** ✅ |
| `PutObject` under `athenaresults/` | `implicitDeny` | **`explicitDeny`** ✅ |
| `PutObject` on `_config/feature-flags.json` | `implicitDeny` | **`explicitDeny`** ✅ |
| `PutObject` on `_directory/usernames.json` | `implicitDeny` | **`explicitDeny`** ✅ |
| `DeleteObject` under `athenaresults/` (**control**) | `explicitDeny` | `explicitDeny` ✅ |
| `DeleteObject` on a `DO_NOT_DELETE.txt` (**control**) | `explicitDeny` | `explicitDeny` ✅ |

**Every denial is paired with an `allowed` control on the same bucket on purpose.** An
`implicitDeny` alone cannot tell an ungranted action from a wrong resource ARN — SPEC-149's trap,
where `dat-prod-athena-admin` mistyped read as a pass.

**The four rows that moved from `implicitDeny` to `explicitDeny` are the strongest evidence here,
and the reason is the widening itself.** Before the apply those keys were denied only because
nothing granted `PutObject` on them. After it, `SpaceDataWrite` grants `PutObject` on
`{bucket}/*` — which covers all four — so the ONLY thing refusing them now is
`NeverOverwritePortalManagedObjects`. A missing or mis-scoped Deny would read `allowed`, not
`implicitDeny`. That is what makes this pass a real check on the narrowing rather than a restatement
of the absence it replaced.

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
- While it is running, confirm the retrieval is real rather than inferred.

  > **This `head-object` is not makeable either** — nothing human can read `dat-prod-archive`
  > (see the note in SPEC-170's step 2). What SPEC-186 FR-004's trail gives you here is the
  > POSITIVE half: that `RestoreObject` was called, and for how many keys. It does not report
  > the `Restore` header, so the header's exact format and the `GLACIER`-stays-`GLACIER`
  > property remain **corroborated by the plane's own polling, not directly observed** — record
  > them as owed rather than discharging them.

  ```bash
  aws s3 ls "s3://dat-prod-archive-audit/AWSLogs/" --recursive \
    | awk '{print $4}' | while read -r key; do
        aws s3 cp "s3://dat-prod-archive-audit/$key" - | gunzip
      done \
    | jq -r --arg id "$ARCHIVE_ID" '
        .Records[]
        | select(.eventName == "RestoreObject")
        | select(.requestParameters.key // "" | contains($id))
        | .requestParameters.key' | sort -u | wc -l
  ```

  Expect **exactly the archive's object count**, and the mirror of SPEC-170's step 2: there, the
  same query must return nothing. `logs/service=archive/` carrying `complete: false` then
  `complete: true` is what stands in for the header transition.

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

### 2. The second guard — the one worth staging deliberately (SPEC-171's own correction)

**This is the only live step that exercises code the spec did not ask for, and it is the one that
proves a real data-loss path is closed.** Do it on a SMALL archive; you are paying for a second
retrieval.

Start a restore. **While it is waiting** — any time before the poll reports complete — re-create one
of the files it is going to restore, at its original path, with different content:

```bash
echo "I made this while waiting" > /tmp/q1.csv
aws s3 cp /tmp/q1.csv "s3://dat-prod-user-space/$USERNAME/reports/q1.csv"
```

Expect, when the retrieval finishes:

- The execution **FAILS** at `ReCheckDestinationClear` — **not** at `CheckDestinationClear`, which
  passed hours ago and correctly.
- The notification names `reports/q1.csv`, and says the files **"have already been retrieved from
  long-term storage and will stay ready for a few days"**. That wording is the second pass; the
  first pass's refusal does not contain it, so it is how you tell which guard fired.
- **THE ASSERTION THIS STEP EXISTS FOR:** the file you just wrote is **still there and still yours**
  — `shasum` it, or just open it. Without the second guard the copy-back would have overwritten it,
  reported success, and swept the vault. Versioning is off, so it would have been unrecoverable.
- The archive prefix is **intact** — nothing was deleted on the refusal path.

Then clear the file and re-request. It should complete in **minutes rather than hours**: the objects
are still retrieved, so `RestoreObject` returns immediately and the first poll finds them complete.
That is the fact the second refusal's wording promises, and this is the only place it is observable.

### 3. Shared space (Phase 4's second half)

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


---

## SPEC-172 — the UI, the read-only folder and the notifications

**Safari, at 400px and at desktop width.** This is the arc's only browser pass, and it is the only
check that exercises the notification wording, the deep links and the write gate at all — every
other section here drives the plane through hand-crafted SQS.

Run it **after** SPEC-169's and SPEC-170's sections, or bring your own archive: step 4 needs a
restore that will actually take hours, and steps 1–3 make one.

### 1. Archive a folder, from the browser

Pick a folder holding a handful of files. Tick it in the file list, then **Archive** in the
selection toolbar.

Expect, in the dialog:

- The heading names the folder **relative to the space root** — `Archive the folder "reports/2026/"
  and everything inside it?`, never `alice/reports/...`.
- It says the data **will be removed from this space** and that a restore takes **several hours**.
- It does **not** say "This can't be undone" — that would be false here.
- **Focus is on Cancel.** Press **Enter**: the dialog CANCELS. This is the one dialog in the app
  where that is the wanted behaviour, and it is the only place it can be observed.

Re-open it, press **Archive**, and expect:

- A toast saying the archive **started** — never that it finished.
- Within a few minutes, a notification reading `Archived N files (X MB). They have been removed from
  your space. Archive id: {uuid} - you'll need it to restore them.`
- **The notification is a LINK.** Click it: it lands in `archive/{uuid}/`, not at your space root.
  A link that silently drops its prefix looks identical from the inbox and is the failure this is
  here to catch.
- The folder is gone from the listing; `archive/{uuid}/receipt.txt` downloads and reads correctly.

**Keep the archive id.** Steps 2 and 4 need it.

### 2. The archive folder is read-only, and says so

Navigate into `archive/`, then into `archive/{uuid}/`.

Expect at BOTH widths (the mobile action bar mounts its own controls — a CSS-hidden twin would pass
a desktop-only pass):

- **Upload** and **New folder** are present but unavailable, and hovering or focusing either gives
  a reason mentioning the folder is read-only. **No `AccessDenied` ever reaches you.**
- Selecting the receipt: **Move** and **Delete** are likewise unavailable with a reason.
- **Archive** is GONE — not disabled. An archive of an archive is not a thing.
- **Details** and **Download** work normally. This is the point of the folder being visible.
- Back at the space root, select `archive/` itself: **Delete** and **Rename** refuse it by name, and
  it is absent from the destination picker when you Move or Copy something else.

Also confirm, at the space root, that selecting `athenaresults/` disables **Archive** with a reason
naming that folder — the browser's mirror of the plane's `reserved_folder` refusal.

### 3. Archive a single file from its details panel

Open **Details** on any file, then **Archive** in the panel. Confirm. This is the only route to
archiving something you have not ticked, and it is a different component from step 1's.

### 4. Restore, and the two notifications

Click **Restore Archived Data** in the toolbar.

- Type nonsense and submit: an inline error names what a valid id looks like, and **the submit
  control is never merely disabled**.
- Paste step 1's id and submit. Expect a toast saying the restore has **started**, and the dialog
  naming the space it will restore into.
- Within a few minutes: `Restoring N files from long-term storage. This takes several hours - you'll
  get another notification when it finishes. Nothing has changed in your space yet.` **No link** on
  this one.
- **Come back the same day.** The terminal notification reads `Restored N files (X MB) to your
  space, back where they came from. The archive has been cleaned up.` and **its link works** —
  landing in the space, with the files back where they were.

### 5. The refusal a user is most likely to hit

Re-create one of the restored files, then submit the same id again.

Expect `destination_occupied`'s wording, **naming that file**, with the "there may be more" caveat —
rendered from `arcommon.messages` verbatim. The browser composes nothing.

### 6. A shared space, as a non-owner member

Repeat steps 1 and 4 in a shared space you are a member of but do not own. This is the membership
rule SPEC-168 FR-005 and SPEC-170 FR-002 both specify and **no unit test exercises against real
Cognito tags**. Confirm the notification link carries `?space=` and lands in the space rather than
in your own files — the failure mode SPEC-167 records is that it silently resolves the personal
space instead.
