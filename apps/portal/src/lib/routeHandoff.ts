// Hand-offs between sibling features that may not import each other. `features/query/` and
// `features/data-explorer/` are fenced apart by lint, so a gesture on one that opens something on
// the other travels as ROUTER STATE, and the shape of that state lives here: one builder for the
// sender, one reader for the receiver, and one module owning each shape so the two sides cannot
// drift. Router state rather than the URL, because a statement can be long and can quote the
// user's data, and a URL is kept in history and in logs.

/** Router state asking the Data Explorer to open a tab over a statement. */
export type ExploreSqlHandoff = {exploreSql: {body: string; label: string}};

/**
 * Builds the router state that opens a statement in the Data Explorer.
 *
 * @param handoff - The statement, with no trailing semicolon, and the tab's label.
 * @returns The state to navigate to `/explore` with.
 */
export function buildExploreSqlHandoff(handoff: {body: string; label: string}): ExploreSqlHandoff {
  return {exploreSql: {body: handoff.body, label: handoff.label}};
}

/**
 * Reads a Data Explorer hand-off out of router state, refusing anything it did not build.
 *
 * Router state is whatever the history entry carries — another hand-off, a stale entry, or
 * nothing — so every field is checked, and only an OWN `exploreSql` counts: `in` would admit one
 * inherited from a prototype. A blank body is refused as well, because it would open a tab whose
 * every statement fails.
 *
 * @param state - `location.state`, or anything at all.
 * @returns The statement and label, or null when the state is not this hand-off.
 */
export function readExploreSqlHandoff(state: unknown): {body: string; label: string} | null {
  if (typeof state !== 'object' || state === null || !Object.hasOwn(state, 'exploreSql')) return null;
  const handoff = (state as {exploreSql: unknown}).exploreSql;
  if (typeof handoff !== 'object' || handoff === null) return null;
  const {body, label} = handoff as Record<string, unknown>;
  if (typeof body !== 'string' || body.trim() === '' || typeof label !== 'string') return null;
  return {body, label};
}
