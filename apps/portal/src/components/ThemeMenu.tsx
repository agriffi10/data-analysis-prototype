import {useTheme, THEME_OPTIONS} from '../lib/useTheme';
import {IconButton} from './IconButton';
import {ThemeIcon} from './icons';
import {Menu, type MenuItem} from './Menu';
import {SegmentedFilter} from './SegmentedFilter';

/**
 * The theme control as a header icon button opening a menu of Light / Dark / System.
 *
 * The current choice is a `menuitemradio` with `aria-checked` and a tick, so it reads to
 * assistive technology and is not carried by colour alone.
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
        <IconButton
          ref={ref}
          label="Change theme"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? menuId : undefined}
          onClick={toggle}>
          <ThemeIcon className="h-4 w-4" />
        </IconButton>
      )}
    />
  );
}

/**
 * The same three choices as a labelled group, for the mobile nav drawer.
 *
 * A group rather than a second menu: the drawer is already a dialog, and the header's icon
 * button is absent at this width because the authenticated header is over its width budget at
 * 375px before anything is added.
 *
 * @example
 * <ThemeChoiceGroup />
 */
export function ThemeChoiceGroup() {
  const {preference, setPreference} = useTheme();

  return (
    <SegmentedFilter
      label="Theme"
      options={THEME_OPTIONS}
      value={preference}
      onChange={setPreference}
    />
  );
}
