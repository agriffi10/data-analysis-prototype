import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, screen, within} from '@testing-library/react';
import {Header} from './Header';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated, unauthenticated} from '../test/authFixtures';
import {Route, Routes, useNavigate} from 'react-router';
import {RootLayout} from './RootLayout';
import type {AuthContextValue} from '../features/auth';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../test/axe';

// ─── from Header.test.tsx ───
vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

describe('Header', () => {
  /**
   * Auth is INJECTED, not mocked (SPEC-154 FR-002). `vi.mock('../features/auth')` replaced the
   * whole barrel, so the real provider never ran and no test could click a control that calls
   * it — `signOut` was a spy on a stub of a stub. The harness's `auth` option supplies a real
   * `AuthContextValue` to the real `useAuth`, which is what `LandingPage.test.tsx` already does.
   * Only the notifications SERVICE is mocked: that is the AWS boundary.
   */

  function setWidth(w: number) {
    Object.defineProperty(window, 'innerWidth', {value: w, writable: true, configurable: true});
  }

  function renderHeader(auth: AuthContextValue = unauthenticated()) {
    return renderWithProviders(<Header />, {auth, route: '/files'});
  }

  beforeEach(() => {
    setWidth(1024);
  });

  afterEach(() => {
    cleanup();
    setWidth(1024);
  });

  describe('Header hamburger (SPEC-095 FR-002)', () => {
    it('renders the hamburger + primary nav for authenticated users', () => {
      renderHeader(authenticated('alice'));

      const hamburger = screen.getByRole('button', {name: 'Open navigation'});
      expect(hamburger).toHaveClass('tablet:hidden', 'h-11', 'w-11');
      expect(hamburger).toHaveAttribute('aria-expanded', 'false');
      // aria-controls is only set while the drawer is mounted (see mobile test).
      expect(hamburger).not.toHaveAttribute('aria-controls');
      // Primary tab strip is present but desktop-only (hidden below tablet).
      expect(screen.getByRole('navigation', {name: 'Primary'}).parentElement).toHaveClass('hidden', 'tablet:flex');
      // Brand + bell remain at all widths.
      expect(screen.getByText('Data Quarry')).toBeInTheDocument();
    });

    // THE WORDS, not the square — and `desktop`, not `tablet`, which is the whole finding.
    // A `tablet:` threshold fixes the phone and leaves 900–1023 wrapping the wordmark onto a
    // second line inside a one-line bar, because that band shows the tab strip and the three
    // control labels at once. Measured against the former, longer `Data Workspace`; the rename
    // shortened it, which can only move that edge down — see the register entry, which is the
    // one place that reasoning lives. Pinned to the exact class for that reason: `hidden` alone would
    // pass on the threshold that was wrong. Asserted on the class because jsdom has no layout —
    // it loads no Tailwind, so a wrapped wordmark and a hidden one measure identically here.
    it('holds the wordmark back to desktop when signed in, and keeps it when signed out', () => {
      renderHeader(authenticated('alice'));
      expect(screen.getByText('Data Quarry')).toHaveClass('hidden', 'desktop:inline');
      expect(screen.getByText('Data Quarry')).not.toHaveClass('tablet:inline');

      cleanup();

      // Signed out there is no hamburger, no tab strip and no user zone, so there is room at
      // every width — and the landing page's own mark is a separate instance this cannot reach.
      renderHeader(unauthenticated());
      expect(screen.getByText('Data Quarry')).not.toHaveClass('hidden');
    });

    // AND WHAT WAITS WITH IT. At `tablet` the bar overflowed until the username and the tab icons
    // joined the wordmark, and a tab label on two lines is the other face of the same shortfall.
    // Pinned to the exact class strings, for the wordmark's reason and one more: `hidden` alone
    // passes on the threshold that overflowed, and so does any added `tablet:` class that shows
    // it again. The tab count is pinned too, because a sixth tab spends the band's headroom and
    // owes the width sweep in `docs/testing/e2e.md` §4.15.
    it('holds the username and the tab icons back to desktop, and never wraps a tab', () => {
      renderHeader(authenticated('alice'));

      expect(screen.getByText('alice')).toHaveAttribute(
        'class',
        'hidden max-w-40 truncate text-sm text-text-2 desktop:inline'
      );

      const tabs = within(screen.getByRole('navigation', {name: 'Primary'})).getAllByRole('link');
      expect(tabs, 'a new tab owes the band sweep before this count moves').toHaveLength(5);
      for (const tab of tabs) {
        expect(tab).toHaveClass('whitespace-nowrap');
        expect([...tab.classList].filter((c) => c.startsWith('tablet:'))).toEqual([]);
        expect(tab.querySelector('svg')).toHaveAttribute('class', 'hidden h-4 w-4 flex-none desktop:block');
      }
    });

    // The name has to be SOMEWHERE below `tablet`, and this is the only place left. Driven to
    // the open drawer rather than asserted against the closed tree, so it cannot pass on a
    // drawer that never mounted.
    it('names the app in the nav drawer, where the bar no longer can', async () => {
      setWidth(375);
      const {user} = renderHeader(authenticated('alice'));
      await user.click(screen.getByRole('button', {name: 'Open navigation'}));

      const drawer = await screen.findByRole('dialog', {name: 'Navigation'});
      expect(within(drawer).getByText('Data Quarry')).toBeInTheDocument();
    });

    it('opens the nav drawer on mobile when the hamburger is clicked', () => {
      setWidth(500);
      renderHeader(authenticated('alice'));

      expect(screen.queryByRole('dialog', {name: 'Navigation'})).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', {name: 'Open navigation'}));
      const drawer = screen.getByRole('dialog', {name: 'Navigation'});
      expect(drawer).toBeInTheDocument();
      const hamburger = screen.getByRole('button', {name: 'Open navigation'});
      expect(hamburger).toHaveAttribute('aria-expanded', 'true');
      // Linked to the now-mounted drawer.
      expect(hamburger.getAttribute('aria-controls')).toBe(drawer.id);
    });

    it('does not mount the nav drawer at desktop widths', () => {
      setWidth(1400);
      renderHeader(authenticated('alice'));
      // Even if state were open, the drawer is JS-gated to mobile only.
      expect(screen.queryByRole('dialog', {name: 'Navigation'})).not.toBeInTheDocument();
    });
  });

  // ─── the account menu (what is left in it, and the kebab that says it is there) ───
  describe('the account menu', () => {
    const ITEMS = ['Give feedback', 'Sign out'];

    async function openMenu() {
      const {user} = renderHeader(authenticated('alice'));
      await user.click(screen.getByRole('button', {name: 'Account: alice'}));
      return {user, menu: screen.getByRole('menu', {name: 'Account'})};
    }

    it('carries every option with an icon, and Sign out last', async () => {
      const {menu} = await openMenu();
      // Pinned WHOLE, in document order. Help and the theme moved back onto the bar as named
      // controls, and this list is what says they left rather than gained a second home:
      // asserting only that the two survivors are present would pass over either coming back.
      const items = [...menu.querySelectorAll<HTMLElement>('[role^="menuitem"]')];

      expect(items.map((i) => i.textContent?.trim())).toEqual(ITEMS);
      // "Each option should have text and an icon" — the icons are aria-hidden svgs, so this
      // asserts the element rather than an accessible name, which would not see them.
      for (const item of items) expect(item.querySelector('svg')).not.toBeNull();
      expect(items.at(-1)).toHaveTextContent('Sign out');
    });

    // The trigger has to name the user itself: the avatar's initials are aria-hidden, the kebab
    // is decorative, and the username text is CSS-hidden below `desktop`, so none of the three
    // can supply the accessible name.
    it('names the signed-in user on the trigger, and reports its own expanded state', async () => {
      const {user} = renderHeader(authenticated('alice'));
      const trigger = screen.getByRole('button', {name: 'Account: alice'});

      expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
      expect(trigger).toHaveAttribute('aria-expanded', 'false');
      // Absent while closed — it must not point at an element that is not rendered.
      expect(trigger).not.toHaveAttribute('aria-controls');

      await user.click(trigger);

      expect(trigger).toHaveAttribute('aria-expanded', 'true');
      // All four attributes the trigger owes `Menu` are asserted, not three: `aria-controls`
      // has to name the popover that actually appeared, so it is compared against its id.
      expect(trigger).toHaveAttribute('aria-controls', screen.getByRole('menu', {name: 'Account'}).id);
    });

    // WHY THE KEBAB EXISTS, asserted rather than left to the class string. The trigger was an
    // avatar and a name, which reads as a status badge — nothing on it said there was a menu
    // behind it. Counted against the AVATAR's own svg (the gradient initials are a span, but a
    // future avatar image would not be), so this cannot pass on the icon of some other item.
    it('shows a kebab on the trigger, so the menu is discoverable', () => {
      renderHeader(authenticated('alice'));
      const trigger = screen.getByRole('button', {name: 'Account: alice'});

      expect(trigger.querySelectorAll('svg')).toHaveLength(1);
      // Three dots, which is what makes it a kebab rather than any other glyph.
      expect(trigger.querySelectorAll('svg circle')).toHaveLength(3);
    });

    // Help left this menu for the bar, and BOTH halves of that are asserted here. The absence
    // alone would pass over a release that dropped help entirely; the bar control alone would
    // pass over one that kept a second copy in the menu. Driven to its effect rather than
    // queried — a control that renders and does nothing is the dead affordance the unasserted
    // menu item used to be. (Where the control goes on a route with no panel is
    // `helpPanel.test.tsx`; every route in this app but `/help` itself has one.)
    it('leaves help to the bar, and the bar control works', async () => {
      const {user} = renderHeader(authenticated('alice'));

      await user.click(screen.getByRole('button', {name: 'Account: alice'}));
      expect(
        within(screen.getByRole('menu', {name: 'Account'})).queryByRole('menuitem', {name: 'Help & guides'})
      ).not.toBeInTheDocument();
      await user.keyboard('{Escape}');

      await user.click(screen.getByRole('button', {name: 'Help for this page'}));

      expect(await screen.findByRole('dialog', {name: 'Files'})).toBeInTheDocument();
    });

    it('signs out from the last item', async () => {
      const auth = authenticated('alice');
      const {user} = renderWithProviders(<Header />, {auth, route: '/files'});
      await user.click(screen.getByRole('button', {name: 'Account: alice'}));
      await user.click(within(screen.getByRole('menu', {name: 'Account'})).getByRole('menuitem', {name: 'Sign out'}));

      expect(auth.signOut).toHaveBeenCalledTimes(1);
    });

    it('closes on Escape and returns focus to the trigger', async () => {
      const {user} = await openMenu();
      await user.keyboard('{Escape}');

      expect(screen.queryByRole('menu', {name: 'Account'})).not.toBeInTheDocument();
      expect(document.activeElement).toBe(screen.getByRole('button', {name: 'Account: alice'}));
    });

    it('has no axe violations with the menu open', async () => {
      const {user} = renderHeader(authenticated('alice'));
      const container = screen.getByRole('banner').parentElement as HTMLElement;
      await user.click(screen.getByRole('button', {name: 'Account: alice'}));

      await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
    });
  });
});

