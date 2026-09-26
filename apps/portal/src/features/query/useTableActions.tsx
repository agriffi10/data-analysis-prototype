import {useEffect, useMemo, useRef} from 'react';
import {useNavigate} from 'react-router';
import {getTableDdl} from '../catalog/athena.service';
import {parseS3Url} from '../../lib/s3Url';
import {spaceBuckets} from '../../lib/userSpace';
import {toUserText} from '../../lib/errorMessages';
import {splitSqlStatements} from './query.sql';
import {quoteIdentifierIfNeeded} from '../../lib/sql';
import {SchemaTree, type TableActions} from './SchemaBrowser';
import {useProvideNavRail} from '../../components/navRailContext';
import type {ToastApi} from '../../components/toastContext';
import type {Connection} from '../connections/connection.types';
import type {GlueTableSummary} from '../catalog/catalog.types';
import type {UseMobileQuerySurfaceResult} from './useMobileQuerySurface';
import type {UseTabRunsResult} from './useTabRuns';
import type {UseQueryTabsResult} from './useQueryTabs';
import {SECTION_CAPTION} from '../../components/fieldStyles';

type Params = {
  username: string;
  isMobile: boolean;
  connections: Connection[];
  toast: ToastApi;
  mobile: UseMobileQuerySurfaceResult;
  submitBatch: UseTabRunsResult['submitBatch'];
  /** Opens a tab, or returns null at the cap. */
  openTab: UseQueryTabsResult['openTab'];
  /** Called when `openTab` refused — the workspace shows the cap dialog. */
  onTabLimit: () => void;
  /** Returns focus to the editor after a tab opens. */
  focusEditor: () => void;
  onRefreshTable: (database: string, table: GlueTableSummary) => void;
  onShareTable: (database: string, table: string) => void;
  onDropTable: (target: {database: string; table: GlueTableSummary}) => void;
};

/**
 * The per-table rail actions — View source files, View DDL, View data,
 * Refresh, Share, Drop — plus the mobile nav-rail registration that has to be
 * fed the same handlers.
 *
 * each action takes the database from the rail node the table
 * was invoked from (a table under `db_a` acts on `db_a.<table>`); there is no
 * active-database selection to source it from.
 */
