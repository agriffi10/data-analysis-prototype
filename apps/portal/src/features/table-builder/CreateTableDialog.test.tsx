import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent, within} from '@testing-library/react';
import {CreateTableDialog} from './CreateTableDialog';
import {PartitionKeysField} from './PartitionKeysField';
import {emptyDraftKey} from './partitionKeys';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';

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

  it('submits on Enter in the name field', () => {
    const {onSubmit} = renderDialog();
    fireEvent.keyDown(nameInput(), {key: 'Enter'});
    expect(onSubmit).toHaveBeenCalledWith({tableName: 'sales_2026', partitionKeys: []});
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

  it('reorders keys (granularity order)', () => {
    const {onSubmit} = renderDialog();
    fireEvent.click(addKeysBtn());
    fireEvent.change(screen.getByLabelText('Partition key 1 name'), {target: {value: 'month'}});
    fireEvent.change(screen.getByLabelText('Partition key 1 values'), {target: {value: '01,02'}});
    fireEvent.click(screen.getByRole('button', {name: 'Add another key'}));
    fireEvent.change(screen.getByLabelText('Partition key 2 name'), {target: {value: 'year'}});
    fireEvent.change(screen.getByLabelText('Partition key 2 values'), {target: {value: '2025,2026'}});

    // Move the second row (year) up so it leads (coarsest first).
    fireEvent.click(screen.getByRole('button', {name: 'Move partition key 2 earlier'}));
    fireEvent.click(createBtn());

    const call = onSubmit.mock.calls[0][0];
    expect(call.partitionKeys.map((k: {name: string}) => k.name)).toEqual(['year', 'month']);
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
