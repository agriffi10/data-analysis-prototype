import {describe, it, expect, vi, beforeEach, type MockedFunction} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import type {AuthContextValue} from '../auth';

// Integration style (react.md §21): render the REAL ConnectionsPage with its real
// hooks (useConnections/useCreateSharedConnection/useManageMembers/…) and real child
// dialogs (Create/Manage/Roster/Leave/Delete). Mock ONLY the AWS boundary: the
// shared-spaces service (SQS enqueue + cache read) and the credential vend the
// Refresh/reconcile path re-mints. Auth is injected via the harness, never mocked.
vi.mock('./sharedSpaces.service', () => ({
  enqueueSharedSpaceRequest: vi.fn(),
  readSharedConnectionsCache: vi.fn()
}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn(),
  getIdToken: vi.fn()
}));

import {enqueueSharedSpaceRequest, readSharedConnectionsCache} from './sharedSpaces.service';
import {getSessionCredentials} from '../../lib/awsCredentials';
import {ConnectionsPage} from './ConnectionsPage';
import type {SharedConnectionsCache} from './sharedSpaces.types';

const mockEnqueue = enqueueSharedSpaceRequest as unknown as MockedFunction<(...args: unknown[]) => Promise<unknown>>;
const mockRead = readSharedConnectionsCache as unknown as MockedFunction<(u: string) => Promise<unknown>>;
const mockForceRefresh = getSessionCredentials as unknown as MockedFunction<(f?: boolean) => Promise<unknown>>;

function cache(connections: SharedConnectionsCache['connections']): {success: true; data: SharedConnectionsCache} {
  return {success: true, data: {version: 1, connections}};
}

function renderPage(auth: AuthContextValue = authenticated('alice')): ReturnType<typeof renderWithProviders> {
  return renderWithProviders(<ConnectionsPage />, {auth});
}

/** The `<li>` card for a connection named `name`. */
const rowFor = async (name: string): Promise<HTMLElement> => (await screen.findByText(name)).closest('li')!;

beforeEach(() => {
  vi.clearAllMocks();
  mockForceRefresh.mockResolvedValue({success: true, data: {}});
  mockEnqueue.mockResolvedValue({success: true, data: {requestId: 'r1'}});
});