export function useTableActions({
  username,
  isMobile,
  connections,
  toast,
  mobile,
  submitBatch,
  openTab,
  onTabLimit,
  focusEditor,
  onRefreshTable,
  onShareTable,
  onDropTable
}: Params): TableActions {
  const navigate = useNavigate();

  // The space a database belongs to, or null when it is not one this user can reach.
  // `connections` is already this hook's input and carries both halves the deep link needs:
  // the id `?space=` takes ('personal' for the personal space, the space name for a shared
  // one) and the kind that says which bucket the space lives in.
  const spaceFor = (database: string): {id: string; bucket: string} | null => {
    const connection = connections.find((c) => c.database === database);
    if (!connection) return null;
    const buckets = spaceBuckets();
    const bucket = connection.kind === 'personal' ? buckets.user : buckets.shared;
    return bucket ? {id: connection.id, bucket} : null;
  };

  // The in-space S3 key (folder) backing a table, or null when it has no LOCATION — a view
  // — or that LOCATION is not inside the space being browsed.
  //
  // This used to require the key to start with the USERNAME, which is why the action was
  // dead for every shared-space table: their data sits under the space's own name in a
  // different bucket. The rule is now the browsed database rather than the signed-in user,
  // which is the same test for the personal space and a working one for a shared space.
  //
  // BOTH halves are checked and neither implies the other. A user can write
  // CREATE EXTERNAL TABLE ... LOCATION pointing at any bucket, so a link built from the
  // prefix alone would open THIS space's bucket at a path that is not the table's data.
  const tablePrefix = (database: string, table: GlueTableSummary): string | null => {
    const parsed = parseS3Url(table.location);
    const space = spaceFor(database);
    if (!parsed || !space) return null;
    const key = parsed.key.endsWith('/') ? parsed.key : `${parsed.key}/`;
    return parsed.bucket === space.bucket && key.startsWith(`${database}/`) ? key : null;
  };

  const actions: TableActions = {
    canViewSourceFiles: (database: string, table: GlueTableSummary) => tablePrefix(database, table) !== null,
    // Deep-link the file browser to the table's data folder. `space` is REQUIRED, not
    // decoration: an absent one resolves to the personal space, whose root refuses a shared
    // prefix, so a shared table's link would open the user's own files at their root.
    onViewSourceFiles: (database: string, table: GlueTableSummary) => {
      const key = tablePrefix(database, table);
      const space = spaceFor(database);
      if (!key || !space) return;
      navigate(`/files?space=${encodeURIComponent(space.id)}&prefix=${encodeURIComponent(key)}`);
    },
    // Hand the table to the Data Explorer. `space` and `db` are BOTH the
    // node's own database, which is exact rather than convenient — a shared space's database
    // IS its space id, and the personal database is the username, which `/explore` resolves
    // to the personal space by the precedence rule. The route re-resolves both against
    // the spaces this user can reach, so a stale link opens the picker rather than failing.
    onExploreData: (database: string, table: GlueTableSummary) => {
      const params = new URLSearchParams({space: database, db: database, table: table.name});
      navigate(`/explore?${params.toString()}`);
    },
    // SHOW CREATE TABLE against the node's database → a new, non-run "DDL: {table}" tab.
    onViewDdl: (database: string, table: GlueTableSummary) => {
      const loading = toast.push({variant: 'info', message: `Loading DDL for ${table.name}…`});
      void (async () => {
        const result = await getTableDdl({
          database,
          table: table.name,
          username,
          isView: table.tableType === 'VIRTUAL_VIEW'
        });
        if (!result.success) {
          toast.push({
            variant: 'danger',
            message: `Couldn’t load DDL for ${table.name}. ${toUserText(result.error)}`
          });
          return;
        }
        toast.dismiss(loading);
        // The drawer puts these actions on a phone too, where there is
        // no editor to open a tab into — show the DDL in the read-only view.
        if (isMobile) {
          mobile.viewSql(result.data, `DDL: ${table.name}`);
          return;
        }
        const id = openTab({label: `DDL: ${table.name}`, sql: result.data});
        if (id === null) onTabLimit();
        else focusEditor();
      })();
    },
    // Open a "{table}" tab pre-filled with an unbounded, fully-qualified SELECT *
    // + auto-run — the results pager (at the user's page size) walks the whole
    // table; the workgroup bytes-scanned cutoff is the cost guard.
    onViewData: (database: string, table: GlueTableSummary) => {
      // Quoted only where needed, so an ordinary name reads in the tab as the user would type it.
      const sql = `SELECT * FROM ${quoteIdentifierIfNeeded(database)}.${quoteIdentifierIfNeeded(table.name)}`;
      // on a phone the run goes to the mobile results view; opening a
      // tab there would run a query with nothing able to display it.
      if (isMobile) {
        mobile.runSql(sql, table.name);
        return;
      }
      const id = openTab({label: table.name, sql});
      if (id === null) {
        onTabLimit();
        return;
      }
      focusEditor();
      submitBatch(splitSqlStatements(sql), 'script-single', id); // auto-run into the just-opened tab
    },
    // Open the Refresh dialog for this rail table. Unlike Share, `open`
    // takes the whole summary — the request's space is derived from the table's own
    // `location`, the only thing in the workspace that knows where its files live.
    onRefreshTable: (database: string, table: GlueTableSummary) => onRefreshTable(database, table),
    // Open the Share dialog for this rail table (base tables only — the
    // menu omits the item for views); submission + toasts live in useTableShare.
    onShareTable: (database: string, table: GlueTableSummary) => onShareTable(database, table.name),
    // Confirm, then drop in the background (handled on confirm) — carries the node's db.
    onDropTable: (database: string, table: GlueTableSummary) => onDropTable({database, table})
  };

  // Below `tablet` the inline rail is gone, so the same tree is
  // fed into the mobile AppNavDrawer's contextual slot. The registered node must
  // keep a stable identity (useProvideNavRail registers it in an effect), so the
  // drawer's copy delegates through a ref to the current handlers rather than
  // closing over the per-render `actions` object.
  const actionsRef = useRef(actions);
  useEffect(() => {
    actionsRef.current = actions;
  });
  const railActions = useMemo<TableActions>(
    () => ({
      canViewSourceFiles: (database, table) => actionsRef.current.canViewSourceFiles(database, table),
      onViewSourceFiles: (database, table) => actionsRef.current.onViewSourceFiles(database, table),
      onViewDdl: (database, table) => actionsRef.current.onViewDdl(database, table),
      onViewData: (database, table) => actionsRef.current.onViewData(database, table),
      onExploreData: (database, table) => actionsRef.current.onExploreData(database, table),
      onRefreshTable: (database, table) => actionsRef.current.onRefreshTable(database, table),
      onShareTable: (database, table) => actionsRef.current.onShareTable(database, table),
      onDropTable: (database, table) => actionsRef.current.onDropTable(database, table)
    }),
    []
  );
  const navRail = useMemo(
    () =>
      isMobile ? (
        <div className="p-3">
          <p className={`px-3 pb-1 pt-1 ${SECTION_CAPTION}`}>Databases</p>
          <SchemaTree
            connections={connections}
            actions={railActions}
          />
        </div>
      ) : null,
    [isMobile, connections, railActions]
  );
  useProvideNavRail(navRail);

  return actions;
}
