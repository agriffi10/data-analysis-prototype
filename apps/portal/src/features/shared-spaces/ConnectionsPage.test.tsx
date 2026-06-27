import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  type MockedFunction,
} from 'vitest';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

vi.mock('../auth', () => ({ useAuth: vi.fn() }));
vi.mock('./sharedSpaces.service', () => ({
  enqueueSharedSpaceRequest: vi.fn(),
  readSharedConnectionsCache: vi.fn(),
}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn(),
  getIdToken: vi.fn(),
}));

import { useAuth } from '../auth';
import {
  enqueueSharedSpaceRequest,
  readSharedConnectionsCache,
} from './sharedSpaces.service';
import { getSessionCredentials } from '../../lib/awsCredentials';
import { ConnectionsPage } from './ConnectionsPage';
import type { SharedConnectionsCache } from './sharedSpaces.types';

const mockUseAuth = useAuth as unknown as MockedFunction<() => unknown>;
const mockEnqueue = enqueueSharedSpaceRequest as unknown as MockedFunction<
  (...args: unknown[]) => Promise<unknown>
>;
const mockRead = readSharedConnectionsCache as unknown as MockedFunction<
  (u: string) => Promise<unknown>
>;
const mockForceRefresh = getSessionCredentials as unknown as MockedFunction<
  (f?: boolean) => Promise<unknown>
>;

function cache(
  connections: SharedConnectionsCache['connections'],
): { success: true; data: SharedConnectionsCache } {
  return { success: true, data: { version: 1, connections } };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<ConnectionsPage />, { wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockUseAuth.mockReturnValue({ user: { username: 'alice' } });
  mockForceRefresh.mockResolvedValue({ success: true, data: {} });
});

