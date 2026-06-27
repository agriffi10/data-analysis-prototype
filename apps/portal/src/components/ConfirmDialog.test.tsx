import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {ConfirmDialog} from './ConfirmDialog';

const base = {
  title: 'Delete it?',
  ariaLabel: 'Confirm delete',
  confirmLabel: 'Delete',
  onConfirm: vi.fn(),
  onCancel: vi.fn()
};

describe('ConfirmDialog', () => {
  it('renders title, body, and confirm/cancel; wires the handlers', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        {...base}
        onConfirm={onConfirm}
        onCancel={onCancel}>
        <p>the body</p>
      </ConfirmDialog>
    );
    expect(screen.getByRole('alertdialog', {name: 'Confirm delete'})).toBeInTheDocument();
    expect(screen.getByText('the body')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', {name: 'Delete'}));
    expect(onConfirm).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));
    expect(onCancel).toHaveBeenCalled();
  });

  it('focuses Cancel by default', () => {
    render(<ConfirmDialog {...base} />);
    expect(screen.getByRole('button', {name: 'Cancel'})).toHaveFocus();
  });

  it('appends the irreversible line when set', () => {
    render(
      <ConfirmDialog
        {...base}
        irreversible
      />
    );
    expect(screen.getByText(/can’t be undone/)).toBeInTheDocument();
  });

  it('dismissOnly hides Cancel and focuses the confirm button', () => {
    render(
      <ConfirmDialog
        {...base}
        dismissOnly
        confirmLabel="Got it"
      />
    );
    expect(screen.queryByRole('button', {name: 'Cancel'})).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Got it'})).toHaveFocus();
  });

  it('busy locks both buttons and shows the busy label', () => {
    render(
      <ConfirmDialog
        {...base}
        busy
        busyLabel="Deleting…"
      />
    );
    expect(screen.getByRole('button', {name: 'Cancel'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Deleting…'})).toBeDisabled();
  });

  it('confirmDisabled disables only the confirm button, leaving Cancel live', () => {
    render(
      <ConfirmDialog
        {...base}
        confirmDisabled
      />
    );
    expect(screen.getByRole('button', {name: 'Delete'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Cancel'})).toBeEnabled();
  });
});
