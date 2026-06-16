import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { RenameDialog } from './RenameDialog';

function setup(overrides?: { kind?: 'file' | 'folder'; isBusy?: boolean }) {
  const onRename = vi.fn();
  const onCancel = vi.fn();
  render(
    <RenameDialog
      kind={overrides?.kind ?? 'file'}
      currentName="report.pdf"
      isBusy={overrides?.isBusy}
      onRename={onRename}
      onCancel={onCancel}
    />,
  );
  return { onRename, onCancel };
}

describe('RenameDialog', () => {
  it('prefills the current name and disables Rename until it changes', () => {
    setup();
    const input = screen.getByLabelText(/new name/i) as HTMLInputElement;
    expect(input.value).toBe('report.pdf');
    expect(screen.getByRole('button', { name: /^rename$/i })).toBeDisabled();
  });

  it('enables Rename for a changed, valid name and submits it', () => {
    const { onRename } = setup();
    fireEvent.change(screen.getByLabelText(/new name/i), {
      target: { value: 'final.pdf' },
    });
    const btn = screen.getByRole('button', { name: /^rename$/i });
    expect(btn).toBeEnabled();
    fireEvent.click(btn);
    expect(onRename).toHaveBeenCalledWith('final.pdf');
  });

  it('rejects an invalid name (contains a slash) and keeps Rename disabled', () => {
    setup();
    fireEvent.change(screen.getByLabelText(/new name/i), {
      target: { value: 'a/b' },
    });
    expect(screen.getByRole('alert')).toHaveTextContent('/');
    expect(screen.getByRole('button', { name: /^rename$/i })).toBeDisabled();
  });

  it('cancels on Escape', () => {
    const { onCancel } = setup();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('shows progress and disables actions while busy', () => {
    setup({ isBusy: true });
    expect(screen.getByRole('button', { name: /renaming/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled();
  });
});
