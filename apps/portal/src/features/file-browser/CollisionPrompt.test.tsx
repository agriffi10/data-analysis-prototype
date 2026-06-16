import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { CollisionPrompt } from './CollisionPrompt';

function setup(overrides = {}) {
  const props = {
    kind: 'file' as const,
    name: 'report.pdf',
    onOverwrite: vi.fn(),
    onRename: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  };
  render(<CollisionPrompt {...props} />);
  return props;
}

describe('CollisionPrompt', () => {
  it('overwrites on confirm', () => {
    const { onOverwrite } = setup();
    fireEvent.click(screen.getByRole('button', { name: /overwrite/i }));
    expect(onOverwrite).toHaveBeenCalled();
  });

  it('cancels', () => {
    const { onCancel } = setup();
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
  });

  it('renames with the new name', () => {
    const { onRename } = setup();
    fireEvent.click(screen.getByRole('button', { name: /^rename$/i }));
    fireEvent.change(screen.getByLabelText(/new name/i), {
      target: { value: 'report-v2.pdf' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save as new name/i }));
    expect(onRename).toHaveBeenCalledWith('report-v2.pdf');
  });

  it('disables save when the new name is unchanged', () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: /^rename$/i }));
    // input still equals the original name → save disabled
    expect(screen.getByRole('button', { name: /save as new name/i })).toBeDisabled();
  });
});
