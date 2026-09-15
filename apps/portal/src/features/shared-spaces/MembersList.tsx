import {Badge} from '../../components/Badge';
import {Button} from '../../components/Button';
import {StatusPill} from '../../components/StatusPill';
import {displayedMemberStatus} from './memberStatus';
import type {Member} from './sharedSpaces.types';

type MembersListProps = {
  /** The space owner's username — rendered first with an "Owner" tag, never removable. */
  owner: string;
  /** The full roster (with join status), including the owner. */
  members: Member[];
  /**
   * When provided, each non-owner member shows a Remove button (owner's Manage view).
   * Omit for the read-only member roster.
   */
  onRemove?: (username: string) => void;
  /**
   * When provided, each non-owner member shows a Transfer-ownership button. Passed only by the
   * owner's Manage view, so the read-only roster gets none by construction rather than by a
   * flag someone has to remember to set false.
   */
  onTransfer?: (username: string) => void;
  busy?: boolean;
  /**
   * The signed-in user reading this list, when known.
   *
   * Their own row renders `Active` whatever the projection says, because `Pending` means
   * "invited but hasn't signed in yet" and this reader demonstrably has — they are looking at
   * the page. The acknowledge now fans the roster out (`cache.write_roster_to_all`), so
   * every copy converges; this closes the window between that sign-in and the fan-out landing,
   * which is exactly the moment a member is most likely to open the roster.
   */
  viewer?: string;
};

/**
 * Shared presentational roster: the owner first (tagged, never removable), then the
 * other members A–Z, each with a join-status chip. Read-only by default; pass
 * `onRemove` and/or `onTransfer` to expose the per-member owner controls (the owner's Manage
 * drawer). Used by both `ManageMembersDrawer` (read-write) and `MemberRosterDrawer` (read-only).
 *
 * @example
 * <MembersList owner="alice" members={members} />                 // read-only
 * <MembersList owner="alice" members={members} onRemove={remove} onTransfer={hand} /> // owner
 */
export function MembersList({owner, members, onRemove, onTransfer, busy = false, viewer}: MembersListProps) {
  const others = members.filter((m) => m.username !== owner).sort((a, b) => a.username.localeCompare(b.username));

  return (
    <ul
      role="list"
      className="divide-y divide-border rounded-lg border border-border">
      <li className="flex items-center gap-3 px-4 py-2.5">
        <Avatar name={owner} />
        <span className="min-w-0 truncate font-medium text-text">{owner}</span>
        <Badge className="flex-none">Owner</Badge>
        <div className="flex-1" />
      </li>
      {others.map((member) => (
        <li
          key={member.username}
          className="flex items-center gap-3 px-4 py-2.5">
          <Avatar name={member.username} />
          <span className="min-w-0 truncate font-medium text-text">{member.username}</span>
          <MemberStatusBadge status={displayedMemberStatus(member, viewer)} />
          <div className="flex-1" />
          {onTransfer && (
            <Button
              variant="ghost"
              size="sm"
              // Named for the same reason Remove is: the visible text repeats on every row, so
              // a screen-reader user hearing the list of controls would get N identical buttons
              // with no way to tell which member each one hands the space to. The name leads
              // with the visible text so a voice-control user can say what they see.
              aria-label={`Make owner: ${member.username}`}
              onClick={() => onTransfer(member.username)}
              disabled={busy}>
              Make owner
            </Button>
          )}
          {onRemove && (
            <Button
              variant="dangerOutline"
              size="sm"
              // The visible text is "Remove" on every row, so a screen-reader user hearing the
              // list of controls gets N identical buttons with no way to tell which member each
              // one acts on. Naming the member is the accessible fix and it is also what makes
              // the removal journey testable by a stable query (the journey test's
              // additive-accessibility exception). Appearance is unchanged — `aria-label`
              // overrides the accessible name only, not the rendered text.
              aria-label={`Remove ${member.username}`}
              onClick={() => onRemove(member.username)}
              disabled={busy}>
              Remove
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

// Per-member join status, through the shared pill: the text label
// always carries the meaning, so the colour and dot are never the only signal (WCAG AA).
function MemberStatusBadge({status}: {status: Member['status']}) {
  const active = status === 'active';
  return <StatusPill tone={active ? 'success' : 'warning'}>{active ? 'Active' : 'Pending'}</StatusPill>;
}

// Circular avatar showing the first two letters of the username. Decorative — the
// username text beside it carries the name.
function Avatar({name}: {name: string}) {
  return (
    <span
      aria-hidden="true"
      className="grid h-7 w-7 flex-none place-items-center rounded-full bg-gradient-to-br from-accent to-accent-hover text-xs font-semibold text-white">
      {name.slice(0, 2).toUpperCase()}
    </span>
  );
}
