import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {LeaveSharedSpaceDialog} from './LeaveSharedSpaceDialog';

describe('LeaveSharedSpaceDialog (SPEC-054)', () => {
  it('confirms and cancels via the shared danger dialog', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <LeaveSharedSpaceDialog
        space="sales"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );
    expect(screen.getByRole('alertdialog', {name: 'Leave sales'})).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Leave'}));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('shows the busy label and locks confirm while in flight', () => {
    render(
      <LeaveSharedSpaceDialog
        space="sales"
        busy
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByRole('button', {name: 'Leaving…'})).toBeDisabled();
  });
});
