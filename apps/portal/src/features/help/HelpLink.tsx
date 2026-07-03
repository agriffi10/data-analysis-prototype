import {NavLink} from 'react-router-dom';
import {HelpCircleIcon} from '../../components/icons';
import {cx} from '../../lib/cx';

/**
 * Header help control — a link to `/help`, styled like the notifications bell
 * (32px hit target, 20px icon, active/current treatment on `/help`). Sits left
 * of the bell in the authenticated user-zone (SPEC-074 FR-001).
 *
 * @example
 * <HelpLink />
 */
export function HelpLink() {
  return (
    <NavLink
      to="/help"
      aria-label="Help & guides"
      className={({isActive}) =>
        cx(
          'relative inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
          isActive ? 'bg-surface-2 text-accent-text' : 'text-text-3 hover:bg-surface-2 hover:text-text'
        )
      }>
      <HelpCircleIcon className="h-5 w-5" />
    </NavLink>
  );
}
