import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {render, screen, cleanup, waitFor} from '@testing-library/react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import type {ReactNode} from 'react';
import {expectNoA11yViolations, ROUTE_AXE_OPTIONS} from '../../test/axe';

vi.mock('../auth', () => ({useAuth: vi.fn()}));
vi.mock('../../hooks/usePageTitle', () => ({usePageTitle: vi.fn()}));
vi.mock('./notifications.service', () => ({
  getNotifications: vi.fn(),
  enqueueNotificationAction: vi.fn()
}));

import {useAuth} from '../auth';
import {getNotifications} from './notifications.service';
import {NotificationsPage} from './NotificationsPage';
import {NotificationsBell} from './NotificationsBell';
import type {Notification} from './notifications.types';

const mockUseAuth = vi.mocked(useAuth);
const mockGet = vi.mocked(getNotifications);

const data: Notification[] = [
  {id: 'a', message: 'Shared space “sales” created', read: false, timestamp: '2026-06-28T00:02:00.000Z'},
  {id: 'b', message: 'You were added to “ops”', read: true, timestamp: '2026-06-28T00:01:00.000Z'}
];

function withProviders(ui: ReactNode) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockUseAuth.mockReturnValue({user: {username: 'alice'}, status: 'authenticated'} as any);
  mockGet.mockResolvedValue({success: true, data});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('NotificationsPage accessibility (SPEC-060 FR-006)', () => {
  it('has no axe violations with a populated list', async () => {
    const ui = withProviders(<NotificationsPage />);
    render(ui);
    await waitFor(() => expect(screen.getByText('Shared space “sales” created')).toBeInTheDocument());
    cleanup();
    await expectNoA11yViolations(ui, ROUTE_AXE_OPTIONS);
  });

  it('has no axe violations at a mobile width (stacked header + full-width Mark-read) [SPEC-102 FR-005]', async () => {
    Object.defineProperty(window, 'innerWidth', {value: 400, writable: true, configurable: true});
    try {
      const ui = withProviders(<NotificationsPage />);
      render(ui);
      await waitFor(() => expect(screen.getByText('Shared space “sales” created')).toBeInTheDocument());
      cleanup();
      await expectNoA11yViolations(ui, ROUTE_AXE_OPTIONS);
    } finally {
      Object.defineProperty(window, 'innerWidth', {value: 1024, writable: true, configurable: true});
    }
  });

  it('exposes exactly one <h1> and a <main> landmark', async () => {
    render(withProviders(<NotificationsPage />));
    await waitFor(() => expect(screen.getByText('Shared space “sales” created')).toBeInTheDocument());
    expect(screen.getAllByRole('heading', {level: 1})).toHaveLength(1);
    expect(screen.getByRole('main')).toBeInTheDocument();
  });

  it('the header bell has no axe violations', async () => {
    await expectNoA11yViolations(
      withProviders(
        <NotificationsBell
          hasUnread
          unreadCount={2}
        />
      )
    );
  });
});
