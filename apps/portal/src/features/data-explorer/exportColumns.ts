/**
 * Which of the execution's columns a save should write, in the order the grid draws them.
 *
 * Resolved by NAME against the execution's own column list, never by the grid's own index:
 * `useColumnGeometry` builds its columns over the result's columns *or* the Glue fallback, and
 * appends a grouped exploration's percentage column on the end, so a `GridColumn.index` is a
 * position in that list rather than in the result. A name is the only thing the two agree on,
 * which is also why the conversion plane takes positions in the RESULT and resolves nothing.
 *
 * A visible column the result does not have is left out rather than refused — the percentage
 * column is computed in the browser and is in no result, and dropping it here is what keeps
 * "export what the grid shows" true of a grouped exploration.
 *
 * @param resultColumns - The execution's column names, in its own order.
 * @param visibleInOrder - The visible columns' names, in draw order, pinned block first.
 * @returns The positions to keep, in order; `null` when they are every position in the result's
 *   own order, which is the case a plain copy already produces; and an EMPTY array when no
 *   visible column is in the result at all, which is the one case a save cannot be made from.
 */
export function exportColumnIndexes(resultColumns: string[], visibleInOrder: string[]): number[] | null {
  const position = new Map(resultColumns.map((name, index) => [name, index]));
  const kept = visibleInOrder.map((name) => position.get(name)).filter((index): index is number => index !== undefined);
  // `[].every` is true, so an empty result — the window before an execution lands — answers
  // `null` here rather than the empty array. That is deliberate: nothing is hidden yet, and the
  // caller must not read "still loading" as "every column is hidden".
  const unchanged = kept.length === resultColumns.length && kept.every((index, at) => index === at);
  return unchanged ? null : kept;
}
