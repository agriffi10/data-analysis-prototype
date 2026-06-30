import {describe, it, expect, vi, beforeEach, type MockedFunction} from 'vitest';
import {render, screen, fireEvent, waitFor, within} from '@testing-library/react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import type {ReactNode} from 'react';

vi.mock('../auth', () => ({useAuth: vi.fn()}));
vi.mock('./sharedSpaces.service', () => ({
  enqueueSharedSpaceRequest: vi.fn(),
  readSharedConnectionsCache: vi.fn()
}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn(),
  getIdToken: vi.fn()
}));

import {useAuth} from '../auth';
import {enqueueSharedSpaceRequest, readSharedConnectionsCache} from './sharedSpaces.service';
import {getSessionCredentials} from '../../lib/awsCredentials';
import {ConnectionsPage} from './ConnectionsPage';
import type {SharedConnectionsCache} from './sharedSpaces.types';

const mockUseAuth = useAuth as unknown as MockedFunction<() => unknown>;
const mockEnqueue = enqueueSharedSpaceRequest as unknown as MockedFunction<(...args: unknown[]) => Promise<unknown>>;
const mockRead = readSharedConnectionsCache as unknown as MockedFunction<(u: string) => Promise<unknown>>;
const mockForceRefresh = getSessionCredentials as unknown as MockedFunction<(f?: boolean) => Promise<unknown>>;

function cache(connections: SharedConnectionsCache['connections']): {success: true; data: SharedConnectionsCache} {
  return {success: true, data: {version: 1, connections}};
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {queries: {retry: false}}
  });
  const wrapper = ({children}: {children: ReactNode}) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<ConnectionsPage />, {wrapper});
}

beforeEach(() => {
  vi.clearAllMocks();
  mockUseAuth.mockReturnValue({user: {username: 'alice'}});
  mockForceRefresh.mockResolvedValue({success: true, data: {}});
});

