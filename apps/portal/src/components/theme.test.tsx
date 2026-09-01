import {useState} from 'react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, screen} from '@testing-library/react';
import {Header} from './Header';
import {ThemeMenu} from './ThemeMenu';
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
  it('sits in the header at tablet and above, signed in or out', () => {
    renderWithProviders(<Header />, {auth: authenticated('alice'), route: '/files'});
    expect(screen.getByRole('button', {name: 'Change theme'})).toBeInTheDocument();
    cleanup();

    // The landing page carries its own copy; this is the header a signed-out visitor meets on
    // any other route.
    renderWithProviders(<Header />, {auth: unauthenticated(), route: '/files'});
    expect(screen.getByRole('button', {name: 'Change theme'})).toBeInTheDocument();
  });

  it('moves into the nav drawer below tablet when signed in, adding nothing to the header', async () => {
    // The authenticated header is over its width budget at 375px before anything is added — a
    // hamburger, the brand mark, help, the bell, an avatar and Sign out inside `px-4`.
    setWidth(375);
    const {user} = renderWithProviders(<Header />, {auth: authenticated('alice'), route: '/files'});

    expect(screen.queryByRole('button', {name: 'Change theme'})).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'Open navigation'}));
    const group = screen.getByRole('group', {name: 'Theme'});
    expect(group).toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'Dark'}));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(screen.getByRole('button', {name: 'Dark'})).toHaveAttribute('aria-pressed', 'true');
  });

  it('stays in the header below tablet when signed out, where there is no drawer', () => {
    // The signed-out header carries a brand mark and one button, and mounts no drawer at all,
    // so the measurement that moved the control does not apply to it.
    setWidth(375);
    renderWithProviders(<Header />, {auth: unauthenticated(), route: '/files'});
    expect(screen.getByRole('button', {name: 'Change theme'})).toBeInTheDocument();
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
