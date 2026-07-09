import {describe, it, expect, vi} from 'vitest';
import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {ToastProvider} from './ToastProvider';
import {useToast} from './toastContext';

function Harness() {
  const toast = useToast();
  return (
    <div>
      <button onClick={() => toast.push({variant: 'success', message: 'Saved!'})}>push-success</button>
      <button
        onClick={() => toast.push({variant: 'danger', message: 'Failed', action: {label: 'Retry', onClick: () => {}}})}>
        push-action
      </button>
      <button onClick={() => toast.dismiss()}>dismiss</button>
    </div>
  );
}

function renderHarness() {
  return render(
    <ToastProvider>
      <Harness />
    </ToastProvider>
  );
}

describe('ToastProvider / useToast', () => {
  it('pushes a toast that renders, and dismiss clears it', async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByText('push-success'));
    expect(await screen.findByText('Saved!')).toBeInTheDocument();
    await user.click(screen.getByText('dismiss'));
    expect(screen.queryByText('Saved!')).not.toBeInTheDocument();
  });

  it('a new push replaces the current toast (single-toast semantics)', async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByText('push-success'));
    await user.click(screen.getByText('push-action'));
    expect(screen.queryByText('Saved!')).not.toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    // The actionable toast keeps its action button reachable.
    expect(screen.getByRole('button', {name: 'Retry'})).toBeInTheDocument();
  });

  it('throws when useToast is used with no provider', () => {
    // Silence the expected React error boundary console noise.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Harness />)).toThrow(/ToastProvider/);
    spy.mockRestore();
  });
});
