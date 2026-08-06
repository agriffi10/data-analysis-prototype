import {describe, it, expect, vi, beforeEach, type MockedFunction} from 'vitest';
import {screen, fireEvent, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';

// Partial-mock: stub the network call, keep the real name suggestion/validation the
// dialog relies on.
vi.mock('./tableBuild.service', async (orig) => ({
  ...(await orig<typeof import('./tableBuild.service')>()),
  enqueueTableBuild: vi.fn()
}));

import {CreateTableButton} from './CreateTableButton';
import {enqueueTableBuild} from './tableBuild.service';

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
  it('opens the dialog with a name suggested from the current folder', () => {
    renderButton();
    fireEvent.click(screen.getByRole('button', {name: 'Create table'}));
    expect((screen.getByLabelText('Table name') as HTMLInputElement).value).toBe('sales');
  });

  it('enqueues for the active space + current prefix and shows a success toast', async () => {
    renderButton();
    fireEvent.click(screen.getByRole('button', {name: 'Create table'}));
    // The dialog's confirm is also called "Create table"; scope to the dialog rather than
    // reaching for index [1], which silently follows any change in render order (FR-006).
    fireEvent.click(
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
    renderButton({spaceKind: 'shared', bucket: 'dat-prod-shared-space', database: 'salesdata', prefix: 'salesdata/'});
    fireEvent.click(screen.getByRole('button', {name: 'Create table'}));
    fireEvent.click(
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
    renderButton();
    fireEvent.click(screen.getByRole('button', {name: 'Create table'}));
    fireEvent.click(
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
    await user.selectOptions(row(2).getByLabelText('Type'), 'string');
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
