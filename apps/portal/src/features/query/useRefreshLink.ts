import {useCallback, useMemo} from 'react';
import {useLocation, useSearchParams} from '../../lib/navigation';
import {useSchema} from '../catalog/useSchema';
import {parseRefreshLink, useTableRefresh} from '../table-builder';
import {isConnectionUsable, type Connection} from '../connections/connection.types';

type RefreshTarget = NonNullable<Parameters<typeof useTableRefresh>[1]>['target'];

export type UseRefreshLinkResult = {
  /** What the link names, once the rail confirms the table exists; null while unresolved or unreachable. */
  target: RefreshTarget;
  /** Retire the link's parameters from the URL, replacing the history entry. */
  clear: () => void;
};

/**
 * The `/query?refreshTable={db}.{table}&removed={names}` link a `columns_removed`
 * notification carries, resolved against the rail.
 *
 * Read from the RAW query string (`location.search`), never through `useSearchParams`:
 * that decodes, and the names are individually percent-encoded around a comma
 * separator, so a column named `a,b` would arrive already split. The dialog that opens
 * on it is DERIVED from the URL rather than opened from an effect — acting on it retires
 * the parameters, which is what closes it. A database the user cannot reach resolves to
 * null and is never fetched: no existence oracle, and the rail is the authority on what
 * exists.
 *
 * @example
 * const refreshLink = useRefreshLink(connections, connectionsLoading);
 * const refresh = useTableRefresh(toast.push, {target: refreshLink.target, onConsumed: refreshLink.clear});
 */
export function useRefreshLink(connections: Connection[], connectionsLoading: boolean): UseRefreshLinkResult {
  const location = useLocation();
  const [, setSearchParams] = useSearchParams();
  const link = useMemo(() => parseRefreshLink(location.search), [location.search]);
  const linkDatabase =
    link && !connectionsLoading && connections.some((c) => c.database === link.database && isConnectionUsable(c))
      ? link.database
      : null;
  const {data: linkSchema} = useSchema(linkDatabase);
  const target = useMemo(() => {
    if (!link || !linkSchema) return null;
    // A view has no folder to re-read and a table with no location can't be turned
    // into a request (the menu item is disabled for the same reason), so a link
    // naming either opens nothing.
    const table = linkSchema.tables.find(
      (t) => t.name === link.tableName && t.tableType !== 'VIRTUAL_VIEW' && !!t.location
    );
    if (!table) return null;
    // A link carrying no names is NOT the link-borne state. That state gates confirm
    // behind the removals opt-in, which is only an informed choice when the columns
    // are named — with an empty list it would coerce a blind `allowRemovals: true`.
    // The notifier mints no link without names; a URL that has one was edited.
    return {database: link.database, table, pending: link.columns.length > 0 ? link : null};
  }, [link, linkSchema]);
  const clear = useCallback(
    () =>
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('refreshTable');
          next.delete('removed');
          return next;
        },
        {replace: true}
      ),
    [setSearchParams]
  );
  return {target, clear};
}
