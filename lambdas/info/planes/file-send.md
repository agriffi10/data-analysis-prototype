# File send — control plane

Sends a user's files to other users. A received file lands in `shared_files/{sender}/` in the
recipient's own space.

## The machine

`infra/modules/file-send/state-machine.asl.json.tftpl`

`ValidateAuthorize → InspectSource → GuardRecipients (Map) → BuildTransferManifest →
TransferObjects (Map) → CollectTransferResults → ShapeSummary → NotifyOutcomes`

Two Maps: one guards each recipient's inbox for collisions, one moves the bytes.

## The fences

- **The destination path is built by ONE function**, and an AST sweep forbids a second. Keying by
  item **name** is what forces the two refusals an overlapping selection needs.
- **Exclusion rules anchor at the listing prefix** — whichever item the user picked. Reusing them
  anywhere else silently drops files.
- **`NotifyOutcomes` is the ONE producer** of every per-recipient outcome, at the end of the
  machine. No verb notifies on its own.
- **No shared-space directory is published**, and the same reticence applies here: the share dialog
  suggests only spaces you belong to.

## The layer — `file-send-common/fscommon/`

| Module | Holds |
|---|---|
| `authz` | source authorization |
| `config` | domain configuration |
| `copy_plan` | the copy plan, passed by pointer |
| `expand` | turning a validated selection into the concrete, bounded object list |
| `inbox` | what a recipient's inbox already holds from one sender |
| `messages` | user-facing outcome wording |
| `notify` | best-effort outcome notifications |
| `paths` | key containment and the destination layout — the one builder |

The verbs are listed in [`../INDEX.md`](../INDEX.md).
