# Archive — control plane

Moves a user's files into a separate `GLACIER` vault the browser has no relationship with, and
brings them back. **This is the only place in the portal where a mistake is unrecoverable**, and the
machine is shaped around that fact rather than around the happy path.

A restore is `RestoreObject` + a 3–5 hour wait + a copy. Both modes — archive and restore — run
through the *same* state machine, routed by `ChooseMode`.

## The machine

`infra/modules/archive/state-machine.asl.json.tftpl` — the largest in the repo, because the restore
branch is a wait loop with two guards.

**Archive:** `ValidateAuthorize → ChooseMode → InspectSource → BuildTransferManifest →
TransferObjects (Map) → CollectTransferResults → CommitOrRollback → WriteManifest → DeleteSource →
WriteReceipt → NotifyArchived`

**Restore:** `ValidateAuthorize → ChooseMode → InspectArchive → CheckDestinationClear →
BuildRestoreManifest → MarkRestoreRequested → RetrieveObjects (Map) → NotifyRestoreStarted →
WaitForRetrieval ⇄ PollRestore → ReCheckDestinationClear → CopyBackObjects (Map) →
CollectRestoreResults → DeleteArchived → UpdateReceipt → NotifyRestored`

## The fences

- **The destination guard is ABSOLUTE, and it runs TWICE.** Any occupied destination refuses the
  *whole* restore, and a **403 counts as occupied**. The second pass (`ReCheckDestinationClear`) is
  the spec correcting itself: the billed 3–5 hours are spent telling the user a restore is in
  flight, so re-creating a file meanwhile is the ordinary case — and the copy-back would otherwise
  have overwritten it, reported success, and swept the vault.
- **Retrieval is the point of no return.** `RetrieveObjects` tolerates **no** failure, where
  `CopyBackObjects` tolerates 100% — a fault there means nothing was copied and the archive is
  untouched. What makes that free is that `archive-initiate-restore` tolerates two codes,
  `RestoreAlreadyInProgress` and `InvalidObjectState`, which is also what keeps the path
  unconditional on the storage class. **Do not "harden" the verb by removing them.**
- **The source is deleted only when EVERY object is confirmed copied**, and the gate is a *state*:
  the rollback arm cannot reach `DeleteSource`. That is asserted by walking the ASL graph, and an
  unrecognisable verdict fails closed.
- `archive-delete-archived` is the one deletion allowed to fail quietly — it sweeps the vault after
  a successful restore, and a leftover object costs storage, not data.

## The layer — `archive-common/arcommon/`

| Module | Holds |
|---|---|
| `authz` | source authorization for the plane |
| `config` | domain configuration |
| `delete` | batched deletion, refusing over the **whole** list (unlike `focommon.delete`, which is per item) |
| `guard` | the destination guard — nothing a restore would write over may already exist |
| `manifest` | `_manifest.json`, the integrity record written before anything is deleted |
| `messages` | user-facing archive and restore wording |
| `notify` | best-effort outcome notifications |
| `paths` | the archive key layout, and the inverse that survives a lost record |
| `plan` | the copy plan, expanded once and passed by pointer |
| `receipt` | the receipt — the one artifact of an archive the user can see |
| `restore` | the restore request contract, and the archive it names |
| `retrieval` | Glacier retrieval: asking for the bytes back, and knowing when they are there |

The verbs are listed in [`../INDEX.md`](../INDEX.md). Long-form reasoning:
`docs/lambda-rationale.md`; the UI's one refusal — the archive dialog never says "this can't be
undone" — is in `CLAUDE.md` → *The browser*.
