import {CollapsibleRail} from '../../components/CollapsibleRail';
import {DatabaseNode} from './DatabaseNode';
import {isConnectionUsable} from './query.types';
import type {Connection, GlueTableSummary} from './query.types';
import {connectionStatusLabel} from '../shared-spaces/connectionStatus';

/**
 * Per-table actions, wired in QueryWorkspace. Each carries the `database` of the
 * rail node the table was invoked from (SPEC-077 FR-007) — there is no active
 * database to source it from.
 */
export type TableActions = {
  onViewSourceFiles: (database: string, table: GlueTableSummary) => void;
  onViewDdl: (database: string, table: GlueTableSummary) => void;
  onViewData: (database: string, table: GlueTableSummary) => void;
  /** Base tables only — views can't be shared (SPEC-093), so their menu omits the item. */
  onShareTable: (database: string, table: GlueTableSummary) => void;
  onDropTable: (database: string, table: GlueTableSummary) => void;
  /** True when the table's S3 location is within the user's own space; View source files is disabled otherwise. */
  canViewSourceFiles: (table: GlueTableSummary) => boolean;
};

function DatabaseIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="h-[18px] w-[18px] flex-none"
      aria-hidden="true">
      <ellipse
        cx="12"
        cy="6"
        rx="8"
        ry="3"
      />
      <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
      <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </svg>
  );
}

// A provisioning/failed/leaving shared connection is shown but not expandable
// and not selectable — a static row with its status label.
function UnusableNode({connection}: {connection: Connection}) {
  return (
    <div className="flex items-center gap-2 rounded-md px-2 py-2 text-base font-semibold text-text-3">
      <span className="w-[13px] flex-none" />
      <DatabaseIcon />
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
 * `AppNavDrawer` contextual slot (SPEC-100 FR-005) — one source, no forked
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
 * panel narrows to 220px in the tablet band (SPEC-100 FR-002) and is hidden below
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
