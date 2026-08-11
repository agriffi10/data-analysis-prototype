import {afterEach, beforeEach, describe, expect, it} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import {renderWithProviders} from '../test/renderWithProviders';
import {LandingNavMenu} from './LandingNavMenu';
import {COMPONENT_AXE_OPTIONS, ROUTE_AXE_OPTIONS, expectNoA11yViolations} from '../test/axe';
import {Route, Routes} from 'react-router';
import {authenticated, unauthenticated} from '../test/authFixtures';
import {setReturnPath} from '../lib/returnPath';
import {TestProviders} from '../test/renderWithProviders';
import type {AuthContextValue} from '../features/auth/auth.types';
import HelpPage from './HelpPage';
import LandingPage from './LandingPage';

// ─── from HelpPage.test.tsx ───
describe('HelpPage', () => {
  // Static content route (SPEC-074): the wrapper renders the real feature view,
  // which owns the content + document title. No data layer / network to mock.
  describe('HelpPage route', () => {
    it('renders the help feature with its first-section guide content', () => {
      renderWithProviders(<HelpPage />, {route: '/help'});

      // Default section is the first (Files); its first guide card is "Upload files"
      // (accordion header button, collapsed by default).
      expect(screen.getByRole('button', {name: /Upload files/})).toBeInTheDocument();
    });

    it('sets the page title', () => {
      renderWithProviders(<HelpPage />, {route: '/help'});
      expect(document.title).toMatch(/Help & guides/);
    });
  });
});

// ─── from LandingNavMenu.test.tsx ───
describe('LandingNavMenu', () => {
  const links = [
    {label: 'Features', href: '#features'},
    {label: 'Security', href: '#security'}
  ];

  afterEach(() => {
    window.location.hash = '';
  });

  describe('LandingNavMenu', () => {
    it('is a closed hamburger toggle initially', () => {
      render(<LandingNavMenu links={links} />);
      const toggle = screen.getByRole('button', {name: 'Open menu'});
      expect(toggle).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
      // The whole control is mobile-only.
      expect(toggle.closest('.relative')).toHaveClass('tablet:hidden');
    });

    it('reveals the section anchors when toggled', () => {
      render(<LandingNavMenu links={links} />);
      fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
      expect(screen.getByRole('menuitem', {name: 'Features'})).toBeInTheDocument();
      expect(screen.getByRole('menuitem', {name: 'Security'})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Open menu'})).toHaveAttribute('aria-expanded', 'true');
    });

    it('navigates to the anchor and closes the panel on link activation', () => {
      render(<LandingNavMenu links={links} />);
      fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
      fireEvent.click(screen.getByRole('menuitem', {name: 'Security'}));
      expect(window.location.hash).toBe('#security');
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });

    it('closes on Escape and on outside click', () => {
      render(
        <div>
          <button>outside</button>
          <LandingNavMenu links={links} />
        </div>
      );
      const open = () => fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));

      open();
      fireEvent.keyDown(screen.getByRole('menu'), {key: 'Escape'});
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();

      open();
      fireEvent.mouseDown(screen.getByRole('button', {name: 'outside'}));
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });

    it('has no a11y violations (closed)', async () => {
      await expectNoA11yViolations(<LandingNavMenu links={links} />, COMPONENT_AXE_OPTIONS);
    });
  });
});

