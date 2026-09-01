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
vi.mock('../../lib/idToken', () => ({getIdToken: vi.fn()}));

import {enqueueSharedSpaceRequest, readSharedConnectionsCache} from './sharedSpaces.service';
import {getIdToken} from '../../lib/idToken';
import {ConnectionsPage} from './ConnectionsPage';
import type {SharedConnectionsCache} from './sharedSpaces.types';

const mockEnqueue = enqueueSharedSpaceRequest as unknown as MockedFunction<(...args: unknown[]) => Promise<unknown>>;
const mockRead = readSharedConnectionsCache as unknown as MockedFunction<(u: string) => Promise<unknown>>;
const mockForceRefresh = getIdToken as unknown as MockedFunction<(f?: boolean) => Promise<unknown>>;

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

  // SPEC-154 FR-006: removal was the one member action with no path from the drawer to the
  // service. The FR names why it is worth driving: the request carries `managing.name` from a
  // CLOSURE, and a closure over the wrong space removes someone from a space the user did not
  // choose. That cannot go wrong with one space in the fixture, so there are two.
  it('removing a member from the drawer enqueues remove_members for the space being managed', async () => {
    mockRead.mockResolvedValue(
      cache([
        {
          name: 'first',
          role: 'owner',
          status: 'active',
          members: [
            {username: 'alice', status: 'active'},
            {username: 'bob', status: 'active'}
          ]
        },
        {
          name: 'second',
          role: 'owner',
          status: 'active',
          members: [
            {username: 'alice', status: 'active'},
            {username: 'bob', status: 'active'}
          ]
        }
      ])
    );
    const {user} = renderPage();

    // Manage the SECOND space, so a closure that captured the first — or the list's head —
    // sends the request against the wrong name and fails here.
    await user.click(within(await rowFor('second')).getByRole('button', {name: 'Manage'}));
    const drawer = await screen.findByRole('dialog', {name: 'Manage members'});
    await user.click(within(drawer).getByRole('button', {name: 'Remove bob'}));

    const confirm = await screen.findByRole('alertdialog', {name: 'Remove bob'});
    await user.click(within(confirm).getByRole('button', {name: 'Remove'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
    expect(mockEnqueue).toHaveBeenCalledWith({
      action: 'remove_members',
      actor: 'alice',
      space: 'second',
      payload: {members: ['bob']}
    });
  });

  it('offers no Remove against the owner', async () => {
    // The owner cannot be removed from their own space, and the drawer is where that would
    // be gotten wrong — MembersList only renders Remove for non-owners.
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
        }
      ])
    );
    const {user} = renderPage();

    await user.click(within(await rowFor('owned')).getByRole('button', {name: 'Manage'}));
    const drawer = await screen.findByRole('dialog', {name: 'Manage members'});

    expect(within(drawer).queryByRole('button', {name: 'Remove alice'})).not.toBeInTheDocument();
    expect(within(drawer).getByRole('button', {name: 'Remove bob'})).toBeInTheDocument();
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
    expect(within(drawer).queryByRole('button', {name: /Remove/})).not.toBeInTheDocument();
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
    // CLASS ASSERTIONS KEPT, with the reason FR-009 requires: SPEC-095's "reflow on ONE tree"
    // is a documented constraint whose whole content is which utility classes the single tree
    // carries. jsdom applies no media queries, so there is nothing rendered to observe and no
    // accessible equivalent to assert — the alternative is not a better test, it is no test.
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

    // RESTORED after review, and the reasoning that removed it was wrong: `PageLayout.test.tsx`
    // asserts this stacking only in a render that passes `stackActionsOnMobile` ITSELF, and the
    // prop defaults to false — so it owns "the prop works", never "ConnectionsPage opts in".
    // Deleting this left `ConnectionsPage.tsx`'s bare `stackActionsOnMobile` pinned nowhere: a
    // tidy-up that dropped the prop would keep both files green while the heading and the New
    // button collide at 400px.
    //
    // The DOM chain stays, which is FR-009 AC3 yielding to AC5 (no coverage decrease): the node
    // is a layout `<div>` with no role, label or landmark, so there is nothing to query it by,
    // and a worse test is not an improvement on a slightly ugly one.
    const header = screen.getByRole('heading', {level: 1, name: 'Shared connections'}).closest('div')!.parentElement!;
    expect(header).toHaveClass('flex-col', 'tablet:flex-row');

    const newBtn = screen.getByRole('button', {name: 'New shared connection'});
    expect(newBtn).toHaveClass('w-full', 'tablet:w-auto');
    expect(within(newBtn).getByText('New')).toHaveClass('desktop:hidden');
    expect(within(newBtn).getByText('New shared connection')).toHaveClass('hidden', 'desktop:inline');
  });
});