describe('ConnectionsPage (SPEC-052)', () => {
  it('shows the empty state when the cache has no shared connections', async () => {
    mockRead.mockResolvedValue(cache([]));
    renderPage();
    expect(await screen.findByText(/No shared connections yet/)).toBeInTheDocument();
  });

  it('lists shared connections with role + status from the cache', async () => {
    mockRead.mockResolvedValue(
      cache([
        {name: 'sales', role: 'owner', status: 'active'},
        {name: 'ops', role: 'member', status: 'provisioning'}
      ])
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
    mockRead.mockResolvedValue({success: false, error: {message: 'boom'}});
    renderPage();
    expect(await screen.findByText(/Couldn.t load/)).toHaveTextContent('boom');
    expect(screen.getByRole('button', {name: 'New shared connection'})).toBeInTheDocument();
  });

  it('Refresh forces a credential refresh then re-reads, picking up a now-active connection', async () => {
    mockRead.mockResolvedValueOnce(cache([]));
    renderPage();
    expect(await screen.findByText(/No shared connections yet/)).toBeInTheDocument();

    mockRead.mockResolvedValueOnce(cache([{name: 'team', role: 'owner', status: 'active'}]));
    fireEvent.click(screen.getByRole('button', {name: 'Refresh connections'}));

    expect(mockForceRefresh).toHaveBeenCalledWith(true);
    expect(await screen.findByText('team')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('a failed entry shows its reason with Dismiss (removes) and Retry (re-enqueues)', async () => {
    mockRead.mockResolvedValue(cache([{name: 'broken', role: 'owner', status: 'failed', reason: 'name taken'}]));
    mockEnqueue.mockResolvedValue({success: true, data: {requestId: 'r1'}});
    renderPage();

    const row = (await screen.findByText('broken')).closest('li')!;
    expect(within(row).getByText('name taken')).toBeInTheDocument();

    // Retry re-enqueues a create and flips the row to provisioning optimistically.
    fireEvent.click(within(row).getByRole('button', {name: 'Retry'}));
    await waitFor(() =>
      expect(mockEnqueue).toHaveBeenCalledWith(expect.objectContaining({action: 'create', space: 'broken'}))
    );
    expect(within(row).getByText('Provisioning…')).toBeInTheDocument();
  });

  it('Dismiss removes a failed entry from the list', async () => {
    mockRead.mockResolvedValue(cache([{name: 'broken', role: 'owner', status: 'failed', reason: 'x'}]));
    renderPage();
    const row = (await screen.findByText('broken')).closest('li')!;
    fireEvent.click(within(row).getByRole('button', {name: 'Dismiss'}));
    await waitFor(() => expect(screen.queryByText('broken')).not.toBeInTheDocument());
  });

  it('create enqueues one request and shows an optimistic pending entry + toast', async () => {
    mockRead.mockResolvedValue(cache([]));
    mockEnqueue.mockResolvedValue({success: true, data: {requestId: 'r1'}});
    renderPage();
    await screen.findByText(/No shared connections yet/);

    fireEvent.click(screen.getByRole('button', {name: 'New shared connection'}));
    fireEvent.change(screen.getByLabelText('Connection name'), {
      target: {value: 'sales_data'}
    });
    fireEvent.click(screen.getByRole('button', {name: 'Create'}));

    await waitFor(() => expect(screen.getByText(/Creating .*sales_data/)).toBeInTheDocument());
    expect(mockEnqueue).toHaveBeenCalledTimes(1);
    expect(screen.getByText('sales_data')).toBeInTheDocument();
    expect(screen.getByText('Provisioning…')).toBeInTheDocument();
  });
});

describe('ConnectionsPage — Manage members (SPEC-053)', () => {
  it('shows Manage only on an active connection the user owns, and opens the drawer', async () => {
    mockRead.mockResolvedValue(
      cache([
        {name: 'owned', role: 'owner', status: 'active', members: ['alice', 'bob']},
        {name: 'joined', role: 'member', status: 'active'},
        {name: 'pending', role: 'owner', status: 'provisioning'}
      ])
    );
    renderPage();

    const owned = (await screen.findByText('owned')).closest('li')!;
    expect(within(owned).getByRole('button', {name: 'Manage'})).toBeEnabled();
    // No Manage for a space the user only belongs to.
    expect(
      within(screen.getByText('joined').closest('li')!).queryByRole('button', {
        name: 'Manage'
      })
    ).not.toBeInTheDocument();
    // A still-provisioning owned space shows Manage, but disabled (design parity).
    expect(
      within(screen.getByText('pending').closest('li')!).getByRole('button', {
        name: 'Manage'
      })
    ).toBeDisabled();

    fireEvent.click(within(owned).getByRole('button', {name: 'Manage'}));
    const drawer = screen.getByRole('dialog', {name: 'Manage members'});
    expect(within(drawer).getByText('bob')).toBeInTheDocument();
  });

  it('adding a member from the drawer enqueues one add_members request', async () => {
    mockRead.mockResolvedValue(cache([{name: 'owned', role: 'owner', status: 'active', members: ['alice']}]));
    mockEnqueue.mockResolvedValue({success: true, data: {requestId: 'r1'}});
    renderPage();

    const owned = (await screen.findByText('owned')).closest('li')!;
    fireEvent.click(within(owned).getByRole('button', {name: 'Manage'}));
    fireEvent.click(screen.getByRole('button', {name: 'Add members'}));
    fireEvent.change(screen.getByLabelText('Usernames'), {
      target: {value: 'bob'}
    });
    fireEvent.click(screen.getByRole('button', {name: 'Add'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
    expect(mockEnqueue).toHaveBeenCalledWith({
      action: 'add_members',
      actor: 'alice',
      space: 'owned',
      payload: {members: ['bob']}
    });
  });
});

describe('ConnectionsPage — Leave & Delete (SPEC-054)', () => {
  it('offers Leave (not Delete/Manage) to a member, enqueues one leave request, shows leaving', async () => {
    mockRead.mockResolvedValue(cache([{name: 'joined', role: 'member', status: 'active'}]));
    mockEnqueue.mockResolvedValue({success: true, data: {requestId: 'r1'}});
    renderPage();

    const row = (await screen.findByText('joined')).closest('li')!;
    expect(within(row).getByRole('button', {name: 'Leave'})).toBeInTheDocument();
    expect(within(row).queryByRole('button', {name: 'Delete'})).not.toBeInTheDocument();
    expect(within(row).queryByRole('button', {name: 'Manage'})).not.toBeInTheDocument();

    fireEvent.click(within(row).getByRole('button', {name: 'Leave'}));
    const dialog = screen.getByRole('alertdialog', {name: 'Leave joined'});
    fireEvent.click(within(dialog).getByRole('button', {name: 'Leave'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
    expect(mockEnqueue).toHaveBeenCalledWith({action: 'leave', actor: 'alice', space: 'joined'});
    expect(within(row).getByText('Leaving…')).toBeInTheDocument();
  });

  it('offers Delete (not Leave) to an owner; the type-the-name guard gates the destructive button', async () => {
    mockRead.mockResolvedValue(cache([{name: 'owned', role: 'owner', status: 'active', members: ['alice']}]));
    mockEnqueue.mockResolvedValue({success: true, data: {requestId: 'r1'}});
    renderPage();

    const row = (await screen.findByText('owned')).closest('li')!;
    expect(within(row).getByRole('button', {name: 'Delete'})).toBeInTheDocument();
    expect(within(row).queryByRole('button', {name: 'Leave'})).not.toBeInTheDocument();

    fireEvent.click(within(row).getByRole('button', {name: 'Delete'}));
    const dialog = screen.getByRole('alertdialog', {name: 'Delete owned'});
    const confirm = within(dialog).getByRole('button', {name: 'Delete'});
    expect(confirm).toBeDisabled();

    // Wrong text keeps it disabled; the exact name enables it.
    const field = within(dialog).getByLabelText(/to confirm/);
    fireEvent.change(field, {target: {value: 'owne'}});
    expect(confirm).toBeDisabled();
    fireEvent.change(field, {target: {value: 'owned'}});
    expect(confirm).toBeEnabled();

    fireEvent.click(confirm);
    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
    expect(mockEnqueue).toHaveBeenCalledWith({action: 'delete', actor: 'alice', space: 'owned'});
    expect(within(row).getByText('Deleting…')).toBeInTheDocument();
  });

  it('offers neither Leave nor Delete on a non-active connection', async () => {
    mockRead.mockResolvedValue(
      cache([
        {name: 'pending', role: 'owner', status: 'provisioning'},
        {name: 'joining', role: 'member', status: 'provisioning'}
      ])
    );
    renderPage();

    const pending = (await screen.findByText('pending')).closest('li')!;
    expect(within(pending).queryByRole('button', {name: 'Delete'})).not.toBeInTheDocument();
    const joining = screen.getByText('joining').closest('li')!;
    expect(within(joining).queryByRole('button', {name: 'Leave'})).not.toBeInTheDocument();
  });
});
