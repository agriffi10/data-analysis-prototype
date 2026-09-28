import {Fragment} from 'react';
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
  /** leaves the Query workspace for `/explore`, carrying the node's own database. */
  onExploreData: (database: string, table: GlueTableSummary) => void;
  /** Base tables only — a view has no folder to re-read, so their menu omits the item. */
  onRefreshTable: (database: string, table: GlueTableSummary) => void;
  /** Base tables only — views can't be shared, so their menu omits the item. */
  onShareTable: (database: string, table: GlueTableSummary) => void;
  onDropTable: (database: string, table: GlueTableSummary) => void;
  /**
   * True when the table's LOCATION sits inside the space being browsed — its own bucket AND
   * its own prefix. False for a view, which has no location, and for a table pointed at
   * somewhere else; View source files is disabled in both cases. Takes the database because
   * the space is the NODE's, not the signed-in user's: keying it to the username is what made
   * this dead for every shared space.
   */
  canViewSourceFiles: (database: string, table: GlueTableSummary) => boolean;
};

// A shared connection that is not usable (provisioning, failed, leaving, deleting)
// is shown but not expandable — a static row with its status label.
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

/** Labels a group of databases without nesting it: the nodes under it keep the rail's own indent. */
const GROUP_HEADING = 'px-2 pb-0.5 pt-2 text-xs font-semibold text-text-3';

/**
 * The database tree itself, decoupled from the rail chrome so it can render both
 * on-page inside `CollapsibleRail` (≥ tablet) and inside the mobile
 * `AppNavDrawer` contextual slot — one source, no forked
 * logic. Each accessible database is a collapsible node that, when expanded,
 * loads and groups its own Tables and Views (browse-only).
 *
 * The personal database sits under "My database" and the rest under "Shared spaces" — headings,
 * not a level of the tree. A group with nothing in it has no heading.
 *
 * @example
 * <SchemaTree connections={connections} actions={tableActions} />
 */
export function SchemaTree({connections = [], actions}: {connections?: Connection[]; actions: TableActions}) {
  const single = connections.length <= 1;
  const node = (conn: Connection) =>
    isConnectionUsable(conn) ? (
      <DatabaseNode
        key={conn.id}
        connection={conn}
        // First-reveal default: expand the first database (personal), or a
        // lone database, so there's something to see without a click.
        defaultExpanded={single || conn === connections[0]}
        actions={actions}
      />
    ) : (
      <UnusableNode
        key={conn.id}
        connection={conn}
      />
    );
  const groups = [
    {heading: 'My database', members: connections.filter((c) => c.kind === 'personal')},
    {heading: 'Shared spaces', members: connections.filter((c) => c.kind === 'shared')}
  ].filter((group) => group.members.length > 0);

  return (
    <div className="flex flex-col gap-0.5">
      {connections.length === 0 ? (
        <p className="px-3 py-2 text-sm text-text-3">No databases available.</p>
      ) : (
        groups.map((group) => (
          <Fragment key={group.heading}>
            <h2 className={GROUP_HEADING}>{group.heading}</h2>
            {group.members.map(node)}
          </Fragment>
        ))
      )}
    </div>
  );
}

/**
 * The schema rail (browse-only) — `SchemaTree` in the shared rail
 * chrome. There is no active-database selection; queries fully-qualify their own
 * tables. Loading / empty / "setting up" / error states render per node. The
 * panel narrows to 220px in the tablet band and is hidden below
 * it, where the drawer carries the tree instead.
 */
export function SchemaBrowser({
  connections = [],
  actions
}: {
  /** Every connection, personal first; a shared one that is not usable renders as a static row. */
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
