import {describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen, within} from '@testing-library/react';
import {CreateTableDialog} from './CreateTableDialog';
import {PartitionKeysField} from './PartitionKeysField';
import {buildPartitionKey, buildPartitionKeys, emptyDraftKey, parseValues, validateDraftKey} from './partitionKeys';
import type {DraftPartitionKey} from './partitionKeys';
import {COMPONENT_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import {renderWithProviders} from '../../test/renderWithProviders';
import {RefreshTableDialog} from './RefreshTableDialog';
import {parseRefreshLink} from './tableRefresh.link';
import {parseTableLocation} from './tableRefresh.location';
import type {TableRefreshTarget} from './tableRefresh.types';

// ─── from CreateTableDialog.test.tsx ───
describe('CreateTableDialog', () => {
  function renderDialog(props?: Partial<React.ComponentProps<typeof CreateTableDialog>>) {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    render(
      <CreateTableDialog
        folderName="Sales 2026"
        onSubmit={onSubmit}
        onCancel={onCancel}
        {...props}
      />
    );
    return {onSubmit, onCancel};
  }

  const nameInput = () => screen.getByLabelText('Table name') as HTMLInputElement;
  const createBtn = () => screen.getByRole('button', {name: 'Create table'});
  const addKeysBtn = () => screen.getByRole('button', {name: 'Add partition keys'});

  describe('CreateTableDialog — name', () => {
    it('pre-fills a catalog-safe suggestion from the folder name', () => {
      renderDialog();
      expect(nameInput().value).toBe('sales_2026');
      expect(createBtn()).toBeEnabled();
    });

    it('disables Create when the name is invalid', () => {
      renderDialog();
      fireEvent.change(nameInput(), {target: {value: 'Bad Name'}});
      expect(createBtn()).toBeDisabled();
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    it('submits a flat request (no partition keys) with the entered name', () => {
      const {onSubmit} = renderDialog();
      fireEvent.change(nameInput(), {target: {value: 'my_table'}});
      fireEvent.click(createBtn());
      expect(onSubmit).toHaveBeenCalledWith({tableName: 'my_table', partitionKeys: []});
    });
  });

  describe('CreateTableDialog — partition keys', () => {
    it('adds a key and blocks Create until the row is valid, then sends it', () => {
      const {onSubmit} = renderDialog();
      fireEvent.click(addKeysBtn());

      // A blank row is invalid → Create is disabled.
      expect(createBtn()).toBeDisabled();

      fireEvent.change(screen.getByLabelText('Partition key 1 name'), {target: {value: 'region'}});
      fireEvent.change(screen.getByLabelText('Partition key 1 values'), {target: {value: 'us, eu'}});
      expect(createBtn()).toBeEnabled();

      fireEvent.click(createBtn());
      expect(onSubmit).toHaveBeenCalledWith({
        tableName: 'sales_2026',
        partitionKeys: [{name: 'region', type: 'string', values: ['us', 'eu']}]
      });
    });

    it('builds an integer key with a range', () => {
      const {onSubmit} = renderDialog();
      fireEvent.click(addKeysBtn());
      fireEvent.change(screen.getByLabelText('Partition key 1 name'), {target: {value: 'year'}});
      fireEvent.change(screen.getByLabelText('Type'), {target: {value: 'integer'}});
      fireEvent.change(screen.getByLabelText('Partition key 1 minimum'), {target: {value: '2020'}});
      fireEvent.change(screen.getByLabelText('Partition key 1 maximum'), {target: {value: '2026'}});
      fireEvent.click(createBtn());
      expect(onSubmit).toHaveBeenCalledWith({
        tableName: 'sales_2026',
        partitionKeys: [{name: 'year', type: 'integer', range: [2020, 2026]}]
      });
    });

    it('removes a key, returning to a flat request', () => {
      const {onSubmit} = renderDialog();
      fireEvent.click(addKeysBtn());
      fireEvent.click(screen.getByRole('button', {name: 'Remove partition key 1'}));
      // Back to the collapsed affordance.
      expect(addKeysBtn()).toBeInTheDocument();
      fireEvent.click(createBtn());
      expect(onSubmit).toHaveBeenCalledWith({tableName: 'sales_2026', partitionKeys: []});
    });

    it('flags a duplicate key name', () => {
      renderDialog();
      fireEvent.click(addKeysBtn());
      fireEvent.change(screen.getByLabelText('Partition key 1 name'), {target: {value: 'region'}});
      fireEvent.change(screen.getByLabelText('Partition key 1 values'), {target: {value: 'us'}});
      fireEvent.click(screen.getByRole('button', {name: 'Add another key'}));
      fireEvent.change(screen.getByLabelText('Partition key 2 name'), {target: {value: 'region'}});
      fireEvent.change(screen.getByLabelText('Partition key 2 values'), {target: {value: 'eu'}});

      const row2 = screen.getByRole('group', {name: 'Partition key 2'});
      expect(within(row2).getByText(/duplicate/i)).toBeInTheDocument();
      expect(createBtn()).toBeDisabled();
    });

    it('sends a two-character key named after a dt= folder', () => {
      const {onSubmit} = renderDialog();
      fireEvent.click(addKeysBtn());
      fireEvent.change(screen.getByLabelText('Partition key 1 name'), {target: {value: 'dt'}});
      fireEvent.change(screen.getByLabelText('Type'), {target: {value: 'date'}});
      fireEvent.change(screen.getByLabelText('Partition key 1 range start'), {target: {value: '2025-01-01'}});
      fireEvent.change(screen.getByLabelText('Partition key 1 range end'), {target: {value: 'NOW'}});

      fireEvent.click(createBtn());

      expect(onSubmit).toHaveBeenCalledWith({
        tableName: 'sales_2026',
        partitionKeys: [{name: 'dt', type: 'date', range: ['2025-01-01', 'NOW'], format: 'yyyy-MM-dd'}]
      });
    });

    it('holds a key to 1–63 characters and the table name to 3–63', () => {
      renderDialog();
      fireEvent.click(addKeysBtn());
      fireEvent.change(screen.getByLabelText('Partition key 1 name'), {target: {value: 'Dt'}});
      fireEvent.change(nameInput(), {target: {value: 'dt'}});

      expect(screen.getByLabelText('Partition key 1 name')).toHaveAccessibleDescription(/^Use 1–63 characters/);
      expect(nameInput()).toHaveAccessibleDescription(/^Use 3–63 characters/);
      expect(createBtn()).toBeDisabled();
    });
  });

  describe('CreateTableDialog — when a key’s errors are announced', () => {
    it('shows a blank key’s errors without announcing them, and holds Create', () => {
      renderDialog();

      fireEvent.click(addKeysBtn());

      expect(screen.getByLabelText('Partition key 1 name')).toHaveFocus();
      expect(screen.getByLabelText('Partition key 1 name')).toHaveAccessibleDescription('Enter a key name.');
      expect(screen.getByText('Enter at least one value.')).toBeVisible();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(createBtn()).toBeDisabled();
    });

    it('announces a field’s error once it is left, and none a type switch brings in', () => {
      renderDialog();
      fireEvent.click(addKeysBtn());

      // Leaving each field for the next, as a real pointer or Tab does.
      fireEvent.blur(screen.getByLabelText('Partition key 1 name'));
      fireEvent.blur(screen.getByLabelText('Partition key 1 values'));
      fireEvent.change(screen.getByLabelText('Type'), {target: {value: 'integer'}});
      fireEvent.change(screen.getByLabelText('Type'), {target: {value: 'string'}});

      expect(screen.getAllByRole('alert').map((a) => a.textContent)).toEqual(['Enter a key name.']);
      expect(screen.getByLabelText('Partition key 1 values')).toHaveAccessibleDescription('Enter at least one value.');
    });

    it('keeps a left field’s announcement with its own row when an earlier row is removed', () => {
      renderDialog();
      fireEvent.click(addKeysBtn());
      fireEvent.blur(screen.getByLabelText('Partition key 1 name'));
      fireEvent.click(screen.getByRole('button', {name: 'Add another key'}));

      fireEvent.click(screen.getByRole('button', {name: 'Remove partition key 1'}));

      expect(screen.getByLabelText('Partition key 1 name')).toHaveFocus();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });

  describe('CreateTableDialog — busy + error', () => {
    it('locks the form and shows a submit error', () => {
      renderDialog({busy: true, submitError: 'SQS is unavailable'});
      expect(nameInput()).toBeDisabled();
      expect(screen.getByText('SQS is unavailable')).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Submitting…'})).toBeDisabled();
    });
  });

  describe('CreateTableDialog — a11y', () => {
    it('has no axe violations (dialog, no keys)', async () => {
      await expectNoA11yViolations(
        <CreateTableDialog
          folderName="events"
          onSubmit={vi.fn()}
          onCancel={vi.fn()}
        />,
        COMPONENT_AXE_OPTIONS
      );
    });

    it('has no axe violations in the dynamic partition-key rows', async () => {
      const year = {...emptyDraftKey(), name: 'year', type: 'integer' as const, min: '2020', max: '2026'};
      const region = {...emptyDraftKey(), name: 'region', type: 'string' as const, values: 'us,eu'};
      await expectNoA11yViolations(
        <PartitionKeysField
          value={[year, region]}
          errors={[{}, {}]}
          onChange={vi.fn()}
        />,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});

// ─── from RefreshTableDialog.test.tsx ───
describe('RefreshTableDialog', () => {
  const TARGET: TableRefreshTarget = {
    database: 'alice',
    table: {
      name: 'sales_2026',
      columns: [{name: 'region', type: 'string'}],
      location: 's3://dat-prod-user-space/alice/sales/2026/'
    },
    pending: null
  };

  const LINKED: TableRefreshTarget = {
    ...TARGET,
    pending: {database: 'alice', tableName: 'sales_2026', columns: ['legacy_id', 'Order ID']}
  };

  function render(target = TARGET, props: Partial<React.ComponentProps<typeof RefreshTableDialog>> = {}) {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const rendered = renderWithProviders(
      <RefreshTableDialog
        target={target}
        onConfirm={onConfirm}
        onCancel={onCancel}
        {...props}
      />
    );
    return {...rendered, onConfirm, onCancel};
  }

  const confirmButton = () => screen.getByRole('button', {name: 'Refresh table'});
  const optIn = () => screen.getByRole('checkbox', {name: /allow columns to be removed/i});

  describe('RefreshTableDialog', () => {
    it('names the table and the folder whose first file it will read', () => {
      render();
      expect(screen.getByRole('alertdialog', {name: /alice\.sales_2026/})).toBeInTheDocument();
      expect(screen.getByText('alice.sales_2026')).toBeInTheDocument();
      expect(screen.getByText('s3://dat-prod-user-space/alice/sales/2026/')).toBeInTheDocument();
    });

    it('offers the opt-in unchecked with confirm enabled — an additive refresh needs no tick', async () => {
      const {onConfirm, user} = render();
      expect(optIn()).not.toBeChecked();
      expect(confirmButton()).toBeEnabled();
      await user.click(confirmButton());
      expect(onConfirm).toHaveBeenCalledWith(false);
    });

    // The consequence is a DESCRIPTION on the control, not prose beside it: a user who reaches
    // the checkbox with a screen reader has to hear what ticking it costs before they tick it.
    // A CSV table reads by position, so a removal shifts every file that still carries the
    // column — the dialog cannot know the format, so the copy names CSV instead of branching.
    it('tells the checkbox what removing a column does to a CSV file that still has it', () => {
      render();
      expect(optIn()).toHaveAccessibleDescription(
        /In a table built from CSV files, a file that still has a removed column will have the values after it read into the wrong columns\./
      );
    });

    it('passes the ticked opt-in to confirm', async () => {
      const {onConfirm, user} = render();
      await user.click(optIn());
      await user.click(confirmButton());
      expect(onConfirm).toHaveBeenCalledWith(true);
    });

    it('names the link-borne columns, explains why the refresh was stopped, and offers a way to keep them', () => {
      render(LINKED);
      expect(screen.getByText(/previous refresh was stopped/i)).toBeInTheDocument();
      expect(screen.getByText(/aren’t in the first file in the table’s folder/i)).toBeInTheDocument();
      expect(screen.getByText(/to keep them, cancel/i)).toBeInTheDocument();
      const list = screen.getByRole('list', {name: /columns that would be removed/i});
      expect(within(list).getByText('legacy_id')).toBeInTheDocument();
      // Not a catalog-safe identifier — column names never have to be.
      expect(within(list).getByText('Order ID')).toBeInTheDocument();
    });

    // SPEC-186 FR-002 changed HOW this refuses, not whether: `aria-disabled` with a reason
    // rather than a bare `disabled`, so the control keeps its place in the tab order and
    // says what it is waiting for. Dropping `confirmDisabledReason` reddens this.
    it('gates confirm on the opt-in in the link-borne state, and says what it wants', async () => {
      const {onConfirm, user} = render(LINKED);
      expect(optIn()).not.toBeChecked();
      expect(confirmButton()).toHaveAttribute('aria-disabled', 'true');
      expect(confirmButton()).toHaveAttribute('title', 'Tick “Allow columns to be removed” to refresh this table.');
      expect(confirmButton()).not.toBeDisabled();
      // The reason is a description, never the name (SPEC-172's registry rule).
      expect(confirmButton()).toHaveAccessibleName('Refresh table');
      await user.click(confirmButton());
      expect(onConfirm).not.toHaveBeenCalled();

      await user.click(optIn());
      expect(confirmButton()).not.toHaveAttribute('aria-disabled');
      await user.click(confirmButton());
      expect(onConfirm).toHaveBeenCalledWith(true);
    });

    it('locks the dialog and shows progress while the enqueue is in flight', () => {
      render(TARGET, {busy: true});
      expect(screen.getByRole('button', {name: 'Starting…'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Cancel'})).toBeDisabled();
      expect(optIn()).toBeDisabled();
    });

    it('surfaces a submit error inline without closing', () => {
      render(TARGET, {submitError: 'Sign in to continue.'});
      expect(screen.getByRole('alert')).toHaveTextContent('Sign in to continue.');
      expect(confirmButton()).toBeEnabled();
    });

    // SPEC-095/145 FR-007: one tree, `tablet:` only — no `*Mobile` twin, and nothing in the
    // dialog reads `useIsMobile`.
    //
    // RENAMED FROM `describe('at a narrow viewport')` (SPEC-154 FR-009), because it never
    // changed the viewport — and could not usefully: jsdom applies no media queries, so a
    // `tablet:` class assertion says nothing about what a narrow-screen user sees while
    // breaking on any refactor to equivalent CSS. What these cases actually pin is the
    // RESPONSIVE CONTRACT in the markup, which is a real thing to guard and is now named as
    // such. The one case with an accessible contract available is asserted through it instead.
    describe('the responsive contract in the markup (not a rendered viewport)', () => {
      // The viewport cap itself belongs to `Modal` and is asserted in Modal.test.tsx —
      // asserting it here would pass no matter what this component does.
      it('scrolls a long column list rather than growing without bound', () => {
        render({...LINKED, pending: {...LINKED.pending!, columns: Array.from({length: 20}, (_, i) => `col_${i}`)}});
        const scroller = screen.getByRole('region', {name: /columns that would be removed/i});
        expect(scroller).toHaveClass('max-h-32', 'overflow-y-auto');
        // A scrolling region the keyboard cannot reach hides the columns past its fold.
        expect(scroller).toHaveAttribute('tabindex', '0');
        // The behavioural half: however long the list gets, confirm is still reachable.
        expect(confirmButton()).toBeInTheDocument();
      });

      it('declares the one-tree reflow for the table/folder rows', () => {
        // Class-string assertion KEPT, with the reason FR-009 asks for: SPEC-095's "reflow on
        // ONE tree" is a documented constraint with no accessible equivalent — the guarantee is
        // precisely that no `*Mobile` twin exists, which is a fact about the markup.
        render();
        expect(screen.getByText('alice.sales_2026').parentElement).toHaveClass('flex-col', 'tablet:flex-row');
      });
    });
  });
});

// ─── from RefreshTableDialog.a11y.test.tsx ───
describe('RefreshTableDialog.a11y', () => {
  const noop = () => {};

  const TARGET: TableRefreshTarget = {
    database: 'alice',
    table: {name: 'sales_2026', columns: [], location: 's3://dat-prod-user-space/alice/sales/2026/'},
    pending: null
  };

  describe('RefreshTableDialog a11y', () => {
    it('has no axe violations in the plain state', async () => {
      await expectNoA11yViolations(
        <RefreshTableDialog
          target={TARGET}
          onConfirm={noop}
          onCancel={noop}
        />,
        COMPONENT_AXE_OPTIONS
      );
    });

    it('has no axe violations in the link-borne state', async () => {
      await expectNoA11yViolations(
        <RefreshTableDialog
          target={{
            ...TARGET,
            pending: {database: 'alice', tableName: 'sales_2026', columns: ['legacy_id', 'Order ID']}
          }}
          onConfirm={noop}
          onCancel={noop}
        />,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});

// ─── from partitionKeys.test.ts ───
describe('partitionKeys', () => {
  // Build a draft from partial overrides on a blank row (with a stable id).
  function draft(over: Partial<DraftPartitionKey>): DraftPartitionKey {
    return {...emptyDraftKey(), ...over};
  }

  describe('emptyDraftKey', () => {
    it('defaults to a string key with a date format and unique id', () => {
      const a = emptyDraftKey();
      const b = emptyDraftKey();
      expect(a.type).toBe('string');
      expect(a.format).toBe('yyyy-MM-dd');
      expect(a.id).not.toBe(b.id);
    });
  });

  describe('parseValues', () => {
    it('splits, trims, and drops empties', () => {
      expect(parseValues(' us, eu , , apac ')).toEqual(['us', 'eu', 'apac']);
      expect(parseValues('')).toEqual([]);
    });
  });

  describe('validateDraftKey — name', () => {
    it('holds a key name to 1–63 characters, starting with a lowercase letter', () => {
      expect(validateDraftKey(draft({name: 'd', type: 'string', values: 'a'}), []).name).toBeUndefined();
      for (const name of ['Year', '1year', 'd'.repeat(64)]) {
        expect(validateDraftKey(draft({name, type: 'string', values: 'a'}), []).name).toMatch(/^Use 1–63 characters/);
      }
    });
  });

  describe('validateDraftKey — integer', () => {
    it('requires whole-number min and max', () => {
      const e = validateDraftKey(draft({name: 'y', type: 'integer', min: 'x', max: '1.5'}), []);
      expect(e.min).toBeTruthy();
      expect(e.max).toBeTruthy();
    });
  });

  describe('validateDraftKey — date', () => {
    it('requires start, end, and format', () => {
      const e = validateDraftKey(draft({name: 'd', type: 'date', start: '', end: '', format: ''}), []);
      expect(e.start).toBeTruthy();
      expect(e.end).toBeTruthy();
      expect(e.format).toBeTruthy();
    });
  });

  describe('validateDraftKey — string', () => {
    it('requires at least one value', () => {
      expect(validateDraftKey(draft({name: 's', type: 'string', values: '  '}), []).values).toBeTruthy();
    });
  });

  describe('buildPartitionKey', () => {
    it('builds an integer key with optional digits', () => {
      expect(
        buildPartitionKey(draft({name: 'year', type: 'integer', min: '2020', max: '2026', digits: '4'}), [])
      ).toEqual({
        name: 'year',
        type: 'integer',
        range: [2020, 2026],
        digits: 4
      });
      expect(buildPartitionKey(draft({name: 'year', type: 'integer', min: '2020', max: '2026'}), [])).toEqual({
        name: 'year',
        type: 'integer',
        range: [2020, 2026]
      });
    });

    it('builds a date key', () => {
      expect(
        buildPartitionKey(draft({name: 'day', type: 'date', start: '2020-01-01', end: 'NOW', format: 'yyyy-MM-dd'}), [])
      ).toEqual({name: 'day', type: 'date', range: ['2020-01-01', 'NOW'], format: 'yyyy-MM-dd'});
    });
  });

  describe('buildPartitionKeys', () => {
    it('treats an empty list as a valid flat table', () => {
      expect(buildPartitionKeys([])).toEqual({valid: true, keys: [], errors: []});
    });

    it('builds all keys in order when every row is valid', () => {
      const rows = [
        draft({name: 'year', type: 'integer', min: '2020', max: '2026'}),
        draft({name: 'region', type: 'string', values: 'us,eu'})
      ];
      const result = buildPartitionKeys(rows);
      expect(result.valid).toBe(true);
      expect(result.keys.map((k) => k.name)).toEqual(['year', 'region']);
    });
  });
});

// ─── from tableRefresh.link.test.ts ───
describe('tableRefresh.link', () => {
  describe('parseRefreshLink', () => {
    it('parses the link SPEC-144 mints', () => {
      expect(parseRefreshLink('?refreshTable=sales.orders&removed=legacy_id,old_total')).toEqual({
        database: 'sales',
        tableName: 'orders',
        columns: ['legacy_id', 'old_total']
      });
    });

    it('decodes each name individually, so a comma inside one is not a separator', () => {
      // The exact string tbcommon.notify builds for these names.
      expect(parseRefreshLink('?refreshTable=sales.orders&removed=Order%20ID,a%26b,x%23y,co%2Cmma')).toEqual({
        database: 'sales',
        tableName: 'orders',
        columns: ['Order ID', 'a&b', 'x#y', 'co,mma']
      });
    });

    it('caps the list at 20 names', () => {
      const names = Array.from({length: 25}, (_, i) => `col_${i}`);
      expect(parseRefreshLink(`?refreshTable=sales.orders&removed=${names.join(',')}`)?.columns).toHaveLength(20);
    });
  });
});

// ─── from tableRefresh.location.test.ts ───
describe('tableRefresh.location', () => {
  describe('parseTableLocation', () => {
    it('splits an s3 location into bucket and prefix', () => {
      expect(parseTableLocation('s3://user-space/alice/sales/')).toEqual({
        bucket: 'user-space',
        prefix: 'alice/sales/'
      });
    });

    it('normalises a missing trailing slash', () => {
      expect(parseTableLocation('s3://user-space/alice/sales')).toEqual({bucket: 'user-space', prefix: 'alice/sales/'});
    });
  });
});
