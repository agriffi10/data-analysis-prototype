// App-managed, root-level folders within a user's own space. They hold data the
// portal writes on the user's behalf and aren't meant to be browsed or written
// into directly:
//
//  - `user_settings/` — query history + saved queries (SPEC-034/043). Hidden
//    EVERYWHERE: the main file browser and the move/copy destination picker.
//  - `athenaresults/` — Athena query results (SPEC-032). Locked out of move/copy
//    destinations, but still visible in the browser.

// Hidden from the main file-browser listing.
export const HIDDEN_BROWSER_FOLDERS = ['user_settings'] as const;

// Never offered as a move/copy destination.
export const PICKER_LOCKED_FOLDERS = ['athenaresults', 'user_settings'] as const;

// Does `folderPrefix` name one of `names` at the user's own root
// (`{rootPrefix}{name}/`)? Only the user-root instance matches — a nested folder
// that happens to share the name is a normal user folder.
export function isRootFolderNamed(folderPrefix: string, rootPrefix: string, names: readonly string[]): boolean {
  return names.some((name) => folderPrefix === `${rootPrefix}${name}/`);
}
