import {useState} from 'react';
import {cx} from '../../lib/cx';
import {useSchema} from './useSchema';
import {TableActionsMenu} from './TableActionsMenu';
import {partitionSchema} from './schema.partition';
import type {Connection, GlueTableSummary} from './query.types';
import type {TableActions} from './SchemaBrowser';

// SPEC-063: a single database in the schema rail — a disclosure node that, when
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

// FR-005: each object row keeps its current behavior — expand to reveal columns,
// click a column to insert it, the per-row (view-aware) actions menu. The "View"
// badge is dropped inside the Views group (membership conveys the type, FR-005).
function TableRow({
  table,
  open,
  onToggle,
  onInsert,
  actions
}: {
  table: GlueTableSummary;
  open: boolean;
  onToggle: () => void;
  onInsert: (name: string) => void;
  actions: TableActions;
}) {
  const isView = table.tableType === 'VIRTUAL_VIEW';
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
                onSelect: () => actions.onViewSourceFiles(table),
                disabled: !actions.canViewSourceFiles(table)
              },
              {
                key: 'view-ddl',
                label: 'View DDL',
                onSelect: () => actions.onViewDdl(table)
              },
              {
                key: 'view-data',
                label: 'View data',
                onSelect: () => actions.onViewData(table)
              },
              {
                key: 'drop',
                label: isView ? 'Drop view' : 'Drop table',
                onSelect: () => actions.onDropTable(table),
                danger: true,
                separatorBefore: true
              }
            ]}
          />
        </div>
      </div>
      {open && (
        <div className="flex flex-col py-1 pl-8">
          {table.columns.length === 0 ? (
            <p className="px-2 py-1 text-xs text-text-3">No columns</p>
          ) : (
            table.columns.map((column) => (
              <button
                key={column.name}
                type="button"
                onClick={() => onInsert(column.name)}
                title={`Insert "${column.name}"`}
                aria-label={`Insert column ${column.name} into the query editor`}
                className="flex items-baseline gap-2 rounded-sm px-2 py-[3px] text-left text-sm text-text-2 hover:bg-surface-2 hover:text-text">
                <span className="min-w-0 truncate">{column.name}</span>
                <span className="ml-auto flex-none font-mono text-xs text-text-3">{column.type}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// FR-002: a Tables/Views sub-group — its own disclosure toggle + object count, and
// an empty state so the grouping stays legible rather than disappearing.
function ObjectGroup({
  title,
  objects,
  open,
  onToggle,
  emptyState,
  openTables,
  onToggleTable,
  onInsert,
  actions
}: {
  title: string;
  objects: GlueTableSummary[];
  open: boolean;
  onToggle: () => void;
  emptyState: React.ReactNode;
  openTables: Set<string>;
  onToggleTable: (name: string) => void;
  onInsert: (name: string) => void;
  actions: TableActions;
}) {
  return (
    <div className="pl-3">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs font-semibold uppercase tracking-[.04em] text-text-3 hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
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
                table={table}
                open={openTables.has(table.name)}
                onToggle={() => onToggleTable(table.name)}
                onInsert={onInsert}
                actions={actions}
              />
            ))}
          </div>
        ))}
    </div>
  );
}

export function DatabaseNode({
  connection,
  isActive,
  defaultExpanded,
  onSetActive,
  onInsert,
  actions
}: {
  connection: Connection;
  isActive: boolean;
  // First-reveal default for the node body; once the user toggles, their choice wins.
  defaultExpanded: boolean;
  onSetActive: (database: string) => void;
  onInsert: (name: string) => void;
  actions: TableActions;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  // Group expansion: Tables defaults open; Views defaults open iff there are views
  // (FR-002). `null` = "use the default"; an explicit toggle pins a boolean.
  const [tablesOpen, setTablesOpen] = useState<boolean | null>(null);
  const [viewsOpen, setViewsOpen] = useState<boolean | null>(null);
  const [openTables, setOpenTables] = useState<Set<string>>(new Set());

  // FR-004: a node fetches its schema only when expanded (disabled while collapsed).
  const {data, isPending, isError, error} = useSchema(expanded ? connection.database : null);

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
      // getDatabase NotFound = the per-user DB isn't provisioned yet (SPEC-033
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
          Couldn&rsquo;t load this schema. {message}
        </p>
      );
    } else {
      body = (
        <div className="flex flex-col gap-1 py-1">
          <ObjectGroup
            title="Tables"
            objects={tables}
            open={effectiveTablesOpen}
            onToggle={() => setTablesOpen(!effectiveTablesOpen)}
            openTables={openTables}
            onToggleTable={toggleTable}
            onInsert={onInsert}
            actions={actions}
            emptyState={
              <p className="px-3 py-1 text-sm leading-relaxed text-text-3">
                No tables yet. Create one with{' '}
                <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-text-2">
                  CREATE EXTERNAL TABLE &hellip;
                </code>{' '}
                in the editor.
              </p>
            }
          />
          <ObjectGroup
            title="Views"
            objects={views}
            open={effectiveViewsOpen}
            onToggle={() => setViewsOpen(!effectiveViewsOpen)}
            openTables={openTables}
            onToggleTable={toggleTable}
            onInsert={onInsert}
            actions={actions}
            emptyState={<p className="px-3 py-1 text-sm text-text-3">No views.</p>}
          />
        </div>
      );
    }
  }

  return (
    <div>
      <div className={cx('flex items-center gap-1 rounded-md', isActive ? 'bg-accent-soft' : 'hover:bg-surface-2')}>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-label={`${expanded ? 'Collapse' : 'Expand'} ${connection.label}`}
          className={cx(
            'flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-left text-base font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
            isActive ? 'text-accent-text' : 'text-text-2 hover:text-text'
          )}>
          <Chevron open={expanded} />
          <DatabaseIcon />
          <span className="min-w-0 truncate">{connection.label}</span>
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={isActive}
          tabIndex={isActive ? 0 : -1}
          onClick={() => onSetActive(connection.database)}
          aria-label={`Use ${connection.label} as the active database`}
          className="mr-1 flex-none rounded-full p-1 text-text-3 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <span
            className={cx(
              'block h-[14px] w-[14px] rounded-full border-2',
              isActive ? 'border-accent bg-accent' : 'border-border'
            )}
            aria-hidden="true"
          />
          {isActive && <span className="sr-only">(current database)</span>}
        </button>
      </div>
      {body}
    </div>
  );
}