// ─── from LandingPage.test.tsx ───
describe('LandingPage', () => {
  // Integration style (react.md §21): render the REAL LandingPage — it makes no AWS
  // calls, so nothing is mocked. Auth state is injected via `renderWithProviders`
  // (real `useAuth`), and the return-path branch is driven through the real
  // `takeReturnPath` (backed by jsdom sessionStorage). A sibling `/files` route lets
  // us observe navigation/redirects as rendered output.
  function renderApp(auth: AuthContextValue) {
    return renderWithProviders(
      <Routes>
        <Route
          path="/"
          element={<LandingPage />}
        />
        <Route
          path="/files"
          element={<div>files-page</div>}
        />
      </Routes>,
      {route: '/', auth}
    );
  }

  beforeEach(() => {
    sessionStorage.clear();
  });

  describe('LandingPage when authenticated', () => {
    it('shows Go to Dashboard (not sign-in/up) and navigates to /files on click', async () => {
      const {user} = renderApp(authenticated('alice'));

      const cta = screen.getAllByRole('button', {name: /go to dashboard/i});
      expect(cta.length).toBeGreaterThan(0);
      expect(screen.queryByRole('button', {name: /^sign in$/i})).not.toBeInTheDocument();
      expect(screen.queryByRole('button', {name: /create account/i})).not.toBeInTheDocument();

      await user.click(cta[0]);
      expect(screen.getByText('files-page')).toBeInTheDocument();
    });

    it('redirects to a pending return path instead of rendering the page', () => {
      setReturnPath('/files');
      renderApp(authenticated('alice'));

      expect(screen.getByText('files-page')).toBeInTheDocument();
      expect(screen.queryByRole('button', {name: /go to dashboard/i})).not.toBeInTheDocument();
    });
  });

  describe('LandingPage when unauthenticated', () => {
    it('shows Sign in and Create account entry points for a signed-out visitor', () => {
      renderApp(unauthenticated());

      expect(screen.getAllByRole('button', {name: /^sign in$/i}).length).toBeGreaterThan(0);
      expect(screen.getAllByRole('button', {name: /create( your)? account/i}).length).toBeGreaterThan(0);
      expect(screen.queryByRole('button', {name: /go to dashboard/i})).not.toBeInTheDocument();
    });

    it('runs the sign-in action when Sign in is clicked (SPEC-154 FR-002)', async () => {
      // The suite asserted these controls EXIST and never clicked one. A dropped `onClick`,
      // a handler wired to the wrong action, or a button that renders but does nothing all
      // passed — on the app's front door.
      const auth = unauthenticated();
      const {user} = renderApp(auth);

      await user.click(screen.getAllByRole('button', {name: /^sign in$/i})[0]);

      expect(auth.signIn).toHaveBeenCalledTimes(1);
      expect(auth.signUp).not.toHaveBeenCalled();
    });

    it('runs the sign-UP action when Create account is clicked', async () => {
      // The pair matters: both controls sit side by side and both are one word from the
      // other's handler, so asserting one without the other cannot catch a swap.
      const auth = unauthenticated();
      const {user} = renderApp(auth);

      await user.click(screen.getAllByRole('button', {name: /create( your)? account/i})[0]);

      expect(auth.signUp).toHaveBeenCalledTimes(1);
      expect(auth.signIn).not.toHaveBeenCalled();
    });
  });

  describe('LandingPage responsive markers (SPEC-104)', () => {
    it('hides the inline nav links behind a hamburger below tablet', () => {
      renderApp(authenticated('alice'));
      expect(screen.getByRole('button', {name: 'Open menu'})).toBeInTheDocument();
      // The inline anchor group is desktop/tablet-only.
      const inline = screen.getByRole('link', {name: 'Features'}).closest('div');
      expect(inline).toHaveClass('hidden', 'tablet:flex');
    });

    it('scales the hero, CTAs, and feature grid fluidly across the three tiers', () => {
      renderApp(authenticated('alice'));

      // Hero headline steps 32 → 40 → 46px.
      expect(screen.getByRole('heading', {level: 1})).toHaveClass(
        'text-[32px]',
        'tablet:text-[40px]',
        'desktop:text-[46px]'
      );

      // Hero + CTA-strip buttons are full-width on mobile, auto from tablet.
      const fullWidth = screen
        .getAllByRole('button', {name: /go to dashboard/i})
        .filter((b) => b.className.includes('w-full'));
      expect(fullWidth.length).toBeGreaterThan(0);
      for (const btn of fullWidth) {
        expect(btn).toHaveClass('w-full', 'tablet:w-auto');
        expect(btn.parentElement).toHaveClass('flex-col', 'tablet:flex-row');
      }

      // Feature grid steps 1 → 2 (3rd card spans) → 3.
      const grid = document.querySelector('#features .grid')!;
      expect(grid).toHaveClass('grid-cols-1', 'tablet:grid-cols-2', 'desktop:grid-cols-3');
      expect(grid.children[2]).toHaveClass('tablet:col-span-2', 'desktop:col-span-1');
    });
  });
});

// ─── from LandingPage.a11y.test.tsx ───
describe('LandingPage.a11y', () => {
  // Integration style (react.md §21): render the REAL LandingPage in the signed-out
  // state (authenticated visitors are redirected away). No AWS boundary to mock; auth
  // is injected via AuthContext. `expectNoA11yViolations` renders the node itself, so
  // the router + auth providers are composed inline here.
  // Through the shared stack since SPEC-163: the page reads the flags to decide the
  // signed-in CTA, so it needs a QueryClientProvider even in the signed-out state it is
  // asserted in here (where the flags change nothing — FR-007 AC2).
  const signedOut = (
    <TestProviders auth={unauthenticated()}>
      <LandingPage />
    </TestProviders>
  );

  beforeEach(() => {
    sessionStorage.clear();
  });

  describe('LandingPage accessibility (SPEC-045 FR-003)', () => {
    it('has no axe violations', async () => {
      await expectNoA11yViolations(signedOut, ROUTE_AXE_OPTIONS);
    });

    it('exposes exactly one <h1> and a <main> landmark', () => {
      renderWithProviders(<LandingPage />, {route: '/', auth: unauthenticated()});
      expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
      expect(screen.getByRole('main')).toBeInTheDocument();
    });
  });
});
