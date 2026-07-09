import {describe, it, expect, vi, beforeEach, type MockedFunction} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';

// Partial-mock: stub the network call, keep the real name suggestion/validation the
// dialog relies on.
vi.mock('./tableBuild.service', async (orig) => ({
  ...(await orig<typeof import('./tableBuild.service')>()),
  enqueueTableBuild: vi.fn()
}));

import {CreateTableButton} from './CreateTableButton';
import {ToastProvider} from '../../components/ToastProvider';
import {enqueueTableBuild} from './tableBuild.service';

const mockEnqueue = enqueueTableBuild as unknown as MockedFunction<typeof enqueueTableBuild>;

function renderButton(props?: Partial<React.ComponentProps<typeof CreateTableButton>>) {
  render(
    <ToastProvider>
      <CreateTableButton
        spaceKind="personal"
        bucket="dat-prod-user-space"
        database="alice"
        prefix="alice/sales/"
        {...props}
      />
    </ToastProvider>
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
    // The dialog's Confirm button is also "Create table"; it's the second one.
    fireEvent.click(screen.getAllByRole('button', {name: 'Create table'})[1]);

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
    fireEvent.click(screen.getAllByRole('button', {name: 'Create table'})[1]);
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
    fireEvent.click(screen.getAllByRole('button', {name: 'Create table'})[1]);
    expect(await screen.findByText(/Check your connection/)).toBeInTheDocument();
    expect(screen.queryByText('SQS unavailable')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Table name')).toBeInTheDocument();
  });
});
