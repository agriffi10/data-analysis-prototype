import type {Member} from './sharedSpaces.types';

/**
 * The join status to SHOW for one member, which is not always the one stored.
 *
 * `Pending` means "added but hasn't opened the space in Files yet", and it is the OWNER's signal.
 * A reader looking at their own row sees `Active` whatever the cached projection says, because
 * the connections list one click away already shows the space as theirs and a `Pending` row under
 * their own name contradicted it. That is a display choice for the reader alone: the owner still
 * sees them `Pending` until they open the space in Files.
 * the acknowledge now fans the roster out (`cache.write_roster_to_all`) so every copy
 * converges — this closes the window between that sign-in and the fan-out landing, which is
 * exactly when a member is most likely to open the roster.
 *
 * Lives outside `MembersList.tsx` because a component file may export only components
 * (react-refresh), and because the roster's explanatory note has to ask this same question to
 * decide whether it describes anything on screen.
 *
 * @param member - The roster row.
 * @param viewer - The signed-in reader, when known.
 * @returns The status to render.
 */
export function displayedMemberStatus(member: Member, viewer?: string): Member['status'] {
  return member.username === viewer ? 'active' : member.status;
}
