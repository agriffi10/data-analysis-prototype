import {isAtRoot} from '../file-browser/fileBrowser.paths';

/**
 * The user-facing reason a table cannot be built from the folder currently being viewed, or
 * null when it can.
 *
 * **THE SPACE ROOT IS NOT A DATA FOLDER**, and that is the whole rule. A table's `LOCATION`
 * is read recursively, so one built at the root sweeps in every app-managed folder the space
 * carries — `athenaresults/`, `saved_queries/`, `user_settings/`, `shared_files/`,
 * `shared_tables/`, `archive/` — alongside whatever the user actually meant. The build does
 * not fail; it succeeds, and produces a table whose rows are the portal's own bookkeeping.
 * That is the worse of the two outcomes, which is why this is a refusal and not a warning.
 *
 * A refusal rather than a hidden control: the button is where a user standing at the root
 * looks for it, and a control that vanishes teaches nothing about where to go instead.
 *
 * Shaped as a predicate-with-its-words on `writeLockRefusal`'s precedent — the gate and its
 * explanation are one function, so no caller has to find wording for a rule it did not write.
 * The comparison itself is `isAtRoot`, not a second `===`: the browser already owns what
 * "at the root" means and a private copy here would be free to drift from it.
 *
 * @param prefix - The folder currently being viewed, trailing slash.
 * @param rootPrefix - The space root, trailing slash.
 * @returns The explanation, or null when the folder is a real one below the root.
 */
export function createTableRefusal(prefix: string, rootPrefix: string): string | null {
  return isAtRoot(prefix, rootPrefix)
    ? 'A table reads every file in the folder you build it from, so it can’t be built here — the top of a space also holds your query results, saved queries and shared files. Open the folder that holds your data and create the table there.'
    : null;
}
