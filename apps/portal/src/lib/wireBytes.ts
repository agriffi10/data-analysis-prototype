/**
 * How many bytes a value costs on the wire, as the API actually serialises it.
 *
 * The three planes that cap a selection by size — archive, file-send and file operations — each
 * measure the selection in the browser so the common case fails fast and legibly, and each has to
 * measure the SAME quantity the plane does or the courtesy becomes a trap: a browser that
 * under-measures accepts a selection the plane then refuses by notification, minutes later.
 *
 * `JSON.stringify` leaves non-ASCII literal and the API's `json.dumps` escapes it to `\uXXXX`, so
 * an accented key costs two bytes here and six there. That divergence was live: a file-ops
 * selection of accented folder names measured under its cap, cost three times that on the wire, and
 * produced a failure state over the 256 KB Step Functions limit — on a state with no catch, where
 * the user is told nothing at all.
 *
 * The two serialisers already agree on every control character, including the shorthand ones; they
 * part company from U+007F up, which is exactly what this closes. The result is pure ASCII, so its
 * length in characters is its length in bytes.
 */

/** Everything `json.dumps` escapes and `JSON.stringify` does not. */
const NON_ASCII = /[\u007f-\uffff]/g;

/**
 * The serialized size of a value in bytes, counted the way the API sends it.
 *
 * @param value - Anything JSON-serialisable.
 * @returns The byte length of the escaped, compact JSON form.
 */
export function wireBytes(value: unknown): number {
  return JSON.stringify(value).replace(
    NON_ASCII,
    (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`
  ).length;
}
