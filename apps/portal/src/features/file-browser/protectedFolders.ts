// App-managed, root-level folders within a user's own space. They hold data the
// portal writes on the user's behalf and aren't meant to be browsed or written
// into directly:
//
//  - `user_settings/` — query history + saved queries. Hidden EVERYWHERE:
//    the main file browser and the move/copy destination picker.
//  - `athenaresults/` — Athena query results. Locked out of move/copy
//    destinations, but still visible in the browser — inside the `system_settings` group
//    row (`systemFolders.ts`), which collapses it rather than hiding it.
// - `_data-quality-reports/` — the data-quality reports. Hidden
//    EVERYWHERE, like `user_settings/`.
// - `_directory/` — the published username directory. Hidden
//    EVERYWHERE. Note this one lives at the BUCKET root, not inside a user's
//    prefix, so these per-prefix lists cannot actually reach it — the portal
//    role's `ListBucket` is prefix-conditioned, which is what really keeps it
//    out of the browser. It is listed anyway because the lists have already
//    drifted apart from each other (transition_plan.md §6.3), and adding to
//    both is cheaper than reasoning about which one matters.
// - `_config/` — the published feature-flag document. Hidden
//    EVERYWHERE, and a bucket-root folder for the same reason `_directory/` is,
//    so the same note applies: IAM is what really keeps it out of the browser,
//    and these entries are parity with the directory rather than the mechanism.
//
// - `saved_queries/` — the space's saved `.sql` files. VISIBLE and
//    PASTEABLE — an ordinary folder in every respect a user can see — and only
//    undestroyable: it appears in UNDELETABLE_ROOT_FOLDERS alone.
//
// - `archive/` — the archive receipts, one folder per archive. VISIBLE and
//    deliberately so: the folder NAMES are the archive ids, and reading one is how a user
//    finds the id a restore needs, so hiding it would remove the only surface that carries
//    them. It now sits inside the `system_settings` group row (`systemFolders.ts`), which is
//    a collapse and not a hide — the restore dialog and the help both name that path, and
//    they are what keep the ids findable at one click's remove. It joins
//    PICKER_LOCKED_FOLDERS and UNDELETABLE_ROOT_FOLDERS and neither of the
//    other two lists. What is new here is that the folder is also read-only INSIDE — see
//    `writeLockedPrefix.ts`, which is a rule about the prefix the user is standing in rather
//    than about a folder's name, and is therefore not one of these lists at all.
//
//  - `shared_tables/` — where the table-share pipeline copies tables it has
// shared with you. VISIBLE, because seeing what has been shared
//    with you is the point of it — inside the `system_settings` group row like the two
//    above — but locked out of move/copy destinations:
//    the pipeline owns the layout, and a table's files acquiring neighbours is
//    how a later projection read starts returning rows nobody wrote.
//
// `_data-quality-reports` needs BOTH lists, and needs naming here at all,
// because the leading `_` that marks it internal is a LAMBDA-SIDE convention
// only: the SPA has no `_`-prefix filter anywhere (`fileBrowser.service.ts`
// filters nothing), so nothing else would hide it. Hiding it from the listing
// alone would leave it a valid move/copy paste target — a folder the user
// cannot see but can still drop files into, which is how the reports the
// notification links to would quietly acquire neighbours.
//
// ── On the "three divergent lists" (transition_plan.md §6.3) ────────────────
// These two lists and `dqcommon.RESERVED_PREFIXES` are NOT meant to be equal,
// and unioning them would be the wrong repair. They answer three questions:
//
//   dqcommon.RESERVED_PREFIXES  — may a data-quality CHECK treat this as source?
//   HIDDEN_BROWSER_FOLDERS      — does the user SEE it?
//   PICKER_LOCKED_FOLDERS       — may the user PASTE into it?
//
// `SYSTEM_GROUPED_FOLDERS` in `systemFolders.ts` is a fifth, and diverges from all of them
// on purpose: it asks whether the APP fills the folder, which is a question about where a
// row belongs in the listing and about nothing else. It grants and denies nothing.
//
// `athenaresults/` is the clearest case: visible (you want your results) but
// never a paste target. So membership differs ON PURPOSE, and the divergence
// §6.3 flags is only a defect where it is ACCIDENTAL. One such gap existed and
// is closed below — `shared_tables/` was pasteable. `_fc-work` stays
// dqcommon-only: the file-converter arc was cancelled with nothing built, so nothing
// ever creates that folder; it is defensive there and would be dead config here.

import type {SelectableItem} from './selectionContext';

/** Hidden from the main file-browser listing. */
export const HIDDEN_BROWSER_FOLDERS = ['user_settings', '_data-quality-reports', '_directory', '_config'] as const;

/** Never offered as a move/copy destination. */
export const PICKER_LOCKED_FOLDERS = [
  'athenaresults',
  'user_settings',
  '_data-quality-reports',
  '_directory',
  '_config',
  'shared_tables',
  // IAM denies `PutObject` beneath it, so offering it as a paste target only ever
  // produced an AccessDenied — and a receipt acquiring neighbours is how an archive folder
  // stops being a record of what this plane did.
  'archive'
] as const;

