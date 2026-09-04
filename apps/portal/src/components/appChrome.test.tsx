import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, screen, within} from '@testing-library/react';
import {Header} from './Header';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated, unauthenticated} from '../test/authFixtures';
import {Route, Routes} from 'react-router';
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
      expect(screen.getByText('Data Workspace')).toBeInTheDocument();
    });

    // THE WORDS, not the square. Signed in the bar carries a hamburger and four controls, and
    // at 375px those plus `Data Workspace` do not fit — the wordmark wrapped to a second line
    // inside a one-line bar. Asserted on the class because jsdom has no layout: it loads no
    // Tailwind, so a wrapped wordmark and a hidden one measure identically here.
    it('drops the wordmark on a narrow bar when signed in, and keeps it when signed out', () => {
      renderHeader(authenticated('alice'));
      expect(screen.getByText('Data Workspace')).toHaveClass('hidden', 'tablet:inline');

      cleanup();

      // Signed out there is no hamburger and no user zone, so there is room at every width —
      // and the landing page's own mark is a separate instance that this must not reach.
      renderHeader(unauthenticated());
      expect(screen.getByText('Data Workspace')).not.toHaveClass('hidden');
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

  // ─── the account menu (the consolidated header controls) ───
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
    // is decorative, and the username text is CSS-hidden below `tablet`, so none of the three
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
    // SPEC-150 FR-008. The boundary is scoped below the Header so a throwing page
    // leaves working navigation — but RootLayout is a LAYOUT route, so the boundary
    // instance outlives child-route changes. Without `key={pathname}` the fallback
    // would persist after navigating away: nav visible, content region stuck, and the
    // only escape a reload. That is the failure this pins.
    describe('the error boundary around the Outlet', () => {
      function Boom(): never {
        throw new Error('render failed');
      }

      function renderBoomAt(initialEntry: string) {
        return renderAt(
          initialEntry,
          <Routes>
            <Route element={<RootLayout />}>
              <Route
                path="/files"
                element={<Boom />}
              />
              <Route
                path="/help"
                element={<div>HELP CONTENT</div>}
              />
            </Route>
          </Routes>
        );
      }

      it('contains a throwing page while the header survives', () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
        renderBoomAt('/files');

        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(screen.getByText('Data Workspace')).toBeInTheDocument();
        consoleError.mockRestore();
      });
    });
  });
});
