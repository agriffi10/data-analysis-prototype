import {Menu, type MenuItem} from './Menu';
import {HelpCircleIcon, FeedbackIcon, SignOutIcon, ThemeIcon} from './icons';
import {useTheme, THEME_OPTIONS} from '../lib/useTheme';

export type UserMenuProps = {
  /** The signed-in user, shown on the trigger and named in its accessible label. */
  username: string;
  /** Go to Help & guides. A route, not a panel — the per-page help button stays on the bar. */
  onHelp: () => void;
  onGiveFeedback: () => void;
  onSignOut: () => void;
};

/**
 * The account menu beside the username: Help & guides, Give feedback, the theme choice, and
 * Sign out last.
 *
 * PRESENTATIONAL BY REQUIREMENT, not by taste. `components/` may not import `features/`
 * (`eslint.config.js`), and its exemption list is two files long — so help, feedback and sign
 * out arrive as callbacks and `Header`, which is exempt, does the wiring. The theme is the one
 * exception it can own outright: `useTheme` is a `lib/` module store, exactly as `ThemeMenu`
 * reads it.
 *
 * The controls were separate header buttons. On a phone the header was already over its width
 * budget before the sixth was added, which is why two of them were mount-gated away below
 * `tablet` and lived in the drawer instead; one menu is what lets every control exist at every
 * width.
 *
 * THE TRIGGER NEEDS ITS OWN NAME. The avatar is `aria-hidden` (initials are not a label) and
 * the username is CSS-hidden below `tablet`, so neither can supply one — an `aria-label` names
 * the user explicitly. `Menu` renders no trigger ARIA of its own; the four attributes it hands
 * back are wired here.
 *
 * @example
 * <UserMenu username="alice" onHelp={goHelp} onGiveFeedback={open} onSignOut={signOut} />
 */
export function UserMenu({username, onHelp, onGiveFeedback, onSignOut}: UserMenuProps) {
  const {preference, setPreference} = useTheme();

  const items: MenuItem[] = [
    {kind: 'action', label: 'Help & guides', icon: <HelpCircleIcon className="h-4 w-4" />, onSelect: onHelp},
    {kind: 'action', label: 'Give feedback', icon: <FeedbackIcon className="h-4 w-4" />, onSelect: onGiveFeedback},
    {kind: 'separator'},
    // The theme choices are their own section between separators rather than mixed in with the
    // plain actions above: `Menu` renders its tick column only for items that declare
    // `selected`, so interleaving the two gives the labels a ragged left edge.
    ...THEME_OPTIONS.map<MenuItem>((option) => ({
      kind: 'action',
      label: option.label,
      icon: <ThemeIcon className="h-4 w-4" />,
      selected: option.value === preference,
      onSelect: () => setPreference(option.value)
    })),
    {kind: 'separator'},
    // Last, as asked, and the only item that ends the session — `danger` is the tone this app
    // uses for a control whose effect is not undone by clicking it again.
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
          className="flex min-h-[24px] items-center gap-2 rounded-full p-0.5 hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <span className="hidden pl-2 text-sm text-text-2 tablet:inline">{username}</span>
          {/* 32px, comfortably over the 24px target floor. The floor is written in an
              absolute unit on the button above because the root font is 14px, which makes
              every `rem`-derived size understate it. */}
          <span
            className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-hover text-xs font-semibold text-white"
            aria-hidden="true">
            {username.slice(0, 2).toUpperCase()}
          </span>
        </button>
      )}
    />
  );
}
