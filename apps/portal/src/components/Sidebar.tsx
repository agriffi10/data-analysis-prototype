import {cx} from '../lib/cx';
import {FolderIcon} from './icons';
import {isConnectionUsable} from '../features/query/query.types';
import type {Connection} from '../features/query/query.types';
import {connectionStatusLabel} from '../features/shared-spaces/connectionStatus';

type Props = {
  /**
   * The spaces the signed-in user can browse — personal first, then shared A–Z
   * (from `useConnections`). Empty in the dev-unauth path.
   */
  connections: Connection[];
  /** 'personal' | the active shared-space name. */
  activeSpaceId: string;
  onSelectSpace: (id: string) => void;
};

/**
 * Left navigation sidebar for the authenticated app shell — a 248px panel
 * listing the user's spaces: their personal space (labelled with the username)
 * plus each shared connection. Selecting one points the file browser at that
 * space; provisioning/failed connections are shown disabled with their status.
 * Hidden below the md breakpoint so the browser fills narrow viewports.
 *
 * @example
 * <Sidebar connections={connections} activeSpaceId={spaceId} onSelectSpace={setSpaceId} />
 */
export function Sidebar({connections, activeSpaceId, onSelectSpace}: Props) {
  return (
    <aside
      aria-label="Your spaces navigation"
      className="hidden w-[248px] shrink-0 flex-col gap-1 overflow-y-auto border-r border-border bg-surface px-3 py-4 md:flex">
      <p className="px-3 pb-2 pt-3 text-xs font-semibold uppercase tracking-[.04em] text-text-3">Spaces</p>
      <ul
        role="list"
        className="flex flex-col gap-0.5"
        aria-label="Spaces">
        {connections.map((conn) => {
          const active = conn.id === activeSpaceId;
          // Provisioning/failed/leaving shared connections appear but are not
          // selectable — disabled, with their status shown.
          const usable = isConnectionUsable(conn);
          return (
            <li key={conn.id}>
              <button
                type="button"
                disabled={!usable}
                aria-current={active ? 'true' : undefined}
                onClick={usable ? () => onSelectSpace(conn.id) : undefined}
                className={cx(
                  'flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-base font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                  !usable
                    ? 'cursor-not-allowed text-text-3'
                    : active
                      ? 'bg-accent-soft text-accent-text'
                      : 'text-text-2 hover:bg-surface-2 hover:text-text'
                )}>
                <FolderIcon className="h-[18px] w-[18px] flex-none" />
                <span className="min-w-0 truncate">{conn.label}</span>
                {active && <span className="sr-only">(current space)</span>}
                {conn.kind === 'personal' ? (
                  <span className="ml-auto flex-none text-xs text-text-3">user space</span>
                ) : (
                  conn.status &&
                  conn.status !== 'active' && (
                    <span className="ml-auto flex-none text-xs font-medium text-text-3">
                      {connectionStatusLabel(conn.status)}
                    </span>
                  )
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
