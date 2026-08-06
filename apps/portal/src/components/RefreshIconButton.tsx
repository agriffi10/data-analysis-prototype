import {IconButton} from './IconButton';
import {cx} from '../lib/cx';

type RefreshIconButtonProps = {
  /** Accessible name, e.g. "Refresh notifications" — say WHAT is refreshed. */
  label: string;
  /** In flight: the glyph spins and the button is disabled. */
  busy?: boolean;
  /** Matches `IconButton`; 'sm' for a page toolbar, 'md' beside body text. */
  size?: 'sm' | 'md';
  onClick: () => void;
};

/**
 * The refresh affordance for a list page: one icon button, one spinner glyph.
 *
 * There were three divergent refresh spinners in the app and two byte-identical
 * copies of this one. The glyph lives here now so a change to it is a change to all
 * of them.
 *
 * @example
 * <RefreshIconButton label="Refresh notifications" busy={refreshing} onClick={() => void handleRefresh()} />
 */
export function RefreshIconButton({label, busy = false, size = 'sm', onClick}: RefreshIconButtonProps) {
  return (
    <IconButton
      label={label}
      size={size}
      disabled={busy}
      onClick={onClick}>
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className={cx('h-4 w-4', busy && 'animate-spin')}
        aria-hidden="true">
        <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
        <path d="M21 3v5h-5" />
        <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
        <path d="M3 21v-5h5" />
      </svg>
    </IconButton>
  );
}
