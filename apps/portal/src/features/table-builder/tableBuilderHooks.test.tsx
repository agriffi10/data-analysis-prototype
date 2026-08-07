import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {MockedFunction} from 'vitest';
import {act, screen, within} from '@testing-library/react';
import {renderHookWithProviders, renderWithProviders} from '../../test/renderWithProviders';
import {CreateTableButton} from './CreateTableButton';
import {enqueueTableBuild, enqueueTableRefresh} from './tableBuild.service';
import {authenticated} from '../../test/authFixtures';
import {queryKeys} from '../query/queryKeys';
import {getS3Client} from '../../lib/s3Client';
import {useTableRefresh} from './useTableRefresh';
import type {GlueTableSummary} from '../query/query.types';

// ─── from CreateTableButton.test.tsx ───
vi.mock('./tableBuild.service', async (orig) => ({
  ...(await orig<typeof import('./tableBuild.service')>()),
  enqueueTableBuild: vi.fn(),
  enqueueTableRefresh: vi.fn()
}));

vi.mock('../../lib/s3Client', () => ({getS3Client: vi.fn()}));

describe('CreateTableButton', () => {
  // Partial-mock: stub the network call, keep the real name suggestion/validation the
  // dialog relies on.

  const mockEnqueue = enqueueTableBuild as unknown as MockedFunction<typeof enqueueTableBuild>;

  function renderButton(props?: Partial<React.ComponentProps<typeof CreateTableButton>>) {
    // to hand-roll — and returns the `user` the partition-key journey below needs.
    return renderWithProviders(
      <CreateTableButton
        spaceKind="personal"
        bucket="dat-prod-user-space"
        database="alice"
        prefix="alice/sales/"
        {...props}
      />
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockEnqueue.mockResolvedValue({success: true, data: undefined});
  });

  describe('CreateTableButton', () => {
    it('opens the dialog with a name suggested from the current folder', async () => {
      const {user} = renderButton();
      await user.click(screen.getByRole('button', {name: 'Create table'}));
      expect((screen.getByLabelText('Table name') as HTMLInputElement).value).toBe('sales');
    });

    it('enqueues for the active space + current prefix and shows a success toast', async () => {
      const {user} = renderButton();
      await user.click(screen.getByRole('button', {name: 'Create table'}));
      // The dialog's confirm is also called "Create table"; scope to the dialog rather than
      // reaching for index [1], which silently follows any change in render order (FR-006).
      await user.click(
        within(screen.getByRole('dialog', {name: 'Create table from this folder'})).getByRole('button', {
          name: 'Create table'
        })
      );

      expect(mockEnqueue).toHaveBeenCalledWith({
        space: {kind: 'personal', bucket: 'dat-prod-user-space', prefix: 'alice/sales/', database: 'alice'},
        tableName: 'sales',
        partitionKeys: []
      });
      expect(await screen.findByText(/Creating table/)).toBeInTheDocument();
      // Dialog closed on success.
      expect(screen.queryByLabelText('Table name')).not.toBeInTheDocument();
    });

    it('passes the shared space kind + database through', async () => {
      const {user} = renderButton({
        spaceKind: 'shared',
        bucket: 'dat-prod-shared-space',
        database: 'salesdata',
        prefix: 'salesdata/'
      });
      await user.click(screen.getByRole('button', {name: 'Create table'}));
      await user.click(
        within(screen.getByRole('dialog', {name: 'Create table from this folder'})).getByRole('button', {
          name: 'Create table'
        })
      );
      expect(mockEnqueue).toHaveBeenCalledWith(
        expect.objectContaining({space: expect.objectContaining({kind: 'shared', database: 'salesdata'})})
      );
      await screen.findByText(/Creating table/);
    });

    it('keeps the dialog open and shows friendly, mapped error text on a send failure', async () => {
      // Raw AWS message + code; the dialog shows the FR-001-mapped text, not 'SQS unavailable'.
      mockEnqueue.mockResolvedValue({success: false, error: {message: 'SQS unavailable', code: 'NetworkError'}});
      const {user} = renderButton();
      await user.click(screen.getByRole('button', {name: 'Create table'}));
      await user.click(
        within(screen.getByRole('dialog', {name: 'Create table from this folder'})).getByRole('button', {
          name: 'Create table'
        })
      );
      expect(await screen.findByText(/Check your connection/)).toBeInTheDocument();
      expect(screen.queryByText('SQS unavailable')).not.toBeInTheDocument();
      expect(screen.getByLabelText('Table name')).toBeInTheDocument();
    });
  });

  // ── SPEC-154 FR-006: a POPULATED partition-key array reaches the service ────
  //
  // Every existing case enqueues `partitionKeys: []`, so the whole wizard → `buildPartitionKeys`
  // → enqueue path was untested end to end. Partition keys are user-declared and go straight
  // into Athena partition projection (SPEC-066), where a dropped `digits` or a range that never
  // arrives means a table that silently returns no rows for whole partitions.
  describe('CreateTableButton — declared partition keys (SPEC-071)', () => {
    const dialog = () => within(screen.getByRole('dialog', {name: 'Create table from this folder'}));

    it('carries an ordered integer + string key set through to the enqueue, field by field', async () => {
      const {user} = renderButton();
      await user.click(screen.getByRole('button', {name: 'Create table'}));
      await user.click(dialog().getByRole('button', {name: 'Add partition keys'}));

      // Scoped to each row's own group, so "Type" is unambiguous without an index.
      const row = (n: number) => within(dialog().getByRole('group', {name: `Partition key ${n}`}));
      await user.type(row(1).getByLabelText('Partition key 1 name'), 'year');
      await user.selectOptions(row(1).getByLabelText('Type'), 'integer');
      await user.type(row(1).getByLabelText('Partition key 1 minimum'), '2020');
      await user.type(row(1).getByLabelText('Partition key 1 maximum'), '2026');
      await user.type(row(1).getByLabelText('Partition key 1 digit width'), '4');

      await user.click(dialog().getByRole('button', {name: 'Add another key'}));
      await user.type(row(2).getByLabelText('Partition key 2 name'), 'region');
      // `string` is the default type for a new row, so it is NOT selected here — doing so would
      // read as coverage of the select while exercising nothing.
      await user.type(row(2).getByLabelText('Partition key 2 values'), 'us-east, eu-west');

      await user.click(dialog().getByRole('button', {name: 'Create table'}));

      expect(mockEnqueue).toHaveBeenCalledWith(
        expect.objectContaining({
          // ORDER matters (granularity, coarsest first) and so does every field: a dropped
          // `digits` or a range that never arrives means whole partitions return no rows.
          partitionKeys: [
            {name: 'year', type: 'integer', range: [2020, 2026], digits: 4},
            {name: 'region', type: 'string', values: ['us-east', 'eu-west']}
          ]
        })
      );
    });
  });
});

