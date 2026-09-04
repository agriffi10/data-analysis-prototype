/**
 * The class strings for a control on the top bar — help, notifications, the theme.
 *
 * One owner rather than three copies. The three were separate before because they were three
 * icon buttons that happened to agree; they stopped agreeing the moment each grew a text label,
 * and an affordance a user reads as one row of controls must not drift into three.
 */

/**
 * An icon, optionally a label, in a hit target that clears the 24px floor without a label to
 * hold it open. `h-8` is 28px against this app's 14px root, and `px-1.5` puts the padding back
 * that the old `w-8` supplied — so an icon-only control is the same 28×28 box it always was.
 *
 * No `relative` here: the bell's unread badge is positioned against the span around its ICON, not
 * against the control, so that the badge follows the bell rather than the end of a label.
 */
export const HEADER_CONTROL =
  // A plain string, not `cx()`: there is nothing conditional to join, and `cx` is typed
  // `string | undefined` (it returns `undefined` rather than `''`), which would make every
  // reader of this constant handle an absence that cannot happen.
  'inline-flex h-8 items-center gap-1.5 rounded-md px-1.5 text-sm transition-colors ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent';

/** The control for the route you are on, or whose panel is open. */
export const HEADER_CONTROL_ACTIVE = 'bg-surface-2 text-accent-text';

/** Every other state. */
export const HEADER_CONTROL_IDLE = 'text-text-3 hover:bg-surface-2 hover:text-text';

/**
 * The label beside the icon.
 *
 * CSS-hidden below `tablet`, not mount-gated: it is not a control, so a phone loses the word
 * and keeps the button. The bar has no room for three of these at 375px — the fixed-width
 * chrome is already most of that width before any of them is drawn — and every one of the
 * three keeps an `aria-label` that names it, so nothing is lost to a screen reader either way.
 */
export const HEADER_CONTROL_LABEL = 'hidden tablet:inline';
