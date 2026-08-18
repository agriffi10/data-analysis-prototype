import {CollapsibleRail} from '../../components/CollapsibleRail';
import {DatabaseRowIcon} from '../../components/icons';
import {DatabaseNode} from './DatabaseNode';
import type {GlueTableSummary} from '../catalog/catalog.types';
import {isConnectionUsable} from '../connections/connection.types';
import type {Connection} from '../connections/connection.types';
import {connectionStatusLabel} from '../connections/connectionStatus';

/**
 * Per-table actions, wired in QueryWorkspace. Each carries the `database` of the
 * rail node the table was invoked from — there is no active
 * database to source it from.
 */
export type TableActions = {
  onViewSourceFiles: (database: string, table: GlueTableSummary) => void;
  onViewDdl: (database: string, table: GlueTableSummary) => void;
  onViewData: (database: string, table: GlueTableSummary) => void;
  /** SPEC-179: leaves the Query workspace for `/explore`, carrying the node's own database. */
  onExploreData: (database: string, table: GlueTableSummary) => void;
  /** Base tables only — a view has no folder to re-read, so their menu omits the item. */
  onRefreshTable: (database: string, table: GlueTableSummary) => void;
  /** Base tables only — views can't be shared, so their menu omits the item. */
  onShareTable: (database: string, table: GlueTableSummary) => void;
  onDropTable: (database: string, table: GlueTableSummary) => void;
  /** True when the table's S3 location is within the user's own space; View source files is disabled otherwise. */
  canViewSourceFiles: (table: GlueTableSummary) => boolean;
};

// A provisioning/failed/leaving shared connection is shown but not expandable
// and not selectable — a static row with its status label.
function UnusableNode({connection}: {connection: Connection}) {
  return (
    <div className="flex items-center gap-2 rounded-md px-2 py-2 text-base font-semibold text-text-3">
      <span className="w-[13px] flex-none" />
      <DatabaseRowIcon />
      <span className="min-w-0 truncate">{connection.label}</span>
      {connection.status && (
        <span className="ml-auto flex-none text-xs font-medium text-text-3">
          {connectionStatusLabel(connection.status)}
        </span>
      )}
    </div>
  );
}

/**
 * The database tree itself, decoupled from the rail chrome so it can render both
 * on-page inside `CollapsibleRail` (≥ tablet) and inside the mobile
 * `AppNavDrawer` contextual slot — one source, no forked
 * logic. Each accessible database is a collapsible node that, when expanded,
 * loads and groups its own Tables and Views (SPEC-077: browse-only).
 *
 * @example
 * <SchemaTree connections={connections} actions={tableActions} />
 */
export function SchemaTree({connections = [], actions}: {connections?: Connection[]; actions: TableActions}) {
  const single = connections.length <= 1;

  return (
    <div className="flex flex-col gap-0.5">
      {connections.length === 0 ? (
        <p className="px-3 py-2 text-sm text-text-3">No databases available.</p>
      ) : (
        connections.map((conn, i) =>
          isConnectionUsable(conn) ? (
            <DatabaseNode
              key={conn.id}
              connection={conn}
              // First-reveal default: expand the first database (personal), or a
              // lone database, so there's something to see without a click.
              defaultExpanded={single || i === 0}
              actions={actions}
            />
          ) : (
            <UnusableNode
              key={conn.id}
              connection={conn}
            />
          )
        )
      )}
    </div>
  );
}

/**
 * The schema rail (SPEC-077: browse-only) — `SchemaTree` in the shared rail
 * chrome. There is no active-database selection; queries fully-qualify their own
 * tables. Loading / empty / "setting up" / error states render per node. The
 * panel narrows to 220px in the tablet band and is hidden below
 * it, where the drawer carries the tree instead.
 */
export function SchemaBrowser({
  connections = [],
  actions
}: {
  /** Accessible databases (personal + usable shared connections). */
  connections?: Connection[];
  actions: TableActions;
}) {
  return (
    <CollapsibleRail
      ariaLabel="Schema browser"
      title="Databases"
      widthClass="w-[220px] desktop:w-[248px]">
      <SchemaTree
        connections={connections}
        actions={actions}
      />
    </CollapsibleRail>
  );
}
