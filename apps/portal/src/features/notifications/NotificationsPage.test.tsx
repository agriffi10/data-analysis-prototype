import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {screen, cleanup, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {NotificationsPage} from './NotificationsPage';
import type {Notification} from './notifications.types';

// Integration style (react.md §21): render the REAL NotificationsPage with its real
// hooks (useNotifications, usePageTitle) and real children (NotificationRow, Pager,
// filter tabs). Mock ONLY the AWS boundary — the notifications service (S3 read +
// SQS enqueue). Auth + router + QueryClient come from the shared harness.
vi.mock('./notifications.service', () => ({
  getNotifications: vi.fn(),
  enqueueNotificationAction: vi.fn()
}));

import {getNotifications, enqueueNotificationAction} from './notifications.service';

const mockGet = vi.mocked(getNotifications);
const mockEnqueue = vi.mocked(enqueueNotificationAction);

const list = (n: number, opts: {read?: boolean} = {}): Notification[] =>
  Array.from({length: n}, (_, i) => ({
    id: `n${i}`,
    message: `Message ${i}`,
    read: opts.read ?? false,
    // newest-first: index 0 is the most recent
    timestamp: new Date(2026, 5, 28, 0, n - i).toISOString()
  }));

const renderPage = () => renderWithProviders(<NotificationsPage />);

beforeEach(() => {
  mockEnqueue.mockResolvedValue({success: true, data: undefined});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('NotificationsPage (SPEC-060)', () => {
  it('shows the loading state, then the list under a mobile-stacked page header', async () => {
    mockGet.mockResolvedValue({success: true, data: list(3)});
    renderPage();
    expect(screen.getByText('Loading notifications…')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());
    // The PageLayout header stacks below tablet, inline at ≥ tablet (SPEC-102 FR-002).
    const header = screen.getByRole('heading', {level: 1, name: 'Notifications'}).closest('div')!.parentElement!;
    expect(header).toHaveClass('flex-col', 'tablet:flex-row');
  });

  it('shows the empty state when there are no notifications', async () => {
    mockGet.mockResolvedValue({success: true, data: []});
    renderPage();
    await waitFor(() => expect(screen.getByText('You’re all caught up')).toBeInTheDocument());
  });

  it('shows an error state with a retry that re-reads', async () => {
    mockGet.mockResolvedValueOnce({success: false, error: {message: 'boom'}});
    const {user} = renderPage();
    await waitFor(() => expect(screen.getByText('Couldn’t load notifications.')).toBeInTheDocument());

    mockGet.mockResolvedValue({success: true, data: list(1)});
    await user.click(screen.getByRole('button', {name: 'Try again'}));
    await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());
  });

  it('paginates 10 per page, newest-first, with an accurate range label', async () => {
    mockGet.mockResolvedValue({success: true, data: list(25)});
    const {user} = renderPage();
    await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());

    expect(screen.getByText(/1–10 of 25/)).toBeInTheDocument();
    expect(screen.queryByText('Message 10')).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Prev'})).toBeDisabled();

    await user.click(screen.getByRole('button', {name: 'Next'}));
    expect(screen.getByText(/11–20 of 25/)).toBeInTheDocument();
    expect(screen.getByText('Message 10')).toBeInTheDocument();
  });

  it('mark read enqueues and optimistically clears just that row marker', async () => {
    mockGet.mockResolvedValue({success: true, data: list(2)});
    const {user} = renderPage();
    await waitFor(() => expect(screen.getAllByRole('button', {name: 'Mark read'})).toHaveLength(2));

    const firstRow = screen.getByText('Message 0').closest('li')!;
    await user.click(within(firstRow).getByRole('button', {name: 'Mark read'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledWith({action: 'markRead', username: 'alice', id: 'n0'}));
    await waitFor(() => expect(screen.getAllByRole('button', {name: 'Mark read'})).toHaveLength(1));
  });

  it('mark all read enqueues, clears every marker, and leaves the control disabled once nothing is unread', async () => {
    mockGet.mockResolvedValue({success: true, data: list(3)});
    const {user} = renderPage();
    await waitFor(() => expect(screen.getAllByRole('button', {name: 'Mark read'})).toHaveLength(3));

    const markAll = screen.getByRole('button', {name: 'Mark all read'});
    expect(markAll).toBeEnabled();
    await user.click(markAll);

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledWith({action: 'markAllRead', username: 'alice'}));
    await waitFor(() => expect(screen.queryByRole('button', {name: 'Mark read'})).not.toBeInTheDocument());
    expect(markAll).toBeDisabled();
  });

  it('rolls back and shows a danger toast when an action fails', async () => {
    mockGet.mockResolvedValue({success: true, data: list(1)});
    mockEnqueue.mockResolvedValue({success: false, error: {message: 'queue down'}});
    const {user} = renderPage();
    await waitFor(() => expect(screen.getByRole('button', {name: 'Mark read'})).toBeInTheDocument());

    await user.click(screen.getByRole('button', {name: 'Mark read'}));

    await waitFor(() => expect(screen.getByText('queue down')).toBeInTheDocument());
    // rolled back — the unread row (and its Mark read control) is still present.
    expect(screen.getByRole('button', {name: 'Mark read'})).toBeInTheDocument();
  });

  it('the Unread filter hides read notifications and re-pages the list', async () => {
    mockGet.mockResolvedValue({
      success: true,
      data: [
        {id: 'u', message: 'Unread one', read: false, timestamp: '2026-06-28T00:02:00.000Z'},
        {id: 'r', message: 'Read one', read: true, timestamp: '2026-06-28T00:01:00.000Z'}
      ]
    });
    const {user} = renderPage();
    await waitFor(() => expect(screen.getByText('Read one')).toBeInTheDocument());
    expect(screen.getByText(/1–2 of 2/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: /^unread$/i}));
    expect(screen.queryByText('Read one')).not.toBeInTheDocument();
    expect(screen.getByText('Unread one')).toBeInTheDocument();
    expect(screen.getByText(/1–1 of 1/)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /^unread$/i})).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows "No unread notifications." when the Unread filter has nothing (and Mark all read is disabled)', async () => {
    mockGet.mockResolvedValue({success: true, data: list(2, {read: true})});
    const {user} = renderPage();
    await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());
    expect(screen.getByRole('button', {name: 'Mark all read'})).toBeDisabled();

    await user.click(screen.getByRole('button', {name: /^unread$/i}));
    expect(screen.getByText('No unread notifications.')).toBeInTheDocument();
    expect(screen.queryByText('Message 0')).not.toBeInTheDocument();
  });
});