/**
 * Never deletable, and never a move SOURCE, at a space root.
 *
 * A FOURTH question, deliberately not a union of the two lists above (see the
 * note on divergence): "may the user DESTROY it?". `athenaresults/` is visible
 * and browsable on purpose — you want to see your query results — but the role
 * policy's `ResultsNoDelete` Sid denies `s3:DeleteObject` beneath it, so
 * offering Delete only ever produced "You don't have permission to do that" for
 * a rule this app itself authored. The UI was always supposed to refuse
 * this, and this module is that criterion finally being met.
 *
 * `saved_queries/` is the second case, and it is the one that proves
 * the lists are not a union: it is VISIBLE, it IS a valid paste target, and only
 * the folder itself is undestroyable. Everything inside it is ordinary — files
 * may be uploaded, moved, copied and deleted, and subfolders created — because
 * what keeps the query editor's load list coherent is the store's `.sql` filter,
 * not a write lock.
 *
 * `archive/` is the third, and it is the inverse of `saved_queries/`: visible like
 * it, but NOT a valid paste target and read-only inside as well. Deleting the folder would
 * destroy the receipts that carry every archive id — and IAM denies the objects beneath it
 * anyway, so the row here is the browser saying so before the user finds out from S3.
 */
export const UNDELETABLE_ROOT_FOLDERS = ['athenaresults', 'saved_queries', 'archive'] as const;

type UndeletableFolder = (typeof UNDELETABLE_ROOT_FOLDERS)[number];

// One refusal per folder per verb. A move IS a rename here (S3 has neither), so
// the move wording covers both.
const UNDELETABLE_REFUSALS: Record<UndeletableFolder, {delete: string; move: string}> = {
  athenaresults: {
    delete: 'Query results are managed for you and can’t be deleted.',
    move: 'Query results are managed for you and can’t be moved.'
  },
  saved_queries: {
    delete: 'Saved queries live in this folder, so it can’t be deleted.',
    move: 'Saved queries live in this folder, so it can’t be moved or renamed.'
  },
  archive: {
    delete: 'Your archive receipts live in this folder, so it can’t be deleted.',
    move: 'Your archive receipts live in this folder, so it can’t be moved or renamed.'
  }
};

/**
 * The refusal for destroying this folder, or null when it is an ordinary one.
 *
 * @param folderPrefix - The folder being destroyed, trailing slash.
 * @param rootPrefix - The SPACE root, so the refusal holds in a shared space too.
 * @param action - `delete` or `move` (rename is a move).
 * @returns The user-facing message, or null when the operation is allowed.
 */
export function undeletableRootFolderRefusal(
  folderPrefix: string,
  rootPrefix: string,
  action: 'delete' | 'move'
): string | null {
  const name = UNDELETABLE_ROOT_FOLDERS.find((folder) => folderPrefix === `${rootPrefix}${folder}/`);
  return name ? UNDELETABLE_REFUSALS[name][action] : null;
}

/**
 * The refusal for a selection in which NOTHING can be destroyed, or null when any of it can.
 *
 * Something downstream refuses either way — the file-operations plane for a folder it may not
 * touch, and the object routes for a marker key — but every one of those refuses AFTER the user
 * has read *"Delete the folder … and everything inside it? This can't be undone."* and pressed
 * Delete: the most alarming confirm in the app, shown for an action that was never possible. The
 * browser's own `undeletableRootFolderRefusal` call inside the delete service went with the
 * recursive functions; this predicate is what remains, and it is the one that runs first.
 * Feeding this to `Button.disabledReason` states the refusal before the confirm instead, and
 * swallows the click that would have opened it.
 *
 * **ONLY WHEN EVERY ITEM IS REFUSED, and that condition is the whole subtlety.** The service is
 * PER ITEM: `useDelete` loops the selection and records a failure against one protected folder
 * without abandoning the rest. Refusing on the FIRST protected item — which this did until
 * review caught it — killed Delete for a mixed selection the app would previously have carried
 * out, and at a space root the header's select-all takes in `athenaresults/`, `saved_queries/`
 * and `archive/` at once, so "select all → Delete" became dead with a reason about saved
 * queries. The confirm is only misleading when it is offering something wholly impossible; a
 * partial selection genuinely does something, and the per-item report is how that has always
 * been told.
 *
 * Only the folder ITSELF matches, exactly as the service's rule does: a file inside
 * `saved_queries/` is ordinary and deletes normally, so this must not walk ancestors the way
 * `archiveRefusal` does — that plane carries a whole prefix out and deletes it, where a
 * selection deletes only what is named. A file in the selection therefore always makes the
 * selection actionable.
 *
 * @param items - The current selection.
 * @param rootPrefix - The space root, trailing slash, so the rule holds in a shared space.
 * @param action - `delete` or `move` (rename is a move).
 * @returns The first refusal when every item carries one, else null.
 */
export function undeletableSelectionRefusal(
  items: readonly SelectableItem[],
  rootPrefix: string,
  action: 'delete' | 'move'
): string | null {
  if (items.length === 0) return null;
  let first: string | null = null;
  for (const item of items) {
    const refusal = item.type === 'folder' ? undeletableRootFolderRefusal(item.prefix, rootPrefix, action) : null;
    // One actionable item is enough: the operation is not impossible, so the confirm is not a
    // lie and the service's per-item report is the right channel for the rest.
    if (!refusal) return null;
    first ??= refusal;
  }
  return first;
}

/**
 * Does `folderPrefix` name one of `names` at the user's own root
 * (`{rootPrefix}{name}/`)? Only the user-root instance matches — a nested
 * folder that happens to share the name is a normal user folder.
 */
export function isRootFolderNamed(folderPrefix: string, rootPrefix: string, names: readonly string[]): boolean {
  return names.some((name) => folderPrefix === `${rootPrefix}${name}/`);
}
