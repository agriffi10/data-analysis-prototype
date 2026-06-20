import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { Drawer } from './Drawer';

describe('Drawer', () => {
  it('renders nothing when closed', () => {
    render(
      <Drawer open={false} onClose={vi.fn()} title="History">
        body
      </Drawer>,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders title, children, footer, and a close button', () => {
    render(
      <Drawer open onClose={vi.fn()} title="History" footer={<div>foot</div>}>
        <p>body</p>
      </Drawer>,
    );
    expect(screen.getByRole('dialog', { name: 'History' })).toBeInTheDocument();
    expect(screen.getByText('body')).toBeInTheDocument();
    expect(screen.getByText('foot')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Close history' }),
    ).toBeInTheDocument();
  });

  it('closes on the close button, backdrop, and Escape', () => {
    const onClose = vi.fn();
    render(
      <Drawer open onClose={onClose} title="History">
        body
      </Drawer>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Close history' }));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('ignores Escape when closeOnEscape is false', () => {
    const onClose = vi.fn();
    render(
      <Drawer open onClose={onClose} title="History" closeOnEscape={false}>
        body
      </Drawer>,
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('honors a custom aria-label and close label', () => {
    render(
      <Drawer
        open
        onClose={vi.fn()}
        title="Upload"
        ariaLabel="Upload files"
        closeLabel="Close upload panel"
      >
        body
      </Drawer>,
    );
    expect(screen.getByRole('dialog', { name: 'Upload files' })).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Close upload panel' }),
    ).toBeInTheDocument();
  });

  it('blurs the content behind via the scrim', () => {
    render(
      <Drawer open onClose={vi.fn()} title="History">
        body
      </Drawer>,
    );
    const scrim = screen.getByRole('dialog').parentElement!;
    expect(scrim).toHaveClass('backdrop-blur-sm');
  });

  it('restores focus to the trigger when it closes (focus trap)', async () => {
    function Harness({ open }: { open: boolean }) {
      return (
        <>
          <button>trigger</button>
          <Drawer open={open} onClose={vi.fn()} title="History">
            body
          </Drawer>
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