// ─── from useTableRefresh.test.ts ───

describe('useTableRefresh', () => {
  // Integration style: the real hook, the real QueryClient and the real auth
  // context — only the AWS boundary (the enqueue service) is mocked.
  const mockEnqueue = vi.mocked(enqueueTableRefresh);

  const TABLE: GlueTableSummary = {
    name: 'sales_2026',
    columns: [{name: 'region', type: 'string'}],
    location: 's3://dat-prod-user-space/alice/sales/2026'
  };

  const SHARED_TABLE: GlueTableSummary = {
    name: 'events',
    columns: [],
    location: 's3://dat-prod-shared-space/salesdata/events/'
  };

  function render(username = 'alice') {
    const notify = vi.fn();
    const rendered = renderHookWithProviders(() => useTableRefresh(notify), {auth: authenticated(username)});
    return {...rendered, notify};
  }

  /** The FR-005 entry point: a target the caller derived from the notification link. */
  function renderLinked(pending = {database: 'alice', tableName: 'sales_2026', columns: ['legacy_id']}) {
    const notify = vi.fn();
    const onConsumed = vi.fn();
    const target = {database: 'alice', table: TABLE, pending};
    const rendered = renderHookWithProviders(() => useTableRefresh(notify, {target, onConsumed}), {
      auth: authenticated('alice')
    });
    return {...rendered, notify, onConsumed, target};
  }

  describe('useTableRefresh', () => {
    beforeEach(() => {
      mockEnqueue.mockReset();
      mockEnqueue.mockResolvedValue({success: true, data: undefined});
    });

    it('open targets a rail table with no pending removal; close clears it', () => {
      const {result} = render();
      act(() => result.current.open('alice', TABLE));
      expect(result.current.target).toEqual({database: 'alice', table: TABLE, pending: null});
      act(() => result.current.close());
      expect(result.current.target).toBeNull();
    });

    it('open carries a link-borne pending removal', () => {
      const {result} = render();
      const pending = {database: 'alice', tableName: 'sales_2026', columns: ['legacy_id']};
      act(() => result.current.open('alice', TABLE, pending));
      expect(result.current.target?.pending).toEqual(pending);
    });

    it('submits a personal-space request built from the table location', async () => {
      const {result, notify} = render();
      act(() => result.current.open('alice', TABLE));
      await act(() => result.current.submit(false));

      expect(mockEnqueue).toHaveBeenCalledWith({
        space: {
          kind: 'personal',
          bucket: 'dat-prod-user-space',
          prefix: 'alice/sales/2026/', // trailing slash normalised by the parser
          database: 'alice'
        },
        tableName: 'sales_2026'
      });
      expect(result.current.target).toBeNull();
      expect(notify).toHaveBeenCalledWith(
        expect.objectContaining({variant: 'success', message: expect.stringContaining('alice.sales_2026')})
      );
    });

    it('marks a database that is not the signed-in user as a shared space', async () => {
      const {result} = render();
      act(() => result.current.open('salesdata', SHARED_TABLE));
      await act(() => result.current.submit(false));
      expect(mockEnqueue).toHaveBeenCalledWith(
        expect.objectContaining({
          space: {kind: 'shared', bucket: 'dat-prod-shared-space', prefix: 'salesdata/events/', database: 'salesdata'}
        })
      );
    });

    it('sends allowRemovals only when the opt-in was ticked', async () => {
      const {result} = render();
      act(() => result.current.open('alice', TABLE));
      await act(() => result.current.submit(true));
      expect(mockEnqueue.mock.calls[0][0]).toMatchObject({allowRemovals: true});

      act(() => result.current.open('alice', TABLE));
      await act(() => result.current.submit(false));
      expect(mockEnqueue.mock.calls[1][0]).not.toHaveProperty('allowRemovals');
    });

    it('keeps the dialog open with a user-safe error when the enqueue fails', async () => {
      // SPEC-106: the raw service text never reaches the surface.
      mockEnqueue.mockResolvedValue({success: false, error: {message: 'no credentials', code: 'NotAuthenticated'}});
      const {result, notify} = render();
      act(() => result.current.open('alice', TABLE));
      await act(() => result.current.submit(false));

      expect(result.current.target).toEqual({database: 'alice', table: TABLE, pending: null});
      expect(result.current.error).toBe('Sign in to continue.');
      expect(notify).not.toHaveBeenCalled();
    });

    it('refuses to build a request for a table with no location', async () => {
      const {result} = render();
      act(() => result.current.open('alice', {name: 'no_files', columns: []}));
      await act(() => result.current.submit(false));
      expect(mockEnqueue).not.toHaveBeenCalled();
      expect(result.current.error).toContain('no data folder');
    });

    it('ignores submit with no target', async () => {
      const {result} = render();
      await act(() => result.current.submit(false));
      expect(mockEnqueue).not.toHaveBeenCalled();
    });

    it('invalidates the rail once on submit and once on the next focus', async () => {
      const {result, queryClient} = render();
      const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
      act(() => result.current.open('alice', TABLE));
      await act(() => result.current.submit(false));

      expect(invalidate).toHaveBeenCalledTimes(1);
      expect(invalidate).toHaveBeenCalledWith({queryKey: queryKeys.schema('alice')});

      // The refresh lands while the user is elsewhere, so coming back re-reads once…
      await act(async () => void window.dispatchEvent(new Event('focus')));
      expect(invalidate).toHaveBeenCalledTimes(2);

      // …and only once: further focus events are not a reason to refetch.
      await act(async () => void window.dispatchEvent(new Event('focus')));
      await act(async () => void window.dispatchEvent(new Event('focus')));
      expect(invalidate).toHaveBeenCalledTimes(2);
    });

    it('does not invalidate on focus when no refresh was submitted', async () => {
      const {result, queryClient} = render();
      const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
      act(() => result.current.open('alice', TABLE));
      act(() => result.current.close());
      await act(async () => void window.dispatchEvent(new Event('focus')));
      expect(invalidate).not.toHaveBeenCalled();
    });

    describe('a link-borne target (FR-005)', () => {
      it('is the target without anything being opened', () => {
        const {result, target} = renderLinked();
        expect(result.current.target).toEqual(target);
      });

      it('retires the link on close — the parameters are what hold the dialog open', () => {
        const {result, onConsumed} = renderLinked();
        act(() => result.current.close());
        expect(onConsumed).toHaveBeenCalledTimes(1);
      });

      it('submits it and retires the link', async () => {
        const {result, onConsumed} = renderLinked();
        await act(() => result.current.submit(true));
        expect(mockEnqueue).toHaveBeenCalledWith(
          expect.objectContaining({tableName: 'sales_2026', allowRemovals: true})
        );
        expect(onConsumed).toHaveBeenCalledTimes(1);
      });

      it('keeps the link alive when the enqueue fails, so the dialog can be retried', async () => {
        mockEnqueue.mockResolvedValue({success: false, error: {message: 'nope'}});
        const {result, onConsumed} = renderLinked();
        await act(() => result.current.submit(true));
        expect(onConsumed).not.toHaveBeenCalled();
        expect(result.current.error).toBeTruthy();
      });

      it('is overridden by an explicitly opened table', () => {
        const {result} = renderLinked();
        const other = {name: 'other_table', columns: [], location: 's3://dat-prod-user-space/alice/other/'};
        act(() => result.current.open('alice', other));
        expect(result.current.target).toEqual({database: 'alice', table: other, pending: null});
      });
    });

    // SPEC-150 FR-003. Both calls are made inside ONE act block with no await between
    // them — a real double-click, where both land before React re-renders. Awaiting the
    // first would let `busy` commit and would pass against the old state guard, which is
    // exactly the bug. It matters more here than anywhere else: `deduplicationId` is a
    // fresh UUID per call so SQS FIFO cannot collapse the pair, and `messageGroupId`
    // serializes delivery but not execution — so a double-click starts two overlapping
    // `UpdateTable` runs on one table, the race SPEC-149 could not close.
    describe('re-entrancy', () => {
      it('two submits in a single render enqueue exactly once', async () => {
        const {result} = render();
        act(() => result.current.open('alice', TABLE));

        await act(async () => {
          const first = result.current.submit(false);
          const second = result.current.submit(false);
          await Promise.all([first, second]);
        });

        expect(mockEnqueue).toHaveBeenCalledTimes(1);
      });

      it('the dropped second call resolves quietly and leaves the hook usable', async () => {
        const {result} = render();
        act(() => result.current.open('alice', TABLE));

        await act(async () => {
          await Promise.all([
            expect(result.current.submit(false)).resolves.toBeUndefined(),
            expect(result.current.submit(false)).resolves.toBeUndefined()
          ]);
        });
        expect(result.current.error).toBeNull();

        // The guard cleared, so a later legitimate refresh still goes through.
        act(() => result.current.open('alice', SHARED_TABLE));
        await act(() => result.current.submit(true));

        expect(mockEnqueue).toHaveBeenCalledTimes(2);
        expect(mockEnqueue).toHaveBeenLastCalledWith(expect.objectContaining({tableName: 'events'}));
      });

      it('clears the guard on the no-location early return, which never awaits', async () => {
        // The one exit that returns before any await — without a finally it would wedge
        // the dialog permanently.
        const {result} = render();
        act(() => result.current.open('alice', {name: 'no_loc', columns: []}));
        await act(() => result.current.submit(false));
        expect(mockEnqueue).not.toHaveBeenCalled();

        act(() => result.current.open('alice', TABLE));
        await act(() => result.current.submit(false));
        expect(mockEnqueue).toHaveBeenCalledTimes(1);
      });
    });

    it('persists nothing — no localStorage write and no S3 call on any path', async () => {
      // FR-003: the opt-in is never remembered. `user_settings/` is reached through the
      // S3 client, so a feature that never obtains one cannot have written there.
      const setItem = vi.spyOn(Storage.prototype, 'setItem');
      const {result} = render();
      act(() => result.current.open('alice', TABLE));
      await act(() => result.current.submit(true));
      expect(setItem).not.toHaveBeenCalled();
      expect(getS3Client).not.toHaveBeenCalled();
      setItem.mockRestore();
    });
  });
});
