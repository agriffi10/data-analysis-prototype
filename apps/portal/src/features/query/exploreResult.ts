import type {QueryColumn} from '../catalog/catalog.types';

/** Why *Explore in Data Explorer* is refused on a result with an unnamed or repeated column. */
export const UNNAMED_COLUMNS_REFUSAL = 'Give every column its own name with AS to explore this result.';

// Athena's name for an unaliased expression. The outer query cannot refer to it.
const GENERATED_NAME = /^_col\d+$/;

/**
 * Why a result cannot be opened in the Data Explorer, judged on its column names alone.
 *
 * The Explorer wraps the statement as `(…) AS t` and names columns from outside it, so a column
 * Athena named `_col0` cannot be filtered, sorted or grouped, and two columns with one name — a
 * join selecting `a.id` and `b.id` — cannot be told apart, by the outer query or by the grid's
 * name-keyed geometry. Names are compared case-insensitively because Trino folds unquoted names.
 * Refusing the whole hand-off costs the user one `AS`; offering it would leave some gestures
 * working on the tab and others not.
 *
 * @param columns - The displayed result's columns.
 * @returns The refusal sentence, or null when every column has a name of its own.
 */
export function unnamedColumnsRefusal(columns: readonly QueryColumn[]): string | null {
  const seen = new Set<string>();
  for (const {name} of columns) {
    const folded = name.toLowerCase();
    if (GENERATED_NAME.test(name) || seen.has(folded)) return UNNAMED_COLUMNS_REFUSAL;
    seen.add(folded);
  }
  return null;
}
