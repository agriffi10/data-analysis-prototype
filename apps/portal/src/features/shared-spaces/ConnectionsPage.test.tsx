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

  it('Dismiss durably clears a failed entry (enqueues forget) and removes it from the list', async () => {
    mockRead.mockResolvedValue(cache([{name: 'broken', role: 'owner', status: 'failed', reason: 'x'}]));
    mockEnqueue.mockResolvedValue({success: true, data: {requestId: 'r1'}});
    renderPage();
    const row = (await screen.findByText('broken')).closest('li')!;
    fireEvent.click(within(row).getByRole('button', {name: 'Dismiss'}));
    await waitFor(() => expect(screen.queryByText('broken')).not.toBeInTheDocument());
    // Durable, not just a local hide: a `forget` request is enqueued for the entry.
    expect(mockEnqueue).toHaveBeenCalledWith(expect.objectContaining({action: 'forget', space: 'broken'}));
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
        {
          name: 'owned',
          role: 'owner',
          status: 'active',
          members: [
            {username: 'alice', status: 'active'},
            {username: 'bob', status: 'active'}
          ]
        },
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
    mockRead.mockResolvedValue(
      cache([{name: 'owned', role: 'owner', status: 'active', members: [{username: 'alice', status: 'active'}]}])
    );
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
    mockRead.mockResolvedValue(
      cache([{name: 'owned', role: 'owner', status: 'active', members: [{username: 'alice', status: 'active'}]}])
    );
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

  it('offers View members to a member and opens a read-only roster (SPEC-075)', async () => {
    mockUseAuth.mockReturnValue({user: {username: 'bob'}});
    mockRead.mockResolvedValue(
      cache([
        {
          name: 'joined',
          role: 'member',
          status: 'active',
          owner: 'alice',
          members: [
            {username: 'alice', status: 'active'},
            {username: 'bob', status: 'pending'}
          ]
        }
      ])
    );
    renderPage();

    const row = (await screen.findByText('joined')).closest('li')!;
    fireEvent.click(within(row).getByRole('button', {name: 'View members'}));

    const drawer = screen.getByRole('dialog', {name: 'View members'});
    expect(within(drawer).getByText('alice')).toBeInTheDocument();
    expect(within(drawer).getByText('Owner')).toBeInTheDocument();
    expect(within(drawer).getByText('bob')).toBeInTheDocument();
    // Read-only: no management controls.
    expect(within(drawer).queryByRole('button', {name: 'Remove'})).not.toBeInTheDocument();
    expect(within(drawer).queryByRole('button', {name: /Add members/})).not.toBeInTheDocument();
  });

  it('a member with a legacy entry (no roster) sees the not-available note (SPEC-075)', async () => {
    mockUseAuth.mockReturnValue({user: {username: 'bob'}});
    mockRead.mockResolvedValue(cache([{name: 'joined', role: 'member', status: 'active', owner: 'alice'}]));
    renderPage();

    const row = (await screen.findByText('joined')).closest('li')!;
    fireEvent.click(within(row).getByRole('button', {name: 'View members'}));
    expect(screen.getByText(/member list isn.t available yet/i)).toBeInTheDocument();
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

// ─── SPEC-101: responsive reflow ─────────────────────────────────────────────

describe('ConnectionsPage responsive reflow (SPEC-101)', () => {
  it('stacks the card on mobile and rows it at ≥ tablet', async () => {
    mockRead.mockResolvedValue(cache([{name: 'sales', role: 'owner', status: 'active'}]));
    renderPage();
    const li = (await screen.findByText('sales')).closest('li')!;
    expect(li).toHaveClass('flex-col', 'tablet:flex-row');
  });

  it('renders two active-owner actions as a full-width 50/50 grid on mobile', async () => {
    mockRead.mockResolvedValue(cache([{name: 'sales', role: 'owner', status: 'active'}]));
    renderPage();
    const manage = await screen.findByRole('button', {name: 'Manage'});
    expect(manage.parentElement).toHaveClass('grid-cols-2', 'w-full', 'tablet:flex');
    expect(manage).toHaveClass('w-full', 'tablet:w-auto');
  });

  it('renders a single provisioning-owner action full-width on mobile', async () => {
    mockRead.mockResolvedValue(cache([{name: 'ops', role: 'owner', status: 'provisioning'}]));
    renderPage();
    const manage = await screen.findByRole('button', {name: 'Manage'});
    expect(manage).toBeDisabled();
    expect(manage.parentElement).toHaveClass('grid-cols-1');
  });

  it('stacks pills under the name on mobile (inline at ≥ tablet)', async () => {
    mockRead.mockResolvedValue(cache([{name: 'sales', role: 'owner', status: 'active'}]));
    renderPage();
    const nameRow = (await screen.findByText('sales')).parentElement!;
    expect(nameRow).toHaveClass('flex-col', 'tablet:flex-row');
  });

  it('shortens the New button label but keeps its full accessible name', async () => {
    mockRead.mockResolvedValue(cache([]));
    renderPage();
    await screen.findByText(/No shared connections yet/);
    const newBtn = screen.getByRole('button', {name: 'New shared connection'});
    expect(newBtn).toHaveClass('w-full', 'tablet:w-auto');
    expect(within(newBtn).getByText('New')).toHaveClass('desktop:hidden');
    expect(within(newBtn).getByText('New shared connection')).toHaveClass('hidden', 'desktop:inline');
  });

  it('opts the page header into the stacked mobile layout', async () => {
    mockRead.mockResolvedValue(cache([]));
    renderPage();
    await screen.findByText(/No shared connections yet/);
    const header = screen.getByRole('heading', {level: 1, name: 'Shared connections'}).closest('div')!.parentElement!;
    expect(header).toHaveClass('flex-col', 'tablet:flex-row');
  });

  it('opens Manage as a full-height sheet variant (FR-005)', async () => {
    mockRead.mockResolvedValue(
      cache([{name: 'sales', role: 'owner', status: 'active', members: [{username: 'alice', status: 'active'}]}])
    );
    renderPage();
    fireEvent.click(await screen.findByRole('button', {name: 'Manage'}));
    const dialog = await screen.findByRole('dialog', {name: 'Manage members'});
    // full-height variant → h-full, not the bottom-sheet's rounded top.
    expect(dialog).toHaveClass('h-full');
    expect(dialog).not.toHaveClass('rounded-t-xl');
  });
});
