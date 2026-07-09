import {describe, it, expect, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {BatchOverwritePrompt} from './BatchOverwritePrompt';

describe('BatchOverwritePrompt', () => {
  it('names the conflicting count and wires Overwrite all / Cancel', async () => {
    const onOverwriteAll = vi.fn();
    const onCancel = vi.fn();
    const {user} = renderWithProviders(
      <BatchOverwritePrompt
        count={3}
        onOverwriteAll={onOverwriteAll}
        onCancel={onCancel}
      />
    );
    expect(screen.getByRole('alertdialog', {name: 'Destination already has items'})).toBeInTheDocument();
    expect(screen.getByText(/3 item\(s\) already exist/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: 'Overwrite all'}));
    expect(onOverwriteAll).toHaveBeenCalledOnce();
    await user.click(screen.getByRole('button', {name: 'Cancel'}));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
