# Spec: Send Files — Source Resolution & Copy Plan (inspect-source)

**ID:** SPEC-165
**Status:** Completed
**Last Updated:** 2026-08-10
**Depends On:** SPEC-164 (validated request + authorized source root), SPEC-090 (the copy-plan-as-pointer precedent), SPEC-160 (`cpcommon.transfer`), SPEC-150 (protected folders)

## Overview

Given a validated request, work out exactly what will be copied and where each object will land.
A selection is a mix of files and folders; folders expand recursively and can hold thousands of
objects, so the expansion happens here — once, in one verb — and the result is written to S3 as a
**copy plan**, never carried on the Step Functions state.

The destination layout is the decision this spec makes: everything a sender sends lands under
`{targetRoot}/shared_files/{sender}/…`, an inbox namespaced by who sent it. That mirrors
`shared_tables/{table}/` from table share, keeps two senders' files from colliding, and makes the
provenance of a received file obvious in the file browser without any metadata lookup.

## Scope

### In Scope

- **inspect-source**: expand each selected item under the authorized source root, list objects with
  pagination, compute the count and total bytes, enforce the size caps, and emit a copy plan
  pointer.
- The **relative-key rule**: each object's key relative to its *selected item*, which is what makes
  a folder arrive with its structure intact and a file arrive as a file.
- The **destination layout**: `{targetRoot}/shared_files/{sender}/{itemName}[/{relKey}]`, computed
  once in `fscommon.paths` and used by every downstream verb.
- **Exclusions**: the prefix marker (`DO_NOT_DELETE.txt`), zero-byte folder markers, and the space's
  own `athenaresults/`.
- Size caps as named constants, refused as a whole-request terminal failure.

### Out of Scope

- Per-recipient work — conflict guard, copy and terminal states are SPEC-166.
- Notifications — SPEC-167 (the SPEC-152 failure path from SPEC-164 still applies).
- Preserving object metadata beyond what a server-side `CopyObject` carries by default.
- Any transformation: no format conversion, no rename, no flattening of a folder.
- Deduplicating identical objects across two selected items that overlap — an overlapping selection
  is refused instead (FR-002).

---

## Functional Requirements

### FR-001: Expansion and listing

#### Description:

Turn the selection into a concrete object list.

#### Acceptance Criteria:

- [ ] A `file` item resolves to exactly that object; a `HEAD`-absent key is a whole-request terminal
      failure naming the item.
- [ ] A `folder` item expands recursively through paginated `ListObjectsV2` — never assuming one page
      is the whole folder (the recorded 1,000-key constraint).
- [ ] Each object carries its key **relative to its selected item**, so `reports/2026/q1.csv` under a
      selected `reports/` folder keeps `2026/q1.csv`.
- [ ] The prefix marker, zero-byte folder-marker objects and anything under the space's own
      `athenaresults/` are excluded from the copy set.
- [ ] A selection that resolves to **zero** objects (an empty folder, or a folder holding only
      excluded objects) is a whole-request terminal failure — "nothing to send" is not a successful
      send.
- [ ] Every listed key is re-checked for containment inside the authorized root; the check is not
      trusted from SPEC-164 alone, because listing is where a key first arrives from S3 rather than
      from the request.

### FR-002: Overlapping and duplicate selections

#### Acceptance Criteria:

- [ ] Two selected items where one contains the other (a folder and a file inside it) is a
      whole-request terminal failure naming both — silently copying the object twice, or silently
      dropping one, are both worse than a clear refusal.
- [ ] The same item listed twice is collapsed, not refused.
- [ ] Two distinct items whose *names* collide at the destination (`a/reports/` and `b/reports/`)
      is a whole-request terminal failure naming the colliding name — the destination is keyed by
      item name, so this would otherwise interleave two folders.

### FR-003: Destination layout

#### Acceptance Criteria:

- [ ] For recipient kind `user`, the target root is `{user-space-bucket}/{name}/`; for `space`, it is
      `{shared-space-bucket}/{name}/`.
- [ ] Every object's destination is
      `{targetRoot}shared_files/{senderUsername}/{itemName}/{relKey}` for a folder item, and
      `{targetRoot}shared_files/{senderUsername}/{fileName}` for a file item.
- [ ] The destination is computed by **one** function in `fscommon.paths`; a test asserts no verb
      builds a destination key by string concatenation of its own.
- [ ] `shared_files` is a named constant, not a literal repeated across verbs.
- [ ] The layout is unaffected by the sender's own folder depth — a file sent from
      `alice/deep/nested/q1.csv` arrives as `…/shared_files/alice/q1.csv`.

### FR-004: Caps and the copy plan

#### Acceptance Criteria:

- [ ] `SEND_MAX_OBJECTS` and `SEND_MAX_TOTAL_BYTES` are named constants in `fscommon.config`, each
      documented with the limit that sized it; exceeding either is a whole-request terminal failure
      naming the measured value and the cap.
- [ ] The copy plan is written to `{admin_bucket}/file-send/{requestId}/copy-plan.json` and the verb
      emits `{copyPlanKey, objectCount, totalBytes}` — the plan never rides on the state (the
      256 KB lesson from PR #256).
- [ ] The plan records, per object, the source bucket/key, the size, and the **relative key plus its
      owning item name** — everything SPEC-166's manifest builder needs, with no second listing.
- [ ] The refusal reasons render through `fscommon.messages` on the `cpcommon` `Resolver`.

---

## Data Model

```python
# {admin_bucket}/file-send/{requestId}/copy-plan.json
{
  "source": { "bucket": "dat-prod-user-space", "root": "alice/" },
  "sender": "alice",
  "objects": [
    { "item": "reports", "relKey": "2026/q1.csv",
      "srcKey": "alice/reports/2026/q1.csv", "size": 91234 },
    { "item": "notes.txt", "relKey": "",
      "srcKey": "alice/notes.txt", "size": 512 }
  ],
  "objectCount": 2,
  "totalBytes": 91746
}

# inspect-source output (state)
{ "copyPlanKey": "file-send/{requestId}/copy-plan.json", "objectCount": 2, "totalBytes": 91746 }
```

```python
# fscommon.paths
destination_key(target_root, sender, item, rel_key) -> str   # the ONE destination builder
SHARED_FILES_FOLDER = "shared_files"
```

## Implementation Phases

### Phase 1: Expansion + exclusions

- Item resolution, paginated listing, the exclusion set, the re-checked containment, and the
  zero-object refusal.

### Phase 2: Layout + overlap rules

- `fscommon.paths.destination_key`, the overlap/name-collision refusals, and the test forbidding a
  hand-built destination key.

### Phase 3: Caps + plan

- The constants, the refusals through the `Resolver`, the plan write, and the SFN wiring after
  validate-authorize.

### Phase 4: Verification

- Unit tests over fixtures: nested folders, a folder of 2,500 objects (pagination), overlapping
  selections, colliding item names, marker exclusion, and each cap.
- **Live check (owed):** run one request whose source is a folder with more than 1,000 objects and
  confirm the plan's `objectCount` matches the bucket — the pagination boundary is the one thing a
  fixture proves least.

### Phase 5: Completion ritual

- Delivery doc, INDEX status, component-inventory rows for `fscommon.paths`/`config`, and the
  destination-layout line in the `architecture.md` *Send Files* section. The layout decision
  (`shared_files/{sender}/`) gets a `decisions.md` entry — it is what a recipient sees forever.
