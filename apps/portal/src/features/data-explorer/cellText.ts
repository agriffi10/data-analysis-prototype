/** What a SQL NULL is called on screen. */
export const NULL_DISPLAY = 'NULL';

/** What a zero-length string is called on screen — a value, not an absence. */
export const EMPTY_DISPLAY = '(empty)';

/**
 * A cell's value as plain text, for a `title`, the Text presentation, and anywhere a
 * string is all that fits.
 *
 * Athena hands every value back as a string, so NULL and `''` arrive looking identical
 * unless something upstream keeps the difference — `getQueryResults` now does,
 * and this is one of the two places it becomes visible.
 *
 * @param value - The cell, `null` for SQL NULL.
 * @returns The value, or the NULL marker — never an empty rendering for a NULL.
 */
export function cellText(value: string | null): string {
  return value === null ? NULL_DISPLAY : value;
}
