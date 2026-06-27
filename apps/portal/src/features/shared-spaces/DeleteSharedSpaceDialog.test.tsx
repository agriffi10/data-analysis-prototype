import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {DeleteSharedSpaceDialog} from './DeleteSharedSpaceDialog';

describe('DeleteSharedSpaceDialog (SPEC-054)', () => {
  it('keeps Delete disabled until the exact name is typed', () => {
    const onConfirm = vi.fn();
    render(
      <DeleteSharedSpaceDialog
        space="sales"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />
    );
    const confirm = screen.getByRole('button', {name: 'Delete'});
    expect(confirm).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/to confirm/), {target: {value: 'sale'}});
    expect(confirm).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/to confirm/), {target: {value: 'sales'}});
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('Enter confirms only once the name matches', () => {
    const onConfirm = vi.fn();
    render(
      <DeleteSharedSpaceDialog
        space="sales"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />
    );
    const field = screen.getByLabelText(/to confirm/);

    fireEvent.keyDown(field, {key: 'Enter'});
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.change(field, {target: {value: 'sales'}});
    fireEvent.keyDown(field, {key: 'Enter'});
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('marks the action irreversible', () => {
    render(
      <DeleteSharedSpaceDialog
        space="sales"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByText(/can.t be undone/i)).toBeInTheDocument();
  });
});
