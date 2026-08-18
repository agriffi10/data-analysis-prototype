import {CollapsibleRail} from '../../components/CollapsibleRail';
import {SpacesList} from './SpacesList';
import type {Connection} from './connection.types';

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
 * listing the user's spaces (the shared `SpacesList`) inside `CollapsibleRail`.
 * Hidden below the `tablet` breakpoint so the browser fills narrow viewports;
 * on mobile the same `SpacesList` is fed into the `AppNavDrawer`.
 *
 * @example
 * <Sidebar connections={connections} activeSpaceId={spaceId} onSelectSpace={setSpaceId} />
 */
export function Sidebar({connections, activeSpaceId, onSelectSpace}: Props) {
  return (
    <CollapsibleRail
      ariaLabel="Your spaces navigation"
      title="Spaces">
      <SpacesList
        connections={connections}
        activeSpaceId={activeSpaceId}
        onSelectSpace={onSelectSpace}
      />
    </CollapsibleRail>
  );
}
