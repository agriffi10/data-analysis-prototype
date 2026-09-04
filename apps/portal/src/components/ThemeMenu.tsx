import {useTheme, THEME_OPTIONS} from '../lib/useTheme';
import {HEADER_CONTROL, HEADER_CONTROL_ACTIVE, HEADER_CONTROL_IDLE, HEADER_CONTROL_LABEL} from './headerControl';
import {ThemeIcon} from './icons';
import {cx} from '../lib/cx';
import {Menu, type MenuItem} from './Menu';

/**
 * The theme control on the top bar — an icon, the word `Theme`, and a menu of
 * Light / Dark / System.
 *
 * The current choice is a `menuitemradio` with `aria-checked` and a tick, so it reads to
 * assistive technology and is not carried by colour alone.
 *
 * The accessible name stays `Change theme` rather than shrinking to the visible word: a
 * screen-reader user hearing "Theme, button" is not told what activating it does, and SC 2.5.3
 * only asks that the name CONTAIN the label.
 *
 * @example
 * <ThemeMenu />
 */
export function ThemeMenu() {
  const {preference, setPreference} = useTheme();

  const items: MenuItem[] = THEME_OPTIONS.map((option) => ({
    kind: 'action',
    label: option.label,
    selected: option.value === preference,
    onSelect: () => setPreference(option.value)
  }));

  return (
    <Menu
      ariaLabel="Theme"
      items={items}
      trigger={({open, toggle, ref, menuId}) => (
        <button
          ref={ref}
          type="button"
          aria-label="Change theme"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? menuId : undefined}
          onClick={toggle}
          className={cx(HEADER_CONTROL, open ? HEADER_CONTROL_ACTIVE : HEADER_CONTROL_IDLE)}>
          <ThemeIcon className="h-5 w-5 flex-none" />
          <span className={HEADER_CONTROL_LABEL}>Theme</span>
        </button>
      )}
    />
  );
}
