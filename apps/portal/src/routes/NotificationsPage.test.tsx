import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../test/renderWithProviders';
import {authenticated} from '../test/authFixtures';

// Thin route wrapper around the notifications feature page. Render the real
// feature (real useNotifications) over a mocked read boundary — the only AWS
// touchpoint is `getNotifications`.
vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn(),
  enqueueNotificationAction: vi.fn()
}));

import {getNotifications} from '../features/notifications/notifications.service';
import NotificationsPage from './NotificationsPage';

const mockGet = vi.mocked(getNotifications);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('NotificationsPage route', () => {
  it('renders the empty state when the inbox has no notifications', async () => {
    mockGet.mockResolvedValue({success: true, data: []});

    renderWithProviders(<NotificationsPage />, {route: '/notifications', auth: authenticated('alice')});

    expect(await screen.findByText('You’re all caught up')).toBeInTheDocument();
    expect(screen.getByRole('heading', {name: 'Notifications'})).toBeInTheDocument();
  });

  it('renders a notification from the inbox', async () => {
    mockGet.mockResolvedValue({
      success: true,
      data: [{id: 'n1', message: 'Bob shared a space with you', read: false, timestamp: '2026-07-09T00:00:00Z'}]
    });

    renderWithProviders(<NotificationsPage />, {route: '/notifications', auth: authenticated('alice')});

    expect(await screen.findByText('Bob shared a space with you')).toBeInTheDocument();
  });
});
