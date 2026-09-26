import {describe, expect, it, vi} from 'vitest';
import {act, screen} from '@testing-library/react';
import {renderWithProviders} from '../test/renderWithProviders';
import {withFakeTimers} from '../test/fakeTimers';
import {useToast} from './toastContext';

/** A control that pushes one fixed toast — the provider itself comes from the harness. */
function PushSaved() {
  const {push} = useToast();
  return (
    <button
      type="button"
      onClick={() => push({variant: 'success', message: 'Saved'})}>
      Save
    </button>
  );
}

describe('ToastProvider', () => {
  it('gives a repeated message its own full display time', async () => {
    await withFakeTimers(async () => {
      const {user} = renderWithProviders(<PushSaved />);
      await user.click(screen.getByRole('button', {name: 'Save'}));
      await act(() => vi.advanceTimersByTimeAsync(3_000));

      await user.click(screen.getByRole('button', {name: 'Save'}));
      await act(() => vi.advanceTimersByTimeAsync(2_000));

      // Five seconds after the first push and two after the second: the first push's timer
      // would already have removed it.
      expect(screen.getByRole('status')).toHaveTextContent('Saved');
    });
  });
});
