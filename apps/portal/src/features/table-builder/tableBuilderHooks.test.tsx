import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {MockedFunction} from 'vitest';
import {act, screen, within} from '@testing-library/react';
import {renderHookWithProviders, renderWithProviders} from '../../test/renderWithProviders';
import {CreateTableButton} from './CreateTableButton';
import {
  CREATE_TABLE_AT_ROOT_REFUSAL,
  CREATE_TABLE_FILE_AT_ROOT_REFUSAL,
  CREATE_TABLE_FILE_SELECTED_REFUSAL,
  CREATE_TABLE_MANY_SELECTED_REFUSAL,
  CREATE_TABLE_NOTHING_SELECTED_REFUSAL
} from './createTableRefusal';
import {enqueueTableBuild, enqueueTableRefresh} from './tableBuild.service';
import {authenticated} from '../../test/authFixtures';
import {catalogKeys} from '../catalog/catalogKeys';
import {useTableRefresh} from './useTableRefresh';
import {drainCatalogCatchUp} from './useCatalogCatchUp';
import type {GlueTableSummary} from '../catalog/catalog.types';

// ─── from CreateTableButton.test.tsx ───
vi.mock('./tableBuild.service', async (orig) => ({
  ...(await orig<typeof import('./tableBuild.service')>()),
  enqueueTableBuild: vi.fn(),
  enqueueTableRefresh: vi.fn()
}));

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
        selected={[{type: 'folder', prefix: 'alice/sales/'}]}
        rootPrefix="alice/"
        {...props}
      />
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockEnqueue.mockResolvedValue({success: true, data: undefined});
  });

  describe('CreateTableButton', () => {
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
        selected: [{type: 'folder', prefix: 'salesdata/reports/'}]
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

    // A table's LOCATION is read recursively, so a build at the space root SUCCEEDS and
    // produces a table over `athenaresults/`, `saved_queries/` and everything else the space
    // keeps there. Refused before submission, with the reason on the control rather than as a
    // notification about a table that already exists.
    // Each refusal is asserted by IDENTITY, never by a phrase they happen to share. Several
    // of these sentences explain the same underlying rule, so a substring like "reads every
    // file" is satisfied by the wrong arm and the test passes while naming the wrong reason.
    const refusalOf = () => screen.getByRole('button', {name: 'Create table'}).getAttribute('title');

    async function expectRefused(user: ReturnType<typeof renderButton>['user'], reason: string) {
      const button = screen.getByRole('button', {name: 'Create table'});
      expect(button).toHaveAttribute('aria-disabled', 'true');
      expect(refusalOf()).toBe(reason);
      await user.click(button);
      expect(screen.queryByRole('dialog', {name: 'Create table from this folder'})).not.toBeInTheDocument();
      expect(mockEnqueue).not.toHaveBeenCalled();
    }

    it('refuses when nothing is selected', async () => {
      const {user} = renderButton({selected: []});
      await expectRefused(user, CREATE_TABLE_NOTHING_SELECTED_REFUSAL);
    });

    it('refuses when more than one item is selected', async () => {
      const {user} = renderButton({
        selected: [
          {type: 'folder', prefix: 'alice/sales/'},
          {type: 'folder', prefix: 'alice/costs/'}
        ]
      });
      await expectRefused(user, CREATE_TABLE_MANY_SELECTED_REFUSAL);
    });

    // A file was previously neither permitted nor refused — the button ignored the selection
    // entirely and built from whatever folder happened to be open.
    it('refuses when the one selected item is a file', async () => {
      const {user} = renderButton({selected: [{type: 'file', key: 'alice/sales/jan.csv'}]});
      await expectRefused(user, CREATE_TABLE_FILE_SELECTED_REFUSAL);
    });

    // "Select the folder that holds this file" named the space root, which is refused in turn —
    // a tester at the top of their space was sent round in a circle.
    it('tells a user whose file is at the top of the space to put it in a folder first', async () => {
      const {user} = renderButton({selected: [{type: 'file', key: 'alice/jan.csv'}], rootPrefix: 'alice/'});
      await expectRefused(user, CREATE_TABLE_FILE_AT_ROOT_REFUSAL);
    });

    // A table's LOCATION is read recursively, so a build at the space root SUCCEEDS and
    // produces a table over `athenaresults/`, `saved_queries/` and everything else the space
    // keeps there. Still refused even when the root arrives as a selected folder.
    it('refuses a build at the space root and says why, without opening the dialog', async () => {
      const {user} = renderButton({selected: [{type: 'folder', prefix: 'alice/'}], rootPrefix: 'alice/'});
      await expectRefused(user, CREATE_TABLE_AT_ROOT_REFUSAL);
    });

    it('offers the build for one selected folder below the root', () => {
      renderButton({selected: [{type: 'folder', prefix: 'alice/sales/2024/'}], rootPrefix: 'alice/'});
      expect(screen.getByRole('button', {name: 'Create table'})).not.toHaveAttribute('aria-disabled');
    });

    // The name is suggested from the SELECTED folder, not the one in view — the two are
    // routinely different now that selecting is what chooses.
    it('builds from the selected folder, not the folder in view', async () => {
      const {user} = renderButton({selected: [{type: 'folder', prefix: 'alice/costs/2025/'}]});
      await user.click(screen.getByRole('button', {name: 'Create table'}));
      await user.click(
        within(screen.getByRole('dialog', {name: 'Create table from this folder'})).getByRole('button', {
          name: 'Create table'
        })
      );
      expect(mockEnqueue).toHaveBeenCalledWith(
        expect.objectContaining({
          space: expect.objectContaining({prefix: 'alice/costs/2025/'}),
          // `t_` because the real suggestion is running: a table name may not start with a
          // digit, and the folder here is a year.
          tableName: 't_2025'
        })
      );
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
      await user.type(row(1).getByLabelText('Digits for partition key 1'), '4');

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
      // The catch-up is module state, so an arm a previous case left would leak into this one.
      drainCatalogCatchUp(() => {});
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

    it('sends allowRemovals only when the opt-in was ticked', async () => {
      const {result} = render();
      act(() => result.current.open('alice', TABLE));
      await act(() => result.current.submit(true));
      expect(mockEnqueue).toHaveBeenCalledTimes(1);
      expect(mockEnqueue.mock.calls[0][0]).toMatchObject({allowRemovals: true});

      act(() => result.current.open('alice', TABLE));
      await act(() => result.current.submit(false));
      expect(mockEnqueue).toHaveBeenCalledTimes(2);
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
      // Nothing was enqueued, so nothing is owed a re-read.
      const owed = vi.fn();
      drainCatalogCatchUp(owed);
      expect(owed).not.toHaveBeenCalled();
    });

    it('ignores submit with no target', async () => {
      const {result} = render();
      await act(() => result.current.submit(false));
      expect(mockEnqueue).not.toHaveBeenCalled();
    });

    // The refresh lands minutes later, usually after the user has left the query workspace —
    // so the re-read it is owed is held by the shell's catch-up, not by this hook.
    it('invalidates the rail on submit and owes it one more re-read that outlives the hook', async () => {
      const {result, queryClient, unmount} = render();
      const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
      const owed = vi.fn();
      act(() => result.current.open('alice', TABLE));

      await act(() => result.current.submit(false));
      unmount();
      drainCatalogCatchUp(owed);

      expect(invalidate).toHaveBeenCalledTimes(1);
      expect(invalidate).toHaveBeenCalledWith({queryKey: catalogKeys.schema('alice')});
      expect(owed.mock.calls).toEqual([['alice', 'sales_2026']]);
    });

    describe('a link-borne target (FR-005)', () => {
      it('is the target without anything being opened', () => {
        const {result, target} = renderLinked();
        expect(result.current.target).toEqual(target);
      });

      it('submits it and retires the link', async () => {
        const {result, onConsumed} = renderLinked();
        await act(() => result.current.submit(true));
        expect(mockEnqueue).toHaveBeenCalledWith(
          expect.objectContaining({tableName: 'sales_2026', allowRemovals: true})
        );
        expect(onConsumed).toHaveBeenCalledTimes(1);
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
  });
});