describe('ConnectionsPage — a delete that failed (SPEC-205)', () => {
  it('retries a failed DELETE with delete, and offers no Dismiss', async () => {
    // Retry used to always create. On a name that was ever used the server now refuses that,
    // and re-provisioning one would reset the roster to the owner alone over the previous
    // cohort's files. Dismiss is suppressed because `forget` is a server no-op here, and the
    // row it would clear is the only affordance left for finishing the delete.
    mockRead.mockResolvedValue(
      cache([{name: 'sales', role: 'owner', status: 'failed', reason: 'S3 was unhappy', failedAction: 'delete'}])
    );
    const {user} = renderPage();

    const row = await rowFor('sales');
    expect(within(row).queryByRole('button', {name: 'Dismiss'})).not.toBeInTheDocument();
    await user.click(within(row).getByRole('button', {name: 'Retry'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
    expect(mockEnqueue.mock.calls[0][0]).toMatchObject({action: 'delete', space: 'sales'});
  });

  it('leaves a failed CREATE row exactly as it was', async () => {
    mockRead.mockResolvedValue(
      cache([{name: 'ops', role: 'owner', status: 'failed', reason: 'name already taken', failedAction: 'create'}])
    );
    const {user} = renderPage();

    const row = await rowFor('ops');
    expect(within(row).getByRole('button', {name: 'Dismiss'})).toBeInTheDocument();
    await user.click(within(row).getByRole('button', {name: 'Retry'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
    expect(mockEnqueue.mock.calls[0][0]).toMatchObject({action: 'create', space: 'ops'});
  });

  it('gives a row stuck in deleting a Retry, but not one the user just submitted', async () => {
    // The validator writes `deleting` and a run that dies never clears it, so that row needs an
    // exit that is not an operator. A row the user just confirmed a delete on is forced to the
    // same status locally and is indistinguishable in `rows` — offering Retry there would put
    // the button beside a delete submitted two seconds ago.
    mockRead.mockResolvedValue(
      cache([
        {name: 'stuck', role: 'owner', status: 'deleting'},
        {name: 'live', role: 'owner', status: 'active'}
      ])
    );
    const {user} = renderPage();

    expect(within(await rowFor('stuck')).getByRole('button', {name: 'Retry'})).toBeInTheDocument();

    const live = await rowFor('live');
    await user.click(within(live).getByRole('button', {name: 'Delete'}));
    const dialog = await screen.findByRole('alertdialog', {name: 'Delete live'});
    await user.type(within(dialog).getByLabelText(/to confirm/), 'live');
    await user.click(within(dialog).getByRole('button', {name: 'Delete'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalled());
    expect(within(await rowFor('live')).queryByRole('button', {name: 'Retry'})).not.toBeInTheDocument();
  });
});

describe('ConnectionsPage — a delete that stopped (SPEC-205)', () => {
  it('retries a stuck deleting row with DELETE, not create', async () => {
    // Asserting the button RENDERS is not enough, and that gap is what let this through: the
    // card the validator writes for a delete in progress carried no `failedAction`, so a
    // nullish default sent `create` — the one verb that cannot work on a name already taken.
    // Its refusal then overwrites the row's own discriminator, after which nothing on the page
    // can enqueue a delete and the workspace is stranded with no affordance that does anything.
    mockRead.mockResolvedValue(cache([{name: 'stuck', role: 'owner', status: 'deleting'}]));
    const {user} = renderPage();

    await user.click(within(await rowFor('stuck')).getByRole('button', {name: 'Retry'}));

    await waitFor(() => expect(mockEnqueue).toHaveBeenCalledTimes(1));
    expect(mockEnqueue.mock.calls[0][0]).toMatchObject({action: 'delete', space: 'stuck'});
  });

  it('says something true of a deleting row whether it is in flight or stopped', async () => {
    // A Refresh drops the local override, so after one there is no way to tell the two apart —
    // the cache says `deleting` for both. Claiming it stopped is a guess that is wrong for an
    // impatient owner who refreshed two seconds in.
    mockRead.mockResolvedValue(cache([{name: 'stuck', role: 'owner', status: 'deleting'}]));
    renderPage();

    const row = await rowFor('stuck');
    expect(row).toHaveTextContent(/Deleting/);
    expect(row).not.toHaveTextContent(/Not finished removing/);
  });
});
