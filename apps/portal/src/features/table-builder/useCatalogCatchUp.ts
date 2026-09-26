import {useEffect} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {invalidateSchema} from '../catalog/useSchema';

/**
 * What is owed a re-read: one entry per `{database, table}` a build was enqueued for.
 *
 * **MODULE STATE, NOT A REF, AND THAT IS THE WHOLE POINT.** A build lands minutes after the
 * enqueue, so navigating away in the meantime is the ordinary case rather than an edge — and
 * `CreateTableButton`, on the file browser's toolbar, unmounts when the user leaves that
 * route. It was written when a second control enqueued builds from the Data Explorer, and it
 * holds for the same reason with one.
 * Held per component, the arm died with the control that set it: enqueue from Files, walk over
 * to the Explorer to watch for it, and nothing was left to fire. That is the reported bug on
 * the path this mechanism exists to close.
 *
 * Keyed so two builds in flight both get re-read, and so re-arming the same one is idempotent.
 */
const owed = new Map<string, {database: string; table: string}>();

/**
 * Records that a table build or refresh was enqueued, so its catalog is re-read when the answer is wanted.
 *
 * **THE ENQUEUE IS NOT THE EVENT.** The browser puts a request on a queue and the table appears
 * later, announced by a notification nothing in the tab hears. So every cache keyed on that
 * catalog — the schema rail, the Data Explorer's execution cache — goes on describing the
 * catalog as it was. For the Explorer that is the stale-rows bug arriving by a second road:
 * dropping the table invalidates, rebuilding it does not, and the exploration resolves to the
 * pre-drop execution.
 *
 * The table IS named. The control plane refuses a table name that is not catalog-safe and
 * refuses one that already exists, so it creates exactly the name asked for or it fails — there
 * is no case where the caller cannot know. Naming it is what keeps the re-read from resetting
 * every other exploration of that database, which for a mounted one is a billed execution for
 * rows a brand-new table cannot have changed.
 *
 * @param database - The database the build or refresh targets.
 * @param table - The table name the build or refresh was asked for.
 * @returns Nothing.
 */
export function armCatalogCatchUp(database: string, table: string): void {
  owed.set(`${database}\u0000${table}`, {database, table});
}

/**
 * Fires every owed re-read and clears the queue.
 *
 * Exported for the tests and for any future caller with a better signal than window focus.
 *
 * @param invalidate - The invalidation to run per owed entry.
 * @returns Nothing.
 */
export function drainCatalogCatchUp(invalidate: (database: string, table: string) => void): void {
  if (owed.size === 0) return;
  const pending = [...owed.values()];
  owed.clear();
  for (const {database, table} of pending) invalidate(database, table);
}

/**
 * Re-reads the catalog of any enqueued build the next time the window regains focus.
 *
 * Window focus because the build is watched from somewhere else — a notification, another tab,
 * a colleague's message — so returning to the page is the moment the answer is wanted.
 *
 * **THE RESIDUAL, STATED RATHER THAN GLOSSED:** `focus` fires on blur→focus only. A user who
 * enqueues a build and never leaves the window — reading the completion in the in-app
 * notification inbox — gets no catch-up until they do. The rail's own refresh control is the
 * manual way out, and a notification-driven signal would be the way to close it properly.
 *
 * Mount once, in the authenticated shell, beside `useExplorationEviction` and for the same
 * reason: what it listens for outlives every screen that arms it.
 */
export function useCatalogCatchUp(): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    const onFocus = () => drainCatalogCatchUp((database, table) => void invalidateSchema(queryClient, database, table));
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [queryClient]);
}