describe('ConnectionsPage — listing & create (SPEC-052)', () => {
  it('shows the empty state when the cache has no shared connections', async () => {
    mockRead.mockResolvedValue(cache([]));
    renderPage();
    expect(await screen.findByText(/No shared connections yet/)).toBeInTheDocument();
  });

  it('lists shared connections with their role + status from the cache', async () => {
    mockRead.mockResolvedValue(
      cache([
        {name: 'sales', role: 'owner', status: 'active'},
        {name: 'ops', role: 'member', status: 'provisioning'}
      ])
    );
    renderPage();

    const sales = await rowFor('sales');
    expect(within(sales).getByText('owner')).toBeInTheDocument();
    expect(within(sales).getByText('Active')).toBeInTheDocument();

    const ops = await rowFor('ops');
    expect(within(ops).getByText('member')).toBeInTheDocument();
    expect(within(ops).getByText('Provisioning…')).toBeInTheDocument();
  });

  it('shows a Banner on a read error without crashing (create stays available)', async () => {
    mockRead.mockResolvedValue({success: false, error: {message: 'boom'}});
    renderPage();
    // Friendly, actionable text — never the raw service message (SPEC-106).
    const banner = await screen.findByText(/Couldn.t load your shared connections/);
    expect(banner).not.toHaveTextContent('boom');
    expect(screen.getByRole('button', {name: 'New shared connection'})).toBeInTheDocument();
  });

  it('Refresh forces a credential refresh then re-reads, picking up a now-active connection', async () => {
    mockRead.mockResolvedValueOnce(cache([]));
    const {user} = renderPage();
    expect(await screen.findByText(/No shared connections yet/)).toBeInTheDocument();

    mockRead.mockResolvedValueOnce(cache([{name: 'team', role: 'owner', status: 'active'}]));
    await user.click(screen.getByRole('button', {name: 'Refresh connections'}));

    expect(mockForceRefresh).toHaveBeenCalledWith(true);
    expect(await screen.findByText('team')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('create enqueues one request and shows an optimistic pending entry + toast', async () => {
    mockRead.mockResolvedValue(cache([]));
    const {user} = renderPage();
    await screen.findByText(/No shared connections yet/);

    await user.click(screen.getByRole('button', {name: 'New shared connection'}));
    const dialog = await screen.findByRole('dialog', {name: 'Create shared connection'});
    await user.type(within(dialog).getByLabelText('Connection name'), 'sales_data');
    await user.click(within(dialog).getByRole('button', {name: 'Create'}));

    await waitFor(() => expect(screen.getByText(/Creating .*sales_data/)).toBeInTheDocument());
    expect(mockEnqueue).toHaveBeenCalledTimes(1);
    expect(mockEnqueue).toHaveBeenCalledWith(expect.objectContaining({action: 'create', space: 'sales_data'}));
    const created = await rowFor('sales_data');
    expect(within(created).getByText('Provisioning…')).toBeInTheDocument();
  });

  it('a failed entry surfaces its reason with Retry (re-enqueues, flips to provisioning) and Dismiss (durable forget, removes)', async () => {
    mockRead.mockResolvedValue(cache([{name: 'broken', role: 'owner', status: 'failed', reason: 'name taken'}]));
    const {user} = renderPage();

    const row = await rowFor('broken');
    expect(within(row).getByText('name taken')).toBeInTheDocument();

    // Retry re-enqueues a create and flips the row to provisioning optimistically.
    await user.click(within(row).getByRole('button', {name: 'Retry'}));
    await waitFor(() =>
      expect(mockEnqueue).toHaveBeenCalledWith(expect.objectContaining({action: 'create', space: 'broken'}))
    );
    expect(within(row).getByText('Provisioning…')).toBeInTheDocument();
  });

  it('Dismiss durably clears a failed entry (enqueues forget) and removes it from the list', async () => {
    mockRead.mockResolvedValue(cache([{name: 'broken', role: 'owner', status: 'failed', reason: 'x'}]));
    const {user} = renderPage();

    const row = await rowFor('broken');
    await user.click(within(row).getByRole('button', {name: 'Dismiss'}));

    await waitFor(() => expect(screen.queryByText('broken')).not.toBeInTheDocument());
    // Durable, not a local hide: a `forget` request is enqueued for the entry.
    expect(mockEnqueue).toHaveBeenCalledWith(expect.objectContaining({action: 'forget', space: 'broken'}));
  });
});

describe('ConnectionsPage — Manage members (SPEC-053)', () => {
  it('shows Manage only on an active owned space (disabled while provisioning, absent for a joined space) and opens the drawer as a full-height sheet', async () => {
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
    const {user} = renderPage();

    const owned = await rowFor('owned');
    expect(within(owned).getByRole('button', {name: 'Manage'})).toBeEnabled();
    // No Manage for a space the user only belongs to.
    expect(within(await rowFor('joined')).queryByRole('button', {name: 'Manage'})).not.toBeInTheDocument();
    // A still-provisioning owned space shows Manage, but disabled (design parity).
    expect(within(await rowFor('pending')).getByRole('button', {name: 'Manage'})).toBeDisabled();

    await user.click(within(owned).getByRole('button', {name: 'Manage'}));
    const drawer = await screen.findByRole('dialog', {name: 'Manage members'});
    expect(within(drawer).getByText('bob')).toBeInTheDocument();
    // Opens as the full-height sheet variant on small screens (SPEC-101 FR-005).
    expect(drawer).toHaveClass('h-full');
    expect(drawer).not.toHaveClass('rounded-t-xl');
  });

  it('adding a member from the drawer enqueues one add_members request', async () => {
    mockRead.mockResolvedValue(
      cache([{name: 'owned', role: 'owner', status: 'active', members: [{username: 'alice', status: 'active'}]}])
    );
    const {user} = renderPage();

    const owned = await rowFor('owned');
    await user.click(within(owned).getByRole('button', {name: 'Manage'}));
    await user.click(screen.getByRole('button', {name: 'Add members'}));
    // `{enter}` COMMITS the name as a chip; Add then submits. The field is a chips field
    // since SPEC-148, so typing alone no longer enables the submit button.
    await user.type(screen.getByLabelText('Usernames'), 'bob{enter}');
    await user.click(screen.getByRole('button', {name: 'Add'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
    expect(mockEnqueue).toHaveBeenCalledWith({
      action: 'add_members',
      actor: 'alice',
      space: 'owned',
      payload: {members: ['bob']}
    });
  });
});

describe('ConnectionsPage — Leave / Delete / View (SPEC-054 / SPEC-075)', () => {
  it('offers Leave (not Delete/Manage) to a member, enqueues one leave request, shows leaving', async () => {
    mockRead.mockResolvedValue(cache([{name: 'joined', role: 'member', status: 'active'}]));
    const {user} = renderPage();

    const row = await rowFor('joined');
    expect(within(row).getByRole('button', {name: 'Leave'})).toBeInTheDocument();
    expect(within(row).queryByRole('button', {name: 'Delete'})).not.toBeInTheDocument();
    expect(within(row).queryByRole('button', {name: 'Manage'})).not.toBeInTheDocument();

    await user.click(within(row).getByRole('button', {name: 'Leave'}));
    const dialog = await screen.findByRole('alertdialog', {name: 'Leave joined'});
    await user.click(within(dialog).getByRole('button', {name: 'Leave'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
    expect(mockEnqueue).toHaveBeenCalledWith({action: 'leave', actor: 'alice', space: 'joined'});
    expect(within(row).getByText('Leaving…')).toBeInTheDocument();
  });

  it('offers Delete (not Leave) to an owner; the type-the-name guard gates the destructive button', async () => {
    mockRead.mockResolvedValue(
      cache([{name: 'owned', role: 'owner', status: 'active', members: [{username: 'alice', status: 'active'}]}])
    );
    const {user} = renderPage();

    const row = await rowFor('owned');
    expect(within(row).getByRole('button', {name: 'Delete'})).toBeInTheDocument();
    expect(within(row).queryByRole('button', {name: 'Leave'})).not.toBeInTheDocument();

    await user.click(within(row).getByRole('button', {name: 'Delete'}));
    const dialog = await screen.findByRole('alertdialog', {name: 'Delete owned'});
    const confirm = within(dialog).getByRole('button', {name: 'Delete'});
    expect(confirm).toBeDisabled();

    // Wrong text keeps it disabled; the exact name enables it.
    const field = within(dialog).getByLabelText(/to confirm/);
    await user.type(field, 'owne');
    expect(confirm).toBeDisabled();
    await user.type(field, 'd');
    expect(confirm).toBeEnabled();

    await user.click(confirm);
    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
    expect(mockEnqueue).toHaveBeenCalledWith({action: 'delete', actor: 'alice', space: 'owned'});
    expect(within(row).getByText('Deleting…')).toBeInTheDocument();
  });

  it('offers View members to a member and opens a read-only roster (SPEC-075)', async () => {
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
    const {user} = renderPage(authenticated('bob'));

    const row = await rowFor('joined');
    await user.click(within(row).getByRole('button', {name: 'View members'}));

    const drawer = await screen.findByRole('dialog', {name: 'View members'});
    expect(within(drawer).getByText('alice')).toBeInTheDocument();
    expect(within(drawer).getByText('Owner')).toBeInTheDocument();
    expect(within(drawer).getByText('bob')).toBeInTheDocument();
    // Read-only: no management controls.
    expect(within(drawer).queryByRole('button', {name: 'Remove'})).not.toBeInTheDocument();
    expect(within(drawer).queryByRole('button', {name: /Add members/})).not.toBeInTheDocument();
  });

  it('a member with a legacy entry (no roster) sees the not-available note (SPEC-075)', async () => {
    mockRead.mockResolvedValue(cache([{name: 'joined', role: 'member', status: 'active', owner: 'alice'}]));
    const {user} = renderPage(authenticated('bob'));

    const row = await rowFor('joined');
    await user.click(within(row).getByRole('button', {name: 'View members'}));
    expect(await screen.findByText(/member list isn.t available yet/i)).toBeInTheDocument();
  });

  it('offers neither Leave nor Delete on a non-active connection', async () => {
    mockRead.mockResolvedValue(
      cache([
        {name: 'pending', role: 'owner', status: 'provisioning'},
        {name: 'joining', role: 'member', status: 'provisioning'}
      ])
    );
    renderPage();

    expect(within(await rowFor('pending')).queryByRole('button', {name: 'Delete'})).not.toBeInTheDocument();
    expect(within(await rowFor('joining')).queryByRole('button', {name: 'Leave'})).not.toBeInTheDocument();
  });
});

// ─── SPEC-101: responsive reflow (static utility-class assertions) ────────────
describe('ConnectionsPage — responsive reflow (SPEC-101)', () => {
  it('reflows cards and their actions: stacked/full-width on mobile, rowed at ≥ tablet', async () => {
    mockRead.mockResolvedValue(
      cache([
        {name: 'sales', role: 'owner', status: 'active'},
        {name: 'ops', role: 'owner', status: 'provisioning'}
      ])
    );
    renderPage();

    const sales = await rowFor('sales');
    // Card stacks on mobile, rows at ≥ tablet.
    expect(sales).toHaveClass('flex-col', 'tablet:flex-row');
    // Pills stack under the name on mobile, inline at ≥ tablet.
    expect(within(sales).getByText('sales').parentElement).toHaveClass('flex-col', 'tablet:flex-row');
    // Two active-owner actions render as a full-width 50/50 grid on mobile.
    const manage = within(sales).getByRole('button', {name: 'Manage'});
    expect(manage.parentElement).toHaveClass('grid-cols-2', 'w-full', 'tablet:flex');
    expect(manage).toHaveClass('w-full', 'tablet:w-auto');

    // A single provisioning-owner action spans the full width (grid-cols-1).
    const ops = await rowFor('ops');
    const opsManage = within(ops).getByRole('button', {name: 'Manage'});
    expect(opsManage).toBeDisabled();
    expect(opsManage.parentElement).toHaveClass('grid-cols-1');
  });

  it('stacks the page header and the New button on mobile while keeping the full accessible name', async () => {
    mockRead.mockResolvedValue(cache([]));
    renderPage();
    await screen.findByText(/No shared connections yet/);

    const header = screen.getByRole('heading', {level: 1, name: 'Shared connections'}).closest('div')!.parentElement!;
    expect(header).toHaveClass('flex-col', 'tablet:flex-row');

    const newBtn = screen.getByRole('button', {name: 'New shared connection'});
    expect(newBtn).toHaveClass('w-full', 'tablet:w-auto');
    expect(within(newBtn).getByText('New')).toHaveClass('desktop:hidden');
    expect(within(newBtn).getByText('New shared connection')).toHaveClass('hidden', 'desktop:inline');
  });
});
