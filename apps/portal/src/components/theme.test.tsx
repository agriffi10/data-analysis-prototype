import {useState} from 'react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, screen, within} from '@testing-library/react';
import {Header} from './Header';
import {ThemeMenu} from './ThemeMenu';
import {HEADER_CONTROL_LABEL} from './headerControl';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated, unauthenticated} from '../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../test/axe';
import {resetThemeForTest, setThemePreference, THEME_STORAGE_KEY} from '../lib/useTheme';

vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

function setWidth(w: number) {
  Object.defineProperty(window, 'innerWidth', {value: w, writable: true, configurable: true});
}

beforeEach(() => {
  setWidth(1024);
  resetThemeForTest();
});

afterEach(() => {
  cleanup();
  setWidth(1024);
  resetThemeForTest();
});

describe('the theme control', () => {
  it('offers three choices, marks the current one to assistive technology, and applies it', async () => {
    const {user, container} = renderWithProviders(<ThemeMenu />, {auth: null});

    await user.click(screen.getByRole('button', {name: 'Change theme'}));

    // `menuitemradio` + aria-checked, not a colour: the choice has to be readable to a screen
    // reader and to somebody who cannot tell two greys apart.
    const options = screen.getAllByRole('menuitemradio');
    expect(options.map((option) => option.textContent)).toEqual(['Light', 'Dark', 'System']);
    expect(screen.getByRole('menuitemradio', {name: 'System'})).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('menuitemradio', {name: 'Dark'})).toHaveAttribute('aria-checked', 'false');

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);

    await user.click(screen.getByRole('menuitemradio', {name: 'Dark'}));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
  });

  it('switches the theme without re-mounting what is on the page', async () => {
    // FR-004's requirement, and nothing more: a Context provider would pass this too, because a
    // value change re-renders consumers and unmounts nothing. What it does catch is a switch
    // implemented by REMOUNTING — a `key` on a subtree, a router navigation — which is a real way
    // to lose what the user had typed.
    function Typed() {
      const [value, setValue] = useState('');
      return (
        <>
          <ThemeMenu />
          <label>
            Draft
            <input
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </label>
        </>
      );
    }
    const {user} = renderWithProviders(<Typed />, {auth: null});

    await user.type(screen.getByLabelText('Draft'), 'half a sentence');
    await user.click(screen.getByRole('button', {name: 'Change theme'}));
    await user.click(screen.getByRole('menuitemradio', {name: 'Dark'}));

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(screen.getByLabelText('Draft')).toHaveValue('half a sentence');
  });
});

describe('where the theme control lives', () => {
  // ON THE BAR, both auth states, both widths. It spent one release inside the account menu,
  // which cost it its name: an unlabelled trigger holding an unrelated set of options is not
  // somewhere a user looks for the theme.
  it.each([1400, 375])('is a header control when signed in, at %ipx', async (width) => {
    setWidth(width);
    const {user} = renderWithProviders(<Header />, {auth: authenticated('alice'), route: '/files'});

    await user.click(screen.getByRole('button', {name: 'Change theme'}));
    await user.click(screen.getByRole('menuitemradio', {name: 'Dark'}));

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it.each([1400, 375])('is a header control when signed out, at %ipx', (width) => {
    setWidth(width);
    renderWithProviders(<Header />, {auth: unauthenticated(), route: '/files'});
    expect(screen.getByRole('button', {name: 'Change theme'})).toBeInTheDocument();
  });

  // The word, not the icon alone. The three bar controls are queried by `aria-label`
  // everywhere else in the suite, which cannot tell a labelled control from a bare icon — this
  // is the one assertion that would redden if the visible text were dropped again.
  it('shows the word beside each of the three bar controls', () => {
    renderWithProviders(<Header />, {auth: authenticated('alice'), route: '/files'});
    const bar = screen.getByRole('banner');

    expect(within(bar).getByRole('button', {name: 'Change theme'})).toHaveTextContent('Theme');
    expect(within(bar).getByRole('link', {name: 'Notifications, none unread'})).toHaveTextContent('Notifications');
    expect(within(bar).getByRole('button', {name: 'Help for this page'})).toHaveTextContent('Help');
  });

  // AND THE WIDTH THEY APPEAR AT, which the assertion above cannot see: jsdom loads no
  // Tailwind, so `toHaveTextContent` passes over a label hidden at every width. Narrowing this
  // constant to `hidden` — or pushing it out to `desktop:` as the wordmark had to be — takes
  // all three words with it and reddens nothing else in the suite. `tablet` is the threshold
  // the bar was measured at: at 375px the fixed chrome leaves no room for three labels.
  it('shows those words from tablet up, and drops them below it', () => {
    expect(HEADER_CONTROL_LABEL).toBe('hidden tablet:inline');
  });

  // The choice is on the bar at every width, so neither the drawer nor the account menu
  // carries a second copy. Two controls setting one value is a state to keep in step for no
  // benefit, and the menu's copy is what this release removed.
  it('is in neither the nav drawer nor the account menu', async () => {
    setWidth(375);
    const {user} = renderWithProviders(<Header />, {auth: authenticated('alice'), route: '/files'});

    await user.click(screen.getByRole('button', {name: 'Account: alice'}));
    const account = await screen.findByRole('menu', {name: 'Account'});
    expect(within(account).queryByRole('menuitemradio')).not.toBeInTheDocument();
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', {name: 'Open navigation'}));
    // Wait for the drawer BEFORE asserting the absence inside it. Without this the negative
    // is satisfied by a drawer that never opened, for any unrelated reason.
    const drawer = await screen.findByRole('dialog', {name: 'Navigation'});
    expect(within(drawer).queryByRole('group', {name: 'Theme'})).not.toBeInTheDocument();
  });
});

describe('the app shell in the dark theme', () => {
  it('has no axe violations', async () => {
    // ONE dark pass, deliberately. The rest of the suite runs in light: `color-contrast` is
    // disabled in jsdom either way, so a second full run would double a long suite for a rule
    // that cannot fire. Dark-mode contrast is measured in `lib/contrast.test.ts` instead.
    // Through the store, not by stamping the attribute: the store owns that write and would
    // put it back on the next subscribe, so a hand-set attribute is a state no user reaches.
    setThemePreference('dark');
    const {container} = renderWithProviders(<Header />, {auth: authenticated('alice'), route: '/files'});
    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });
});
