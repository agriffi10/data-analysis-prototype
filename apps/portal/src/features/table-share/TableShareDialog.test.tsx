import {describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen, within} from '@testing-library/react';
import {TableShareDialog} from './TableShareDialog';

const SOURCE = {database: 'alice', table: 'orders'};

function renderDialog(over: Partial<React.ComponentProps<typeof TableShareDialog>> = {}) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  render(
    <TableShareDialog
      source={SOURCE}
      onSubmit={onSubmit}
      onCancel={onCancel}
      {...over}
    />
  );
  return {onSubmit, onCancel};
}

const entryInput = () => screen.getByLabelText(/Usernames|Space names/) as HTMLInputElement;
const addButton = () => screen.getByRole('button', {name: 'Add'});
const shareButton = () => screen.getByRole('button', {name: /Share|Submitting/});

function addRecipients(raw: string) {
  fireEvent.change(entryInput(), {target: {value: raw}});
  fireEvent.click(addButton());
}

describe('TableShareDialog', () => {
  it('shows the fully-qualified source read-only and defaults the result name to the source table', () => {
    renderDialog();
    expect(screen.getByText('alice.orders')).toBeInTheDocument();
    expect(screen.getByLabelText('Table name for recipients')).toHaveValue('orders');
  });

  it('adds comma/space-separated names as removable chips tagged with the selected kind', () => {
    renderDialog();
    addRecipients('bob, cara');
    const chips = screen.getByRole('list', {name: 'Recipients'});
    expect(within(chips).getAllByRole('listitem')).toHaveLength(2);
    expect(within(chips).getByRole('button', {name: 'Remove user bob'})).toBeInTheDocument();
    // The entry box clears after an add.
    expect(entryInput()).toHaveValue('');

    fireEvent.click(within(chips).getByRole('button', {name: 'Remove user bob'}));
    expect(within(chips).queryByRole('button', {name: 'Remove user bob'})).not.toBeInTheDocument();
    expect(within(chips).getByRole('button', {name: 'Remove user cara'})).toBeInTheDocument();
  });

  it('tags entries added under "Shared spaces" as spaces (a mixed list is allowed)', () => {
    renderDialog();
    addRecipients('bob');
    fireEvent.click(screen.getByRole('radio', {name: 'Shared spaces'}));
    addRecipients('salesteam');
    const chips = screen.getByRole('list', {name: 'Recipients'});
    expect(within(chips).getByRole('button', {name: 'Remove user bob'})).toBeInTheDocument();
    expect(within(chips).getByRole('button', {name: 'Remove space salesteam'})).toBeInTheDocument();
  });

  it('Enter in the recipient input adds names instead of submitting', () => {
    const {onSubmit} = renderDialog();
    fireEvent.change(entryInput(), {target: {value: 'bob'}});
    fireEvent.keyDown(entryInput(), {key: 'Enter'});
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('button', {name: 'Remove user bob'})).toBeInTheDocument();
  });

  it('drops malformed tokens and dedupes an already-added name of the same kind', () => {
    renderDialog();
    addRecipients('bob, 1bad, -x');
    addRecipients('bob');
    const chips = screen.getByRole('list', {name: 'Recipients'});
    expect(within(chips).getAllByRole('listitem')).toHaveLength(1);
    // With only invalid/duplicate names pending, Add stays disabled.
    fireEvent.change(entryInput(), {target: {value: 'bob 1bad'}});
    expect(addButton()).toBeDisabled();
  });

  it('disables Share until there is at least one recipient and a valid name', () => {
    const {onSubmit} = renderDialog();
    expect(shareButton()).toBeDisabled();

    addRecipients('bob');
    expect(shareButton()).toBeEnabled();

    const nameInput = screen.getByLabelText('Table name for recipients');
    fireEvent.change(nameInput, {target: {value: 'Bad-Name'}});
    expect(screen.getByText(/Use 3–63 characters/)).toBeInTheDocument();
    expect(shareButton()).toBeDisabled();

    fireEvent.change(nameInput, {target: {value: 'orders_copy'}});
    fireEvent.click(shareButton());
    expect(onSubmit).toHaveBeenCalledWith({
      tableName: 'orders_copy',
      recipients: [{kind: 'user', name: 'bob'}]
    });
  });

  it('locks the form while busy and surfaces a submit error inline', () => {
    renderDialog({busy: true, submitError: 'Failed to submit the request'});
    expect(screen.getByRole('button', {name: 'Submitting…'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Cancel'})).toBeDisabled();
    expect(entryInput()).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to submit the request');
  });

  it('Cancel invokes onCancel', () => {
    const {onCancel} = renderDialog();
    fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));
    expect(onCancel).toHaveBeenCalled();
  });
});
