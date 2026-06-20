import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { Modal } from './Modal';

describe('Modal', () => {
  it('renders children with the role + aria-label', () => {
    render(
      <Modal ariaLabel="Test modal" onDismiss={vi.fn()}>
        <p>body</p>
      </Modal>,
    );
    const dialog = screen.getByRole('dialog', { name: 'Test modal' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByText('body')).toBeInTheDocument();
  });

  it('supports the alertdialog role', () => {
    render(
      <Modal ariaLabel="Alert" role="alertdialog" onDismiss={vi.fn()}>
        x
      </Modal>,
    );
    expect(screen.getByRole('alertdialog', { name: 'Alert' })).toBeInTheDocument();
  });

  it('dismisses on backdrop click and Escape; not on panel click', () => {
    const onDismiss = vi.fn();
    render(
      <Modal ariaLabel="M" onDismiss={onDismiss}>
        <button>inside</button>
      </Modal>,
    );
    // Click on the panel (its content) does not dismiss.
    fireEvent.click(screen.getByRole('button', { name: 'inside' }));
    expect(onDismiss).not.toHaveBeenCalled();
    // Escape dismisses.
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('does not dismiss when not dismissible', () => {
    const onDismiss = vi.fn();
    render(
      <Modal ariaLabel="M" dismissible={false} onDismiss={onDismiss}>
        x
      </Modal>,
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it('blurs the content behind via the scrim', () => {
    render(
      <Modal ariaLabel="M" onDismiss={vi.fn()}>
        x
      </Modal>,
    );
    const scrim = screen.getByRole('dialog').parentElement!;
    expect(scrim).toHaveClass('backdrop-blur-sm');
  });

  it('restores focus to the trigger when it closes (focus trap)', async () => {
    function Harness({ open }: { open: boolean }) {
      return (
        <>
          <button>trigger</button>
          {open ? (
            <Modal ariaLabel="M" onDismiss={vi.fn()}>
              <button>inside</button>
            </Modal>
          ) : null}
        </>
      );
    }
    const { rerender } = render(<Harness open={false} />);
    const trigger = screen.getByRole('button', { name: 'trigger' });
    trigger.focus();
    expect(trigger).toHaveFocus();

    rerender(<Harness open />);
    rerender(<Harness open={false} />);
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
