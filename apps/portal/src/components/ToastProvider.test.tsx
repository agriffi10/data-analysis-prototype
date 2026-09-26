import {describe, expect, it, vi} from 'vitest';
import {useRef} from 'react';
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

/** A slow action's notice, a later toast, and the slow action landing — the three moves of a dismiss race. */
function SlowAction() {
  const {push, dismiss} = useToast();
  const notice = useRef<number | undefined>(undefined);
  return (
    <>
      <button
        type="button"
        onClick={() => (notice.current = push({variant: 'info', message: 'Loading'}))}>
        Start
      </button>
      <button
        type="button"
        onClick={() => push({variant: 'danger', message: 'Something else failed'})}>
        Fail elsewhere
      </button>
      <button
        type="button"
        onClick={() => dismiss(notice.current)}>
        Land
      </button>
    </>
  );
}

describe('ToastProvider', () => {
  it('closes whichever toast is showing from its own Dismiss button', async () => {
    const {user} = renderWithProviders(<SlowAction />);
    await user.click(screen.getByRole('button', {name: 'Start'}));
    await user.click(screen.getByRole('button', {name: 'Fail elsewhere'}));
    expect(screen.getByRole('alert')).toHaveTextContent('Something else failed');

    await user.click(screen.getByRole('button', {name: 'Dismiss'}));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  // The first push after a mount is the id a count restarted on close would hand out again.
  it('never gives a closed toast’s id to a later toast', async () => {
    const {user} = renderWithProviders(<SlowAction />);
    await user.click(screen.getByRole('button', {name: 'Start'}));
    await user.click(screen.getByRole('button', {name: 'Dismiss'}));

    await user.click(screen.getByRole('button', {name: 'Fail elsewhere'}));
    await user.click(screen.getByRole('button', {name: 'Land'}));

    expect(screen.getByRole('alert')).toHaveTextContent('Something else failed');
  });

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
