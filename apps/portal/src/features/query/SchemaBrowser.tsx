import { useState } from 'react';
import { cx } from '../../lib/cx';
import { useSchema } from './useSchema';
import { TableActionsMenu } from './TableActionsMenu';
import type { GlueTableSummary } from './query.types';

// SPEC-044: per-table actions, wired in QueryWorkspace.
export type TableActions = {
  onViewSourceFiles: (table: GlueTableSummary) => void;
  onViewDdl: (table: GlueTableSummary) => void;
  onViewData: (table: GlueTableSummary) => void;
  onDropTable: (table: GlueTableSummary) => void;
  // True when the table's S3 location is within the user's own space (FR-002);
  // View source files is disabled otherwise.
  canViewSourceFiles: (table: GlueTableSummary) => boolean;
};

const railClass =
  'hidden w-[248px] flex-shrink-0 flex-col gap-1 overflow-y-auto border-r border-border bg-surface px-3 py-4 md:flex';
const labelClass =
  'px-3 pb-2 pt-3 text-xs font-semibold uppercase tracking-[.04em] text-text-3';

function DatabaseIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="h-[18px] w-[18px] flex-none"
      aria-hidden="true"
    >
      <ellipse cx="12" cy="6" rx="8" ry="3" />
      <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
      <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </svg>
  );
}

function Rail({
  database,
  children,
}: {
  database: string;
  children: React.ReactNode;
}) {
  return (
    <aside className={railClass} aria-label="Schema browser">
      <p className={labelClass}>Database</p>
      <div className="flex items-center gap-2 rounded-md bg-accent-soft px-3 py-2 text-base font-semibold text-accent-text">
        <DatabaseIcon />
        <span className="min-w-0 truncate">{database || '—'}</span>
      </div>
      {children}
    </aside>
  );
}

// SPEC-035 FR-007: lists the user's database + tables/columns. Clicking a table
// toggles its columns (chevron); clicking a column inserts its name into the
// editor at the cursor. Loading / empty / "setting up" (DB not provisioned yet,
// SPEC-033 backfill) / error states are all friendly, never a raw throw.
export function SchemaBrowser({
  database,
  onInsert,
  actions,
}: {
  database: string;
  onInsert: (name: string) => void;
  actions: TableActions;
}) {
  const { data, isPending, isError, error } = useSchema(database || null);
  const [openTables, setOpenTables] = useState<Set<string>>(new Set());

  const toggle = (name: string) =>
    setOpenTables((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  let body: React.ReactNode;
  if (!database || isPending) {
    body = (
      <p role="status" className="px-3 py-2 text-sm text-text-3">
        Loading schema&hellip;
      </p>
    );
  } else if (isError) {
    // getDatabase NotFound = the per-user DB isn't provisioned yet (SPEC-033
    // backfill window) — present it as "setting up", not an error.
    const message = (error as Error)?.message ?? '';
    body = /does not exist/i.test(message) ? (
      <p role="status" className="px-3 text-sm leading-relaxed text-text-3">
        Setting up your database&hellip; This is automatic right after sign-up. If
        it persists, contact an administrator.
      </p>
    ) : (
      <p role="alert" className="px-3 text-sm leading-relaxed text-danger">
        Couldn&rsquo;t load your schema. {message}
      </p>
    );
  } else if (data.tables.length === 0) {
    body = (
      <p className="px-3 text-sm leading-relaxed text-text-3">
        No tables yet. Create one with{' '}
        <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-text-2">
          CREATE EXTERNAL TABLE &hellip;
        </code>{' '}
        in the editor.
      </p>
    );
  } else {
    body = data.tables.map((table) => (
      <TableRow
        key={table.name}
        table={table}
        open={openTables.has(table.name)}
        onToggle={() => toggle(table.name)}
        onInsert={onInsert}
        actions={actions}
      />
    ));
  }

  return (
    <Rail database={database}>
      <p className={labelClass}>Tables</p>
      {body}
    </Rail>
  );
}

function TableRow({
  table,
  open,
  onToggle,
  onInsert,
  actions,
}: {
  table: GlueTableSummary;
  open: boolean;
  onToggle: () => void;
  onInsert: (name: string) => void;
  actions: TableActions;
}) {
  return (
    <div>
      <div className="group flex items-center gap-1 rounded-md pr-1 hover:bg-surface-2">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-text"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="h-[15px] w-[15px] flex-none text-text-3"
            aria-hidden="true"
          >
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <path d="M3 9h18M9 4v16" />
          </svg>
          <span className="min-w-0 truncate">{table.name}</span>
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className={cx(
              'ml-auto h-[13px] w-[13px] flex-none text-text-3 transition-transform',
              open && 'rotate-90',
            )}
            aria-hidden="true"
          >
            <path d="m9 6 6 6-6 6" />
          </svg>
        </button>
        <div className="opacity-0 group-hover:opacity-100 group-focus-within:opacity-100">
          <TableActionsMenu
            tableName={table.name}
            items={[
              {
                key: 'view-source',
                label: 'View source files',
                onSelect: () => actions.onViewSourceFiles(table),
                disabled: !actions.canViewSourceFiles(table),
              },
              {
                key: 'view-ddl',
                label: 'View DDL',
                onSelect: () => actions.onViewDdl(table),
              },
              {
                key: 'view-data',
                label: 'View data',
                onSelect: () => actions.onViewData(table),
              },
              {
                key: 'drop',
                label: 'Drop table',
                onSelect: () => actions.onDropTable(table),
                danger: true,
                separatorBefore: true,
              },
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
                className="flex items-baseline gap-2 rounded-sm px-2 py-[3px] text-left text-sm text-text-2 hover:bg-surface-2 hover:text-text"
              >
                <span className="min-w-0 truncate">{column.name}</span>
                <span className="ml-auto flex-none font-mono text-xs text-text-3">
                  {column.type}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
