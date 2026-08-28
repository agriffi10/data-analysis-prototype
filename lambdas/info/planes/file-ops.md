# File operations — control plane

Move, copy and delete inside a user's own space and between spaces. The plane exists because S3 is
not a filesystem: every move is `CopyObject` + `DeleteObject`, folder operations are recursive and
**non-atomic**, and versioning is off — which is what makes a failure between those two steps
unrecoverable.

**File operations are synchronous if and only if exactly one file is selected.** Everything else
comes through this plane.

## The machine

`infra/modules/file-ops/state-machine.asl.json.tftpl`

`ValidateAuthorize → AcquireLock ⇄ WaitForLock → ChooseOperation → InspectSource →
NeedsDestinationGuard → CheckDestinations → CheckDestinationsAgain → BuildTransferManifest →
TransferObjects (Map) → CollectTransferResults → NeedsSourceDeletion → DeleteSource →
FinaliseOutcomes → ReleaseLock → NotifyOutcomes`

`ReleaseLockOnGiveUp` and `ReleaseLockOnFailure` are the other two arms — every terminal path
releases.

## The fences

- **The lock is per SPACE and its loser WAITS** (`LockAcquired → WaitForLock`), rather than being
  refused. A cross-space operation takes **both** locks in digest order or neither.
- **The space root is refused as an item.**
- **The collision unit is the derived destination key**, not the source name, and a **403 counts as
  occupied**.
- **The deletion takes confirmed plan keys**, never a prefix listing — a listing orphans an
  uncopied object.
- **A duplicate is `(kind, key)`, never the key alone.** One key can arrive as both a file and a
  folder; collapsing on the key ships a zero-byte placeholder and reports success.
- `focommon.protected` refuses the portal's own folders server-side — the first plane to do so.
- The browser's async switchover **consults the routing predicate once**, above every submission
  point, in one dispatcher; the in-flight record is session-scoped and settles on a notification
  carrying its request id.

## The layer — `file-ops-common/focommon/`

| Module | Holds |
|---|---|
| `authz` | space authorization |
| `config` | domain configuration |
| `delete` | batched deletion, scoped **per item** — a whole-list refusal on a move would leave everything copied and nothing deleted |
| `lock` | the per-space lock |
| `messages` | user-facing outcome wording |
| `notify` | best-effort failure notifications |
| `outcomes` | the per-item outcome vocabulary every verb reads and extends |
| `paths` | key containment and the derived destination |
| `plan` | the copy plan, passed by pointer |
| `protected` | the portal's own folders |

`focommon` deliberately keeps its own copy of `item_name` rather than importing `fscommon.paths` —
two domain layers are packaged separately, so the import would merge them to save nine lines. That
exemption, and the rules it sits beside, are asserted in
`file-ops-common/test_layer_discipline_focommon.py`.

The verbs are listed in [`../INDEX.md`](../INDEX.md).
