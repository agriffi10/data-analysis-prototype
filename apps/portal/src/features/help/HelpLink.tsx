import {NavLink} from 'react-router';
import {HelpCircleIcon} from '../../components/icons';
import {cx} from '../../lib/cx';
import {HelpPanel} from './HelpPanel';
import {useContextualHelp} from './useContextualHelp';

// One set of classes for both behaviours: the affordance a user sees must not change with
// what activating it does.
const CONTROL = cx(
  'relative inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent'
);
const ACTIVE = 'bg-surface-2 text-accent-text';
const IDLE = 'text-text-3 hover:bg-surface-2 hover:text-text';

/**
 * Header help control — styled like the notifications bell (32px hit target, 20px icon),
 * sitting left of it in the authenticated user-zone.
 *
 * It does one of two things. On a route the guide panel covers it opens that panel over the
 * page, so nothing half-finished is lost; anywhere else it stays the link to `/help` it has
 * always been. The accessible name says which, so a screen-reader user is not told a button
 * is a link to a page.
 *
 * @example
 * <HelpLink />
 */
export function HelpLink() {
  const {sectionId, open, openPanel, closePanel} = useContextualHelp();

  if (sectionId === null) {
    return (
      <NavLink
        to="/help"
        aria-label="Help & guides"
        className={({isActive}) => cx(CONTROL, isActive ? ACTIVE : IDLE)}>
        <HelpCircleIcon className="h-5 w-5" />
      </NavLink>
    );
  }

  return (
    <>
      <button
        type="button"
        aria-label="Help for this page"
        aria-expanded={open}
        onClick={openPanel}
        className={cx(CONTROL, open ? ACTIVE : IDLE)}>
        <HelpCircleIcon className="h-5 w-5" />
      </button>
      <HelpPanel
        sectionId={sectionId}
        open={open}
        onClose={closePanel}
      />
    </>
  );
}
