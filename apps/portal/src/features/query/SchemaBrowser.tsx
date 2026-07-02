import {useRef} from 'react';
import {DatabaseNode} from './DatabaseNode';
import {isConnectionUsable} from './query.types';
import type {Connection, GlueTableSummary} from './query.types';
import {connectionStatusLabel} from '../shared-spaces/connectionStatus';

/** Per-table actions, wired in QueryWorkspace. */
export type TableActions = {
  onViewSourceFiles: (table: GlueTableSummary) => void;
  onViewDdl: (table: GlueTableSummary) => void;
  onViewData: (table: GlueTableSummary) => void;
  onDropTable: (table: GlueTableSummary) => void;
  /** True when the table's S3 location is within the user's own space; View source files is disabled otherwise. */
  canViewSourceFiles: (table: GlueTableSummary) => boolean;
};

const railClass =
  'hidden w-[248px] shrink-0 flex-col gap-1 overflow-y-auto border-r border-border bg-surface px-3 py-4 md:flex';
const labelClass = 'px-3 pb-2 pt-3 text-xs font-semibold uppercase tracking-[.04em] text-text-3';

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
 * The schema rail. Each accessible database is a collapsible node that, when
 * expanded, loads and groups its own Tables and Views (DatabaseNode).
 * Expanding to browse is decoupled from choosing the active query target: the
 * per-node radio (a `radiogroup` across the nodes) sets the workspace-global
 * active database without toggling expansion. Loading / empty / "setting up"
 * / error states render per node.
 */
export function SchemaBrowser({
  database,
  connections = [],
  onSelectDatabase,
  onInsert,
  actions
}: {
  /** The active database (drives the active highlight + run target). */
  database: string;
  /** Accessible databases (default: single personal). */
  connections?: Connection[];
  /** Switches the active database. */
  onSelectDatabase?: (database: string) => void;
  onInsert: (name: string) => void;
  actions: TableActions;
}) {
  const groupRef = useRef<HTMLDivElement>(null);

  const items: Connection[] =
    connections.length > 0 ? connections : [{id: 'personal', label: database || '—', database, kind: 'personal'}];
  const single = items.length <= 1;

  // Roving-focus arrow-key navigation across the active-target radios (APG
  // radiogroup). Selection stays explicit (Enter/Space), so arrows move focus
  // without changing the active database.
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!['ArrowDown', 'ArrowRight', 'ArrowUp', 'ArrowLeft'].includes(e.key)) return;
    const radios = Array.from(groupRef.current?.querySelectorAll<HTMLElement>('[role="radio"]') ?? []);
    if (radios.length === 0) return;
    e.preventDefault();
    const current = radios.findIndex((r) => r === document.activeElement);
    const forward = e.key === 'ArrowDown' || e.key === 'ArrowRight';
    const start = current === -1 ? 0 : current;
    const next = (start + (forward ? 1 : -1) + radios.length) % radios.length;
    radios[next]?.focus();
  };

  return (
    <aside
      className={railClass}
      aria-label="Schema browser">
      <p className={labelClass}>Database</p>
      <div
        ref={groupRef}
        role="radiogroup"
        aria-label="Active database"
        onKeyDown={onKeyDown}
        className="flex flex-col gap-0.5">
        {items.map((conn) =>
          isConnectionUsable(conn) ? (
            <DatabaseNode
              key={conn.id}
              connection={conn}
              isActive={conn.database === database}
              defaultExpanded={conn.database === database || single}
              onSetActive={(db) => onSelectDatabase?.(db)}
              onInsert={onInsert}
              actions={actions}
            />
          ) : (
            <UnusableNode
              key={conn.id}
              connection={conn}
            />
          )
        )}
      </div>
    </aside>
  );
}
