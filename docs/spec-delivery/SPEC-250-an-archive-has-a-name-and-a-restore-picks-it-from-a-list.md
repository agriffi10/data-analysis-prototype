# Completed Spec — SPEC-250: An Archive Has a Name, and a Restore Picks It From a List

## What was completed?

- **The archive confirmation explains itself.** `ArchiveDialog` says where the data goes, that a
  restore puts every file back in the same folder and overwrites nothing ("move or rename" what is
  in the way), that it takes several hours, that storage is charged for at least 90 days, and how
  to find the archive again.
- **An archive can be named.** An optional **Name** field sits in the confirmation, outside any
  form, so Enter still cannot archive. The rule is `arcommon.names` on the plane and `archiveName.ts`
  in the browser: refused control and bidirectional characters and lone surrogates, U+0020-only
  normalisation, 100 code points. Both suites run `lambdas/archive-common/archive_name_corpus.json`.
  The name travels as `archiveName`, rides the state as `archive.name`, and is the receipt's first
  line.
- **Each space keeps an archive index**, `{root}system_settings/archive/index.json`
  (`arcommon.index_store`). write-receipt records each archive after its receipt; update-receipt
  records each restore stage on an existing entry. Every write is a compare-and-swap, every fault
  is swallowed, and the path is bounded in time (`cpcommon.clients.s3_bounded` and a deadline).
- **The restore dialog is a list.** `RestoreArchiveDialog` lists the space's archives
  (`listArchives`, `useArchiveList`, `ArchiveList`): every receipt folder is a row, labelled from
  the index where it has an entry — name, date, what it held, counts, and in a shared space who
  made it — with what its last restore did. Only a `restored` row is disabled. **Restore by archive
  id instead** keeps the typed id one link away.
- **The archived notification** now says to pick the archive from the list, and still names its id.
- Help's `archive-files` guide describes the name, the list and the id fallback.

### Deliberate deviations

- **The wire field is `archiveName`, not `name`.** The API's bounds guard maps a leaf called `name`
  to a catalog identifier.
- **The selection's byte cap dropped from 89 to 87 KiB**, which the spec recorded once the plan
  review measured it: the cap was pinned tight to the message chain, and the name's 1,202-byte bound
  had nowhere else to come from.
- **The index is bounded in time, not only swallowed**, and **written unescaped at a 200-entry cap**
  — both added in review, not in the first draft of the spec. The register entry says why.
- **A name made only of invisible characters is accepted.** Flagged in review and left: the row
  still shows its date, contents and size.

## What changed from earlier specs?

- SPEC-172's `ArchiveDialog` copy is replaced; its "removed from this space … restore using its
  id" sentences are gone, and the 90-day charge its register entry promised is shown again.
- SPEC-172's `RestoreArchiveDialog` is a list with the old id field behind a link; it takes a
  `space` prop. `isArchiveId` moved from `useArchive.ts` to `archiveId.ts`.
- SPEC-229's `ARCHIVE_MAX_ITEM_BYTES` is 87 KiB, and its characterised overshoot now describes the
  request without the name.
- `FormDialog.autoFocusRef` accepts any element.
- `archived_message`'s instruction changed; `archive_not_found` and `receipt_write_failed` did not,
  and both remain true through the id fallback.

## Verification

Both PRs ran the formatter, both linters, both suites, mypy, the build and every `ci.yml`
validator locally, green by exit code, after rebasing onto `main`. The plane PR's execution review
ran fault-injection, deploy-skew, hostile-name and interleaving harnesses against the real verbs.
The live checks — a named archive appearing in the list, and a restore picked from it — are in
`docs/testing/e2e.md` §4.11.
