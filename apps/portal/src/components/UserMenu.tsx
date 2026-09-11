import {Menu, type MenuItem} from './Menu';
import {FeedbackIcon, KebabIcon, SignOutIcon} from './icons';

export type UserMenuProps = {
  /** The signed-in user, shown on the trigger and named in its accessible label. */
  username: string;
  onGiveFeedback: () => void;
  onSignOut: () => void;
};

/**
 * The account menu behind the kebab beside the avatar: Give feedback, and Sign out last.
 *
 * PRESENTATIONAL BY REQUIREMENT, not by taste. `components/` may not import `features/`
 * (`eslint.config.js`), and its exemption list is two files long — so feedback and sign out
 * arrive as callbacks and `Header`, which is exempt, does the wiring.
 *
 * WHAT IT DELIBERATELY DOES NOT CARRY. Help and the theme are back on the bar as named
 * controls, because a control a user is looking for is worth a click less than one they are
 * not: both are reached often enough that hiding them behind a trigger costs more than the
 * width they take. What stays here is what a user reaches for rarely and by intent.
 *
 * THE TRIGGER NEEDS ITS OWN NAME. The avatar is `aria-hidden` (initials are not a label), the
 * kebab is decorative, and the username is CSS-hidden below `desktop`, so none of the three can
 * supply one — an `aria-label` names the user explicitly. `Menu` renders no trigger ARIA of
 * its own; the four attributes it hands back are wired here.
 *
 * THE USERNAME WAITS FOR `desktop`, with the wordmark, and is capped when it shows. Between
 * `tablet` and `desktop` the bar has no room left once the tab strip and the named controls are
 * drawn, and a name is the one term in its width that grows with the user — so it is withheld
 * there, and truncated past the cap rather than allowed to widen the bar above it.
 *
 * @example
 * <UserMenu username="alice" onGiveFeedback={open} onSignOut={signOut} />
 */
export function UserMenu({username, onGiveFeedback, onSignOut}: UserMenuProps) {
  const items: MenuItem[] = [
    {kind: 'action', label: 'Give feedback', icon: <FeedbackIcon className="h-4 w-4" />, onSelect: onGiveFeedback},
    {kind: 'separator'},
    // Last, and the only item that ends the session — `danger` is the tone this app uses for a
    // control whose effect is not undone by clicking it again.
    {kind: 'action', label: 'Sign out', icon: <SignOutIcon className="h-4 w-4" />, tone: 'danger', onSelect: onSignOut}
  ];

  return (
    <Menu
      ariaLabel="Account"
      items={items}
      menuClassName="min-w-52"
      trigger={({open, toggle, ref, menuId}) => (
        <button
          ref={ref}
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? menuId : undefined}
          aria-label={`Account: ${username}`}
          onClick={toggle}
          className="flex min-h-[24px] items-center gap-1.5 rounded-full py-0.5 pl-0.5 pr-1 hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          {/* 28px, not the 32 `h-8` reads as: the root font is 14px, so `--spacing` is 3.5px
              and every `rem`-derived size is smaller than it looks. Still clear of the 24px
              floor, which is why the floor itself is written on the button above in an
              ABSOLUTE unit — `min-h-7` would be 24.5px here and 21px under a 12px root. */}
          <span
            className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-hover text-xs font-semibold text-white"
            aria-hidden="true">
            {username.slice(0, 2).toUpperCase()}
          </span>
          <span
            title={username}
            className="hidden max-w-40 truncate text-sm text-text-2 desktop:inline">
            {username}
          </span>
          {/* The whole point of the trigger's redesign: an avatar alone looks like a status
              badge, so nothing on it said a menu was there to open. */}
          <KebabIcon className="h-4 w-4 flex-none text-text-3" />
        </button>
      )}
    />
  );
}
