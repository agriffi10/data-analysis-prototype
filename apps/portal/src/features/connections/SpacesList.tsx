import {cx} from '../../lib/cx';
import {FolderIcon} from '../../components/icons';
import {isConnectionUsable} from './connection.types';
import type {Connection} from './connection.types';
import {connectionStatusLabel} from './connectionStatus';

export type SpacesListProps = {
  /** Personal first, then shared A–Z (from `useConnections`). Empty in dev-unauth. */
  connections: Connection[];
  /** 'personal' | the active shared-space name. */
  activeSpaceId: string;
  onSelectSpace: (id: string) => void;
};

/**
 * The spaces list itself (personal + shared connections), decoupled from the
 * rail chrome so it can render both on-page inside `Sidebar`/`CollapsibleRail`
 * (≥ tablet) and inside the mobile `AppNavDrawer` contextual slot.
 * Selecting a space points the file browser at it; provisioning/failed
 * connections show disabled with their status.
 *
 * @example
 * <SpacesList connections={connections} activeSpaceId={spaceId} onSelectSpace={setSpaceId} />
 */
export function SpacesList({connections, activeSpaceId, onSelectSpace}: SpacesListProps) {
  return (
    <ul
      role="list"
      className="flex flex-col gap-0.5"
      aria-label="Spaces">
      {connections.map((conn) => {
        const active = conn.id === activeSpaceId;
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
  );
}