// ─── from RootLayout.test.tsx ───

describe('RootLayout', () => {
  // The Header mounts useNotifications for the bell indicator — stub the read so
  // RootLayout tests make no S3/SQS call and stay focused on layout. This is the AWS
  // boundary and the only thing mocked here.

  /**
   * Route composition IS the subject here, so each test supplies its own `<Routes>` — but
   * *inside* the harness's router rather than beside a hand-rolled one (SPEC-154 FR-007),
   * which is what `LandingPage.test.tsx` already does. `route` sets the entry point.
   *
   * Auth is the REAL `useAuth` reading an injected context (FR-002). The old
   * `vi.mock('../features/auth')` replaced the whole barrel, so the provider never ran.
   */
  const renderAt = (route: string, routes: React.ReactElement) =>
    renderWithProviders(routes, {route, auth: unauthenticated()});

  afterEach(() => {
    cleanup();
  });

  describe('RootLayout', () => {
    // The boundary is scoped below the Header so a throwing page leaves working
    // navigation — but RootLayout is a LAYOUT route, so the boundary instance outlives
    // child-route changes. Without a reset the fallback would persist after navigating
    // away: nav visible, content region stuck, and the only escape a reload. The reset
    // is a prop and not a `key`; what a key would cost the signed-in shell is pinned in
    // `App.navigation.test.tsx`, against the real route table.
    describe('the error boundary around the Outlet', () => {
      function Boom(): never {
        throw new Error('render failed');
      }

      // A real in-router navigation. Rendering a second MemoryRouter would NOT do:
      // `initialEntries` applies at mount only, so a rerender leaves the route where it
      // was and a recovery test would pass against the very bug it exists to catch.
      function GoTo({path}: {path: string}) {
        const navigate = useNavigate();
        return <button onClick={() => navigate(path)}>{`go to ${path}`}</button>;
      }

      /** What the boundary caught, read off its dev-only log — the one trace a catch leaves. */
      const catches = (consoleWarn: {mock: {calls: unknown[][]}}) =>
        consoleWarn.mock.calls.filter(([message]) => message === '[ErrorBoundary] caught a render error:');

      function renderBoomAt(initialEntry: string) {
        return renderAt(
          initialEntry,
          <>
            {/* Outside the layout, so it survives the throw the way real nav does. */}
            <GoTo path="/help" />
            <GoTo path="/files" />
            <GoTo path="/query" />
            <Routes>
              <Route element={<RootLayout />}>
                <Route
                  path="/files"
                  element={<Boom />}
                />
                <Route
                  path="/query"
                  element={<Boom />}
                />
                <Route
                  path="/help"
                  element={<div>HELP CONTENT</div>}
                />
              </Route>
            </Routes>
          </>
        );
      }

      it('contains a throwing page while the header survives', () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
        renderBoomAt('/files');

        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(screen.getByText('Data Quarry')).toBeInTheDocument();
        consoleError.mockRestore();
      });

      it('recovers on the next route, rather than pinning the fallback until a reload', async () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
        const {user} = renderBoomAt('/files');
        expect(screen.getByRole('alert')).toBeInTheDocument();

        await user.click(screen.getByRole('button', {name: 'go to /help'}));

        expect(screen.getByText('HELP CONTENT')).toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        consoleError.mockRestore();
      });

      // The route change that renders a broken page is also a change of reset key. Resetting on
      // THAT update would render the page straight into a second throw — the fallback still
      // shows either way, so the only thing that tells the two apart is how often it caught.
      it('catches a page it navigates INTO once, and keeps the fallback', async () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
        const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {});
        const {user} = renderBoomAt('/help');

        await user.click(screen.getByRole('button', {name: 'go to /files'}));

        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(catches(consoleWarn)).toHaveLength(1);
        consoleError.mockRestore();
        consoleWarn.mockRestore();
      });

      // A reset that renders ANOTHER broken page never commits, so the catch after it still finds
      // the error in the previous state, and only the unchanged key stops a second reset. Without
      // that the boundary resets into the throw until React gives up and the error escapes it.
      it('catches a second broken page once, rather than resetting back into it', async () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
        const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {});
        const {user} = renderBoomAt('/files');

        await user.click(screen.getByRole('button', {name: 'go to /query'}));

        expect(screen.getByRole('alert')).toBeInTheDocument();
        // One for the page it opened on, one for the page it went to.
        expect(catches(consoleWarn)).toHaveLength(2);
        consoleError.mockRestore();
        consoleWarn.mockRestore();
      });
    });
  });
});
