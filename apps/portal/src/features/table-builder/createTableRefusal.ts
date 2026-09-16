import {isAtRoot} from '../file-browser/fileBrowser.paths';
import type {SelectableItem} from '../file-browser/selectionContext';

/**
 * The sentence {@link createTableRefusal} returns.
 *
 * Named separately because the folder picker needs it where it has no prefix to compare: it
 * overrides its own default disabled-reason with this up front, rather than rendering a second
 * explanation beneath the first.
 */
export const CREATE_TABLE_AT_ROOT_REFUSAL =
  'A table reads every file in the folder you build it from, so it can’t be built here — the top of a space ' +
  'also holds your query results, saved queries and shared files. Open the folder that holds your data and ' +
  'create the table there.';

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
  return isAtRoot(prefix, rootPrefix) ? CREATE_TABLE_AT_ROOT_REFUSAL : null;
}

/**
 * Why a table cannot be built from the file browser's current SELECTION.
 *
 * Separate wording from {@link CREATE_TABLE_AT_ROOT_REFUSAL}, which stays exactly as it is
 * because the folder picker imports it by name and remains true there: in a picker, opening
 * a folder IS choosing it. In the browser it no longer is — the folder must be selected —
 * so a sentence telling the user to "open the folder and create the table there" would be
 * false on the one surface it is shown.
 *
 * @attribute CREATE_TABLE_NOTHING_SELECTED_REFUSAL - Nothing is ticked.
 * @attribute CREATE_TABLE_MANY_SELECTED_REFUSAL - More than one row is ticked.
 * @attribute CREATE_TABLE_FILE_SELECTED_REFUSAL - The one ticked row is a file inside a folder.
 * @attribute CREATE_TABLE_FILE_AT_ROOT_REFUSAL - The one ticked row is a file at the top of the
 *   space, where "select the folder that holds this file" would name the root, itself refused.
 */
export const CREATE_TABLE_NOTHING_SELECTED_REFUSAL =
  'Select the folder holding your data files, then create the table from it. A table is built ' +
  'from a whole folder, so it needs one to be chosen.';

export const CREATE_TABLE_MANY_SELECTED_REFUSAL =
  'A table is built from ONE folder. Select just the folder you want to query.';

export const CREATE_TABLE_FILE_SELECTED_REFUSAL =
  'A table is built from a folder, not a single file — it reads every file inside, so they can ' +
  'share one set of columns. Select the folder that holds this file instead.';

export const CREATE_TABLE_FILE_AT_ROOT_REFUSAL =
  'A table is built from a folder, not a single file, and this file is at the top of your space. ' +
  'Create a folder, move the file into it, then select that folder and create the table.';

/**
 * Resolve the folder a table would be built from, or the reason there isn't one.
 *
 * Both halves travel together deliberately: the caller needs the chosen folder's prefix to
 * build from AND to suggest a table name, and returning only a refusal would leave it
 * re-deriving the prefix from the same selection under a second, drifting rule.
 *
 * The selection arms are checked BEFORE the space-root arm, and the order is load-bearing
 * rather than stylistic: standing at the space root with nothing selected satisfies both,
 * and "select a folder" is the one that tells the user what to do next. The root arm is
 * still consulted for the selected folder, rather than assumed unreachable because the root
 * is not a row in its own listing — a rule that holds today and would fail silently.
 *
 * @param selected - The file browser's current selection, in no particular order.
 * @param rootPrefix - The space root, trailing slash.
 * @returns The folder prefix to build from with a null refusal, or a null prefix with the
 *   sentence explaining why there is none.
 */
export function createTableTarget(
  selected: readonly SelectableItem[],
  rootPrefix: string
): {prefix: string | null; refusal: string | null} {
  if (selected.length === 0) return {prefix: null, refusal: CREATE_TABLE_NOTHING_SELECTED_REFUSAL};
  if (selected.length > 1) return {prefix: null, refusal: CREATE_TABLE_MANY_SELECTED_REFUSAL};

  const [item] = selected;
  if (item.type === 'file') {
    const folder = item.key.slice(0, item.key.lastIndexOf('/') + 1);
    return {
      prefix: null,
      refusal: isAtRoot(folder, rootPrefix) ? CREATE_TABLE_FILE_AT_ROOT_REFUSAL : CREATE_TABLE_FILE_SELECTED_REFUSAL
    };
  }

  const rootRefusal = createTableRefusal(item.prefix, rootPrefix);
  return rootRefusal ? {prefix: null, refusal: rootRefusal} : {prefix: item.prefix, refusal: null};
}
