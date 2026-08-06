import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {screen, fireEvent, cleanup} from '@testing-library/react';
import {Header} from './Header';
import {renderWithProviders} from '../test/renderWithProviders';
import {authValue, authenticated, unauthenticated} from '../test/authFixtures';
import type {AuthContextValue} from '../features/auth';

/**
 * Auth is INJECTED, not mocked (SPEC-154 FR-002). `vi.mock('../features/auth')` replaced the
 * whole barrel, so the real provider never ran and no test could click a control that calls
 * it — `signOut` was a spy on a stub of a stub. The harness's `auth` option supplies a real
 * `AuthContextValue` to the real `useAuth`, which is what `LandingPage.test.tsx` already does.
 * Only the notifications SERVICE is mocked: that is the AWS boundary.
 */
vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

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

  it('does not render the hamburger for unauthenticated users', () => {
    renderHeader();
    expect(screen.queryByRole('button', {name: 'Open navigation'})).not.toBeInTheDocument();
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

describe('Header authentication controls (SPEC-154 FR-002)', () => {
  it('signs the user out when Sign out is clicked', async () => {
    // Nothing in the suite had ever clicked this control: `Header.tsx` renders
    // `onClick={() => void signOut()}` and coverage was three spy-count assertions inside
    // the auth provider's own test plus a synthetic probe button. A dropped handler, a
    // renamed label or a control rendered for the wrong auth state all passed green.
    const auth = authenticated('alice');
    const {user} = renderHeader(auth);

    await user.click(screen.getByRole('button', {name: 'Sign out'}));

    expect(auth.signOut).toHaveBeenCalledTimes(1);
  });

  it('offers no Sign out control when signed out', async () => {
    renderHeader();

    expect(screen.queryByRole('button', {name: 'Sign out'})).not.toBeInTheDocument();
  });

  it('announces an auth error as an alert', () => {
    // `role="alert"` is the whole contract here — it is how a screen reader learns the
    // sign-in failed — and no test had ever rendered this banner.
    renderHeader(authValue({status: 'unauthenticated', user: null, error: 'Your session expired.'}));

    expect(screen.getByRole('alert')).toHaveTextContent('Your session expired.');
  });

  it('shows no alert region when there is no auth error', () => {
    renderHeader(authenticated('alice'));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
