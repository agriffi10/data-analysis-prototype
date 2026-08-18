import {Banner} from '../../components/Banner';
import {Drawer} from '../../components/Drawer';
import {MembersList} from './MembersList';
import {displayedMemberStatus} from './memberStatus';
import {RefreshConnectionsButton} from './RefreshConnectionsButton';
import type {Member} from './sharedSpaces.types';

type Props = {
  open: boolean;
  onClose: () => void;
  space: string;
  owner: string;
  /** The full roster (owner + members, with join status). */
  members: Member[];
  /** True when the member's cache predates the roster and has none yet. */
  unavailable?: boolean;
  /** The signed-in reader, so their own row can't read `Pending` at them. */
  viewer?: string;
  /** Re-read connection state on demand (the roster is eventually consistent). */
  onRefresh: () => void;
  refreshing?: boolean;
};

/**
 * Read-only member roster: a non-owner member can see who else belongs to
 * a shared space, presented like the owner's Manage drawer (owner tagged + first, join
 * status per member) but with no Add/Remove controls. Legacy cache entries with no
 * roster show a non-blocking "not available yet" note.
 *
 * @example
 * <MemberRosterDrawer open space="sales" owner="alice" members={members} onClose={close} onRefresh={refresh} />
 */
export function MemberRosterDrawer({
  open,
  onClose,
  space,
  owner,
  members,
  unavailable = false,
  viewer,
  onRefresh,
  refreshing = false
}: Props) {
  // The sentence explains a chip; rendering it where no such chip exists is
  // how it came to be read by the one person for whom it was false — a member who HAD signed in,
  // told that Pending means they had not.
  const anyPending = members.some((m) => m.username !== owner && displayedMemberStatus(m, viewer) === 'pending');

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={space}
      titleClassName="font-mono"
      subtitle="Members · everyone shares the same files and tables"
      ariaLabel="View members"
      closeLabel="Close members"
      mobileVariant="full-height"
      headerAccessory={
        <div className="ml-2 flex flex-none items-center gap-1.5">
          <RefreshConnectionsButton
            refreshing={refreshing}
            onRefresh={onRefresh}
          />
        </div>
      }>
      {unavailable ? (
        <Banner variant="info">
          The member list isn&apos;t available yet — it loads after the next membership change on this space. Use
          Refresh connections to check again.
        </Banner>
      ) : (
        <>
          <MembersList
            owner={owner}
            members={members}
            viewer={viewer}
          />
          {anyPending && (
            <p className="text-xs text-text-3">
              A <span className="font-medium text-text-2">Pending</span> member has been invited but hasn&apos;t signed
              in yet; they become <span className="font-medium text-text-2">Active</span> once they do.
            </p>
          )}
        </>
      )}
    </Drawer>
  );
}
