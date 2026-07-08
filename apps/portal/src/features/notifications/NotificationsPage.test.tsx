import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {render, screen, cleanup, fireEvent, waitFor, within} from '@testing-library/react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import type {ReactNode} from 'react';

vi.mock('../auth', () => ({useAuth: vi.fn()}));
vi.mock('../../hooks/usePageTitle', () => ({usePageTitle: vi.fn()}));
vi.mock('./notifications.service', () => ({
  getNotifications: vi.fn(),
  enqueueNotificationAction: vi.fn()
}));

import {useAuth} from '../auth';
import {getNotifications, enqueueNotificationAction} from './notifications.service';
import {NotificationsPage} from './NotificationsPage';
import type {Notification} from './notifications.types';

const mockUseAuth = vi.mocked(useAuth);
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

function renderPage() {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  const wrapper = ({children}: {children: ReactNode}) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
  return render(<NotificationsPage />, {wrapper});
}

beforeEach(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockUseAuth.mockReturnValue({user: {username: 'alice'}, status: 'authenticated'} as any);
  mockEnqueue.mockResolvedValue({success: true, data: undefined});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('NotificationsPage (SPEC-060)', () => {
  it('shows the loading state then the list', async () => {
    mockGet.mockResolvedValue({success: true, data: list(3)});
    renderPage();
    expect(screen.getByText('Loading notifications…')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());
  });

  it('shows the empty state when there are no notifications', async () => {
    mockGet.mockResolvedValue({success: true, data: []});
    renderPage();
    await waitFor(() => expect(screen.getByText('You’re all caught up')).toBeInTheDocument());
  });

  it('opts into the stacked mobile page header (SPEC-102 FR-002)', async () => {
    mockGet.mockResolvedValue({success: true, data: list(1)});
    renderPage();
    await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());
    // The PageLayout header stacks below tablet, inline at ≥ tablet.
    const header = screen.getByRole('heading', {level: 1, name: 'Notifications'}).closest('div')!.parentElement!;
    expect(header).toHaveClass('flex-col', 'tablet:flex-row');
  });

  it('shows an error state with a retry that re-reads', async () => {
    mockGet.mockResolvedValueOnce({success: false, error: {message: 'boom'}});
    renderPage();
    await waitFor(() => expect(screen.getByText('Couldn’t load notifications.')).toBeInTheDocument());

    mockGet.mockResolvedValue({success: true, data: list(1)});
    fireEvent.click(screen.getByRole('button', {name: 'Try again'}));
    await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());
  });

  it('paginates 10 per page, newest-first, with an accurate range label', async () => {
    mockGet.mockResolvedValue({success: true, data: list(25)});
    renderPage();
    await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());

    expect(screen.getByText(/1–10 of 25/)).toBeInTheDocument();
    expect(screen.queryByText('Message 10')).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Prev'})).toBeDisabled();

    fireEvent.click(screen.getByRole('button', {name: 'Next'}));
    expect(screen.getByText(/11–20 of 25/)).toBeInTheDocument();
    expect(screen.getByText('Message 10')).toBeInTheDocument();
  });

  it('mark-all-read is disabled when nothing is unread', async () => {
    mockGet.mockResolvedValue({success: true, data: list(2, {read: true})});
    renderPage();
    await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());
    expect(screen.getByRole('button', {name: 'Mark all read'})).toBeDisabled();
  });

  it('mark read enqueues and optimistically clears the row marker', async () => {
    mockGet.mockResolvedValue({success: true, data: list(2)});
    renderPage();
    await waitFor(() => expect(screen.getAllByRole('button', {name: 'Mark read'})).toHaveLength(2));

    const firstRow = screen.getByText('Message 0').closest('li')!;
    fireEvent.click(within(firstRow).getByRole('button', {name: 'Mark read'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledWith({action: 'markRead', username: 'alice', id: 'n0'}));
    await waitFor(() => expect(screen.getAllByRole('button', {name: 'Mark read'})).toHaveLength(1));
  });

  it('mark all read enqueues, clears all markers, and disables the control', async () => {
    mockGet.mockResolvedValue({success: true, data: list(3)});
    renderPage();
    await waitFor(() => expect(screen.getAllByRole('button', {name: 'Mark read'})).toHaveLength(3));

    fireEvent.click(screen.getByRole('button', {name: 'Mark all read'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledWith({action: 'markAllRead', username: 'alice'}));
    await waitFor(() => expect(screen.queryByRole('button', {name: 'Mark read'})).not.toBeInTheDocument());
    expect(screen.getByRole('button', {name: 'Mark all read'})).toBeDisabled();
  });

  it('the Unread filter hides read notifications and re-pages the list', async () => {
    mockGet.mockResolvedValue({
      success: true,
      data: [
        {id: 'u', message: 'Unread one', read: false, timestamp: '2026-06-28T00:02:00.000Z'},
        {id: 'r', message: 'Read one', read: true, timestamp: '2026-06-28T00:01:00.000Z'}
      ]
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('Read one')).toBeInTheDocument());
    expect(screen.getByText(/1–2 of 2/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: /^unread$/i}));
    expect(screen.queryByText('Read one')).not.toBeInTheDocument();
    expect(screen.getByText('Unread one')).toBeInTheDocument();
    expect(screen.getByText(/1–1 of 1/)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /^unread$/i})).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows "No unread notifications." when the Unread filter has nothing', async () => {
    mockGet.mockResolvedValue({success: true, data: list(2, {read: true})});
    renderPage();
    await waitFor(() => expect(screen.getByText('Message 0')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', {name: /^unread$/i}));
    expect(screen.getByText('No unread notifications.')).toBeInTheDocument();
    expect(screen.queryByText('Message 0')).not.toBeInTheDocument();
  });

  it('rolls back and shows a danger toast when an action fails', async () => {
    mockGet.mockResolvedValue({success: true, data: list(1)});
    mockEnqueue.mockResolvedValue({success: false, error: {message: 'queue down'}});
    renderPage();
    await waitFor(() => expect(screen.getByRole('button', {name: 'Mark read'})).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', {name: 'Mark read'}));

    await waitFor(() => expect(screen.getByText('queue down')).toBeInTheDocument());
    // rolled back — the unread row (and its Mark read control) is still present.
    expect(screen.getByRole('button', {name: 'Mark read'})).toBeInTheDocument();
  });
});
