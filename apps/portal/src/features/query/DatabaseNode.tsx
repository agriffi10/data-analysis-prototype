import {useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {cx} from '../../lib/cx';
import {DatabaseRowIcon} from '../../components/icons';
import {RefreshIconButton} from '../../components/RefreshIconButton';
import {useSchema, invalidateSchema} from '../catalog/useSchema';
import {TableActionsMenu} from './TableActionsMenu';
import {partitionSchema} from './schema.partition';
import type {GlueTableSummary} from '../catalog/catalog.types';
import type {Connection} from '../connections/connection.types';
import type {TableActions} from './SchemaBrowser';
import {useFeature} from '../feature-flags';
import {SECTION_CAPTION} from '../../components/fieldStyles';

// a single database in the schema rail — a disclosure node that, when
// expanded, loads its own schema (`useSchema`, decoupled from the active target)
// and splits its objects into two collapsible groups: Tables and Views.

function Chevron({open, className}: {open: boolean; className?: string}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={cx('h-[13px] w-[13px] flex-none text-text-3 transition-transform', open && 'rotate-90', className)}
      aria-hidden="true">
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

// Each object row: expand to reveal its columns (inspection only — the rail is browse-only
// drops click-to-insert) and a per-row (view-aware) actions menu. The "View"
// badge is dropped inside the Views group (membership conveys the type).
function TableRow({
  database,
  table,
  open,
  onToggle,
  actions
}: {
  database: string;
  table: GlueTableSummary;
  open: boolean;
  onToggle: () => void;
  actions: TableActions;
}) {
  const isView = table.tableType === 'VIRTUAL_VIEW';
  // Belt to the `/query` route's braces. The flag already removes the route these
  // items live inside, so this can only matter if a later spec surfaces the table menu from
  // somewhere else — which is precisely the class of miss the registry exists to catch.
  const queryEnabled = useFeature('query');
  const explorerEnabled = useFeature('dataExplorer');
  return (
    <div>
      <div className="group flex items-center gap-1 rounded-md pr-1 hover:bg-surface-2">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-text">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="h-[15px] w-[15px] flex-none text-text-3"
            aria-hidden="true">
            <rect
              x="3"
              y="4"
              width="18"
              height="16"
              rx="2"
            />
            <path d="M3 9h18M9 4v16" />
          </svg>
          <span className="min-w-0 truncate">{table.name}</span>
          <Chevron
            open={open}
            className="ml-auto"
          />
        </button>
        <div className="opacity-0 group-hover:opacity-100 group-focus-within:opacity-100">
          <TableActionsMenu
            tableName={table.name}
            items={[
              {
                key: 'view-source',
                label: 'View source files',
                onSelect: () => actions.onViewSourceFiles(database, table),
                disabled: !actions.canViewSourceFiles(table)
              },
              {
                key: 'view-ddl',
                label: 'View DDL',
                onSelect: () => actions.onViewDdl(database, table)
              },
              {
                key: 'view-data',
                label: 'View data',
                onSelect: () => actions.onViewData(database, table)
              },
              // Base tables AND views — a view is a perfectly good thing to
              // explore. Gated by BOTH flags, which is what makes it the mirror image of
              // "Create table": the capability is the Data Explorer's, the surface is the
              // Query workspace's, and either flag being off must remove it.
              ...(explorerEnabled && queryEnabled
                ? [
                    {
                      key: 'explore-data',
                      label: 'Explore data',
                      onSelect: () => actions.onExploreData(database, table)
                    }
                  ]
                : []),
              // Base tables only — a view has no folder to re-read. The
              // browser runs NO other eligibility check: The rules (a
              // reconstructable partition scheme, a location inside the space) are
              // the server's to enforce, and its refusals come back as user-facing
              // notifications. A client-side gate here would only drift from them.
              // Disabled without a location because the request can't be built.
              ...(isView || !queryEnabled
                ? []
                : [
                    {
                      key: 'refresh',
                      label: 'Refresh table',
                      onSelect: () => actions.onRefreshTable(database, table),
                      disabled: !table.location
                    }
                  ]),
              // Base tables only — the server rejects views, so no item.
              ...(isView || !queryEnabled
                ? []
                : [
                    {
                      key: 'share',
                      label: 'Share table',
                      onSelect: () => actions.onShareTable(database, table)
                    }
                  ]),
              {
                key: 'drop',
                label: isView ? 'Drop view' : 'Drop table',
                onSelect: () => actions.onDropTable(database, table),
                danger: true,
                separatorBefore: true
              }
            ]}
          />
        </div>
      </div>
      {open && (
        <ul className="flex flex-col py-1 pl-8">
          {table.columns.length === 0 ? (
            <li className="px-2 py-1 text-xs text-text-3">No columns</li>
          ) : (
            // Columns are shown for inspection only — no click-to-insert.
            table.columns.map((column) => (
              <li
                key={column.name}
                className="flex items-baseline gap-2 px-2 py-[3px] text-sm text-text-2">
                <span className="min-w-0 truncate">{column.name}</span>
                <span className="ml-auto flex-none font-mono text-xs text-text-3">{column.type}</span>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

// a Tables/Views sub-group — its own disclosure toggle + object count, and
// an empty state so the grouping stays legible rather than disappearing.
function ObjectGroup({
  database,
  title,
  objects,
  open,
  onToggle,
  emptyState,
  openTables,
  onToggleTable,
  actions
}: {
  database: string;
  title: string;
  objects: GlueTableSummary[];
  open: boolean;
  onToggle: () => void;
  emptyState: React.ReactNode;
  openTables: Set<string>;
  onToggleTable: (name: string) => void;
  actions: TableActions;
}) {
  return (
    <div className="pl-3">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left ${SECTION_CAPTION} hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent`}>
        <Chevron open={open} />
        <span>
          {title} ({objects.length})
        </span>
      </button>
      {open &&
        (objects.length === 0 ? (
          emptyState
        ) : (
          <div className="flex flex-col">
            {objects.map((table) => (
              <TableRow
                key={table.name}
                database={database}
                table={table}
                open={openTables.has(table.name)}
                onToggle={() => onToggleTable(table.name)}
                actions={actions}
              />
            ))}
          </div>
        ))}
    </div>
  );
}

/**
 * One connection's database in the query rail: an expandable header, then a table list grouped
 * by tables and views, each table carrying its own actions menu. Loads the schema on demand and
 * renders the not-yet-provisioned and failed states in place.
 *
 * @example
 * <DatabaseNode connection={connection} defaultExpanded actions={actions} />
 */
export function DatabaseNode({
  connection,
  defaultExpanded,
  actions
}: {
  connection: Connection;
  // First-reveal default for the node body; once the user toggles, their choice wins.
  defaultExpanded: boolean;
  actions: TableActions;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  // Group expansion: Tables defaults open; Views defaults open iff there are views
  // `null` = "use the default"; an explicit toggle pins a boolean.
  const [tablesOpen, setTablesOpen] = useState<boolean | null>(null);
  const [viewsOpen, setViewsOpen] = useState<boolean | null>(null);
  const [openTables, setOpenTables] = useState<Set<string>>(new Set());

  // a node fetches its schema only when expanded (disabled while collapsed).
  const {data, isPending, isError, error, isFetching} = useSchema(expanded ? connection.database : null);

  // re-read only THIS database's schema on demand (invalidate its query key;
  // the expanded node is an active observer so it refetches). `isFetching` drives the
  // button's disabled/spinner state and blocks overlapping refetches for this node.
  const queryClient = useQueryClient();

  const toggleTable = (name: string) =>
    setOpenTables((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  const {tables, views} = partitionSchema(data?.tables ?? []);
  const effectiveTablesOpen = tablesOpen ?? true;
  const effectiveViewsOpen = viewsOpen ?? views.length > 0;

  let body: React.ReactNode = null;
  if (expanded) {
    if (isPending) {
      body = (
        <p
          role="status"
          className="px-3 py-2 text-sm text-text-3">
          Loading schema&hellip;
        </p>
      );
    } else if (isError) {
      // getDatabase NotFound = the per-user DB isn't provisioned yet (the post-confirmation Lambda creates it
      // backfill window) — present it as "setting up", not an error.
      const message = (error as Error)?.message ?? '';
      body = /does not exist/i.test(message) ? (
        <p
          role="status"
          className="px-3 py-2 text-sm leading-relaxed text-text-3">
          Setting up your database&hellip; This is automatic right after sign-up. If it persists, contact an
          administrator.
        </p>
      ) : (
        <p
          role="alert"
          className="px-3 py-2 text-sm leading-relaxed text-danger">
          Couldn&rsquo;t load this schema. Try Refresh, or contact the Administrator.
        </p>
      );
    } else {
      body = (
        <div className="flex flex-col gap-1 py-1">
          <ObjectGroup
            database={connection.database}
            title="Tables"
            objects={tables}
            open={effectiveTablesOpen}
            onToggle={() => setTablesOpen(!effectiveTablesOpen)}
            openTables={openTables}
            onToggleTable={toggleTable}
            actions={actions}
            emptyState={<p className="px-3 py-1 text-sm text-text-3">No tables.</p>}
          />
          <ObjectGroup
            database={connection.database}
            title="Views"
            objects={views}
            open={effectiveViewsOpen}
            onToggle={() => setViewsOpen(!effectiveViewsOpen)}
            openTables={openTables}
            onToggleTable={toggleTable}
            actions={actions}
            emptyState={<p className="px-3 py-1 text-sm text-text-3">No views.</p>}
          />
        </div>
      );
    }
  }

  return (
    <div>
      <div className="group flex items-center gap-1 rounded-md pr-1 hover:bg-surface-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-label={`${expanded ? 'Collapse' : 'Expand'} ${connection.label}`}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-left text-base font-semibold text-text-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <Chevron open={expanded} />
          <DatabaseRowIcon />
          <span className="min-w-0 truncate">{connection.label}</span>
        </button>
        {/* per-node refresh — only on an expanded (loaded) node; re-reads
            just this database's tables/views, never toggling expansion:
            it shares the app's one refresh glyph now, where it used to draw its own
            two-path variant — a deliberate (small) visual change. */}
        {expanded && (
          <RefreshIconButton
            label={`Refresh tables in ${connection.label}`}
            busy={isFetching}
            onClick={() => void invalidateSchema(queryClient, connection.database)}
          />
        )}
      </div>
      {body}
    </div>
  );
}
