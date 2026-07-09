import {describe, it, expect, vi, beforeEach, afterEach, type MockedFunction} from 'vitest';
import {render, screen, fireEvent, cleanup} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import type {ReactNode} from 'react';
import {Header} from './Header';
import type {AuthContextValue} from '../features/auth';

vi.mock('../features/auth', () => ({useAuth: vi.fn()}));
vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

import {useAuth} from '../features/auth';

const mockUseAuth = useAuth as unknown as MockedFunction<() => AuthContextValue>;

function setWidth(w: number) {
  Object.defineProperty(window, 'innerWidth', {value: w, writable: true, configurable: true});
}

const withProviders = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>
    <MemoryRouter initialEntries={['/files']}>{ui}</MemoryRouter>
  </QueryClientProvider>
);

function asAuthed() {
  mockUseAuth.mockReturnValue({
    status: 'authenticated',
    user: {username: 'alice'} as AuthContextValue['user'],
    error: null,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn()
  });
}

beforeEach(() => {
  setWidth(1024);
  mockUseAuth.mockReturnValue({
    status: 'unauthenticated',
    user: null,
    error: null,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn()
  });
});

afterEach(() => {
  cleanup();
  setWidth(1024);
});

describe('Header hamburger (SPEC-095 FR-002)', () => {
  it('renders the hamburger + primary nav for authenticated users', () => {
    asAuthed();
    render(withProviders(<Header />));

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
    render(withProviders(<Header />));
    expect(screen.queryByRole('button', {name: 'Open navigation'})).not.toBeInTheDocument();
  });

  it('opens the nav drawer on mobile when the hamburger is clicked', () => {
    setWidth(500);
    asAuthed();
    render(withProviders(<Header />));

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
    asAuthed();
    render(withProviders(<Header />));
    // Even if state were open, the drawer is JS-gated to mobile only.
    expect(screen.queryByRole('dialog', {name: 'Navigation'})).not.toBeInTheDocument();
  });
});
