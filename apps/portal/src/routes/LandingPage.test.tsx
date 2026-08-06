import {describe, it, expect, beforeEach} from 'vitest';
import {screen} from '@testing-library/react';
import {Routes, Route} from 'react-router';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated, unauthenticated} from '../test/authFixtures';
import {setReturnPath} from '../lib/returnPath';
import type {AuthContextValue} from '../features/auth/auth.types';
import LandingPage from './LandingPage';

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