describe('ConnectionsPage (SPEC-052)', () => {
  it('shows the empty state when the cache has no shared connections', async () => {
    mockRead.mockResolvedValue(cache([]));
    renderPage();
    expect(
      await screen.findByText(/No shared connections yet/),
    ).toBeInTheDocument();
  });

  it('lists shared connections with role + status from the cache', async () => {
    mockRead.mockResolvedValue(
      cache([
        { name: 'sales', role: 'owner', status: 'active' },
        { name: 'ops', role: 'member', status: 'provisioning' },
      ]),
    );
    renderPage();

    const sales = (await screen.findByText('sales')).closest('li')!;
    expect(within(sales).getByText('owner')).toBeInTheDocument();
    expect(within(sales).getByText('Active')).toBeInTheDocument();

    const ops = screen.getByText('ops').closest('li')!;
    expect(within(ops).getByText('member')).toBeInTheDocument();
    expect(within(ops).getByText('Provisioning…')).toBeInTheDocument();
  });

  it('shows a Banner on a read error without crashing (create stays available)', async () => {
    mockRead.mockResolvedValue({ success: false, error: { message: 'boom' } });
    renderPage();
    expect(await screen.findByText(/Couldn.t load/)).toHaveTextContent('boom');
    expect(
      screen.getByRole('button', { name: 'New shared connection' }),
    ).toBeInTheDocument();
  });

  it('Refresh forces a credential refresh then re-reads, picking up a now-active connection', async () => {
    mockRead.mockResolvedValueOnce(cache([]));
    renderPage();
    expect(
      await screen.findByText(/No shared connections yet/),
    ).toBeInTheDocument();

    mockRead.mockResolvedValueOnce(
      cache([{ name: 'team', role: 'owner', status: 'active' }]),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Refresh connections' }));

    expect(mockForceRefresh).toHaveBeenCalledWith(true);
    expect(await screen.findByText('team')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('a failed entry shows its reason with Dismiss (removes) and Retry (re-enqueues)', async () => {
    mockRead.mockResolvedValue(
      cache([
        { name: 'broken', role: 'owner', status: 'failed', reason: 'name taken' },
      ]),
    );
    mockEnqueue.mockResolvedValue({ success: true, data: { requestId: 'r1' } });
    renderPage();

    const row = (await screen.findByText('broken')).closest('li')!;
    expect(within(row).getByText('name taken')).toBeInTheDocument();

    // Retry re-enqueues a create and flips the row to provisioning optimistically.
    fireEvent.click(within(row).getByRole('button', { name: 'Retry' }));
    await waitFor(() =>
      expect(mockEnqueue).toHaveBeenCalledWith(
        expect.objectContaining({ action: 'create', space: 'broken' }),
      ),
    );
    expect(within(row).getByText('Provisioning…')).toBeInTheDocument();
  });

  it('Dismiss removes a failed entry from the list', async () => {
    mockRead.mockResolvedValue(
      cache([{ name: 'broken', role: 'owner', status: 'failed', reason: 'x' }]),
    );
    renderPage();
    const row = (await screen.findByText('broken')).closest('li')!;
    fireEvent.click(within(row).getByRole('button', { name: 'Dismiss' }));
    await waitFor(() =>
      expect(screen.queryByText('broken')).not.toBeInTheDocument(),
    );
  });

  it('create enqueues one request and shows an optimistic pending entry + toast', async () => {
    mockRead.mockResolvedValue(cache([]));
    mockEnqueue.mockResolvedValue({ success: true, data: { requestId: 'r1' } });
    renderPage();
    await screen.findByText(/No shared connections yet/);

    fireEvent.click(
      screen.getByRole('button', { name: 'New shared connection' }),
    );
    fireEvent.change(screen.getByLabelText('Connection name'), {
      target: { value: 'sales_data' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() =>
      expect(screen.getByText(/Creating .*sales_data/)).toBeInTheDocument(),
    );
    expect(mockEnqueue).toHaveBeenCalledTimes(1);
    expect(screen.getByText('sales_data')).toBeInTheDocument();
    expect(screen.getByText('Provisioning…')).toBeInTheDocument();
  });
});

describe('ConnectionsPage — Manage members (SPEC-053)', () => {
  it('shows Manage only on an active connection the user owns, and opens the drawer', async () => {
    mockRead.mockResolvedValue(
      cache([
        { name: 'owned', role: 'owner', status: 'active', members: ['alice', 'bob'] },
        { name: 'joined', role: 'member', status: 'active' },
        { name: 'pending', role: 'owner', status: 'provisioning' },
      ]),
    );
    renderPage();

    const owned = (await screen.findByText('owned')).closest('li')!;
    expect(within(owned).getByRole('button', { name: 'Manage' })).toBeInTheDocument();
    // No Manage for a space the user only belongs to, or one still provisioning.
    expect(
      within(screen.getByText('joined').closest('li')!).queryByRole('button', {
        name: 'Manage',
      }),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByText('pending').closest('li')!).queryByRole('button', {
        name: 'Manage',
      }),
    ).not.toBeInTheDocument();

    fireEvent.click(within(owned).getByRole('button', { name: 'Manage' }));
    const drawer = screen.getByRole('dialog', { name: 'Manage members' });
    expect(within(drawer).getByText('bob')).toBeInTheDocument();
  });

  it('adding a member from the drawer enqueues one add_members request', async () => {
    mockRead.mockResolvedValue(
      cache([{ name: 'owned', role: 'owner', status: 'active', members: ['alice'] }]),
    );
    mockEnqueue.mockResolvedValue({ success: true, data: { requestId: 'r1' } });
    renderPage();

    const owned = (await screen.findByText('owned')).closest('li')!;
    fireEvent.click(within(owned).getByRole('button', { name: 'Manage' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add members' }));
    fireEvent.change(screen.getByLabelText('Usernames'), {
      target: { value: 'bob' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
    expect(mockEnqueue).toHaveBeenCalledWith({
      action: 'add_members',
      actor: 'alice',
      space: 'owned',
      payload: { members: ['bob'] },
    });
  });
});
