// App-managed, root-level folders within a user's own space. They hold data the
// portal writes on the user's behalf and aren't meant to be browsed or written
// into directly:
//
//  - `user_settings/` — query history + saved queries. Hidden EVERYWHERE:
//    the main file browser and the move/copy destination picker.
//  - `athenaresults/` — Athena query results. Locked out of move/copy
//    destinations, but still visible in the browser.
//  - `_data-quality-reports/` — the data-quality reports (SPEC-112). Hidden
//    EVERYWHERE, like `user_settings/`.
//  - `_directory/` — the published username directory (SPEC-146). Hidden
//    EVERYWHERE. Note this one lives at the BUCKET root, not inside a user's
//    prefix, so these per-prefix lists cannot actually reach it — the portal
//    role's `ListBucket` is prefix-conditioned, which is what really keeps it
//    out of the browser. It is listed anyway because the lists have already
//    drifted apart from each other (transition_plan.md §6.3), and adding to
//    both is cheaper than reasoning about which one matters.
//  - `_config/` — the published feature-flag document (SPEC-162). Hidden
//    EVERYWHERE, and a bucket-root folder for the same reason `_directory/` is,
//    so the same note applies: IAM is what really keeps it out of the browser,
//    and these entries are parity with the directory rather than the mechanism.
//
//  - `shared_tables/` — where the table-share pipeline copies tables it has
//    shared with you (SPEC-088). VISIBLE, because seeing what has been shared
//    with you is the point of it, but locked out of move/copy destinations:
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
// `athenaresults/` is the clearest case: visible (you want your results) but
// never a paste target. So membership differs ON PURPOSE, and the divergence
// §6.3 flags is only a defect where it is ACCIDENTAL. One such gap existed and
// is closed below — `shared_tables/` was pasteable. `_fc-work` stays
// dqcommon-only: the SPEC-116 arc was cancelled with nothing built, so nothing
// ever creates that folder; it is defensive there and would be dead config here.

/** Hidden from the main file-browser listing. */
export const HIDDEN_BROWSER_FOLDERS = ['user_settings', '_data-quality-reports', '_directory', '_config'] as const;

/** Never offered as a move/copy destination. */
export const PICKER_LOCKED_FOLDERS = [
  'athenaresults',
  'user_settings',
  '_data-quality-reports',
  '_directory',
  '_config',
  'shared_tables'
] as const;

/**
 * Never deletable, and never a move SOURCE, at a space root.
 *
 * A FOURTH question, deliberately not a union of the two lists above (see the
 * note on divergence): "may the user DESTROY it?". `athenaresults/` is visible
 * and browsable on purpose — you want to see your query results — but the role
 * policy's `ResultsNoDelete` Sid denies `s3:DeleteObject` beneath it, so
 * offering Delete only ever produced "You don't have permission to do that" for
 * a rule this app itself authored. SPEC-057:97-98 already stated the UI refuses
 * this; SPEC-150 FR-007 is that criterion finally being met.
 */
export const UNDELETABLE_ROOT_FOLDERS = ['athenaresults'] as const;

/**
 * Does `folderPrefix` name one of `names` at the user's own root
 * (`{rootPrefix}{name}/`)? Only the user-root instance matches — a nested
 * folder that happens to share the name is a normal user folder.
 */
export function isRootFolderNamed(folderPrefix: string, rootPrefix: string, names: readonly string[]): boolean {
  return names.some((name) => folderPrefix === `${rootPrefix}${name}/`);
}

/**
 * Is this folder one the portal refuses to destroy? True only at the SPACE root,
 * which is `rootPrefix` — so it holds identically in a shared space (SPEC-057's
 * own framing) and leaves `alice/reports/athenaresults/` an ordinary folder the
 * user may delete.
 */
export function isUndeletableRootFolder(folderPrefix: string, rootPrefix: string): boolean {
  return isRootFolderNamed(folderPrefix, rootPrefix, UNDELETABLE_ROOT_FOLDERS);
}
