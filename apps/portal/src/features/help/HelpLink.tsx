import {NavLink} from '../../lib/navigation';
import {
  HEADER_CONTROL,
  HEADER_CONTROL_ACTIVE,
  HEADER_CONTROL_IDLE,
  HEADER_CONTROL_LABEL
} from '../../components/headerControl';
import {HelpCircleIcon} from '../../components/icons';
import {cx} from '../../lib/cx';
import {HelpPanel} from './HelpPanel';
import {useContextualHelp} from './useContextualHelp';

/**
 * Header help control — an icon and the word `Help`, styled like the notifications bell and
 * the theme control beside it, in the authenticated user-zone.
 *
 * It does one of two things. On a route the guide panel covers it opens that panel over the
 * page, so nothing half-finished is lost; anywhere else it stays the link to `/help` it has
 * always been. The accessible name says which, so a screen-reader user is not told a button
 * is a link to a page — and the visible word is a prefix of both, which is what SC 2.5.3 asks
 * of a control whose name says more than its label.
 *
 * @example
 * <HelpLink />
 */
export function HelpLink() {
  const {sectionId, open, openPanel, closePanel} = useContextualHelp();
  const label = <span className={HEADER_CONTROL_LABEL}>Help</span>;

  if (sectionId === null) {
    return (
      <NavLink
        to="/help"
        aria-label="Help & guides"
        className={({isActive}) => cx(HEADER_CONTROL, isActive ? HEADER_CONTROL_ACTIVE : HEADER_CONTROL_IDLE)}>
        <HelpCircleIcon className="h-5 w-5 flex-none" />
        {label}
      </NavLink>
    );
  }

  return (
    <>
      <button
        type="button"
        aria-label="Help for this page"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={openPanel}
        className={cx(HEADER_CONTROL, open ? HEADER_CONTROL_ACTIVE : HEADER_CONTROL_IDLE)}>
        <HelpCircleIcon className="h-5 w-5 flex-none" />
        {label}
      </button>
      <HelpPanel
        sectionId={sectionId}
        open={open}
        onClose={closePanel}
      />
    </>
  );
}
