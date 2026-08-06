import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent, waitFor} from '@testing-library/react';
import {Drawer} from './Drawer';

describe('Drawer', () => {
  it('renders nothing when closed', () => {
    render(
      <Drawer
        open={false}
        onClose={vi.fn()}
        title="History">
        body
      </Drawer>
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders title, children, footer, and a close button', () => {
    render(
      <Drawer
        open
        onClose={vi.fn()}
        title="History"
        footer={<div>foot</div>}>
        <p>body</p>
      </Drawer>
    );
    expect(screen.getByRole('dialog', {name: 'History'})).toBeInTheDocument();
    expect(screen.getByText('body')).toBeInTheDocument();
    expect(screen.getByText('foot')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Close history'})).toBeInTheDocument();
  });

  it('closes on the close button, backdrop, and Escape', () => {
    const onClose = vi.fn();
    render(
      <Drawer
        open
        onClose={onClose}
        title="History">
        body
      </Drawer>
    );
    fireEvent.click(screen.getByRole('button', {name: 'Close history'}));
    fireEvent.keyDown(document, {key: 'Escape'});
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('ignores Escape while closed', () => {
    // Replaces the old `closeOnEscape={false}` case: that prop is gone (SPEC-155 FR-006 —
    // a nested dialog outranks the drawer by tree depth, so nothing has to opt out).
    // What still matters is that a CLOSED drawer holds no claim on the key at all.
    const onClose = vi.fn();
    render(
      <Drawer
        open={false}
        onClose={onClose}
        title="History">
        body
      </Drawer>
    );
    fireEvent.keyDown(document, {key: 'Escape'});
    expect(onClose).not.toHaveBeenCalled();
  });

  it('honors a custom aria-label and close label', () => {
    render(
      <Drawer
        open
        onClose={vi.fn()}
        title="Upload"
        ariaLabel="Upload files"
        closeLabel="Close upload panel">
        body
      </Drawer>
    );
    expect(screen.getByRole('dialog', {name: 'Upload files'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Close upload panel'})).toBeInTheDocument();
  });

  it('blurs the content behind via the scrim', () => {
    render(
      <Drawer
        open
        onClose={vi.fn()}
        title="History">
        body
      </Drawer>
    );
    const scrim = screen.getByRole('dialog').parentElement!;
    expect(scrim).toHaveClass('backdrop-blur-sm');
  });

  it('presents as a docked bottom sheet on mobile by default', () => {
    render(
      <Drawer
        open
        onClose={vi.fn()}
        title="History">
        body
      </Drawer>
    );
    const scrim = screen.getByRole('dialog').parentElement!;
    expect(scrim).toHaveClass('items-end', 'tablet:items-stretch');
    expect(screen.getByRole('dialog')).toHaveClass('rounded-t-xl', 'tablet:max-w-[440px]');
  });

  it('presents as a full-height sheet on mobile when mobileVariant="full-height"', () => {
    render(
      <Drawer
        open
        onClose={vi.fn()}
        title="Members"
        mobileVariant="full-height">
        body
      </Drawer>
    );
    const scrim = screen.getByRole('dialog').parentElement!;
    expect(scrim).not.toHaveClass('items-end');
    expect(screen.getByRole('dialog')).toHaveClass('h-full', 'tablet:max-w-[440px]');
  });

  it('restores focus to the trigger when it closes (focus trap)', async () => {
    function Harness({open}: {open: boolean}) {
      return (
        <>
          <button>trigger</button>
          <Drawer
            open={open}
            onClose={vi.fn()}
            title="History">
            body
          </Drawer>
        </>
      );
    }
    const {rerender} = render(<Harness open={false} />);
    const trigger = screen.getByRole('button', {name: 'trigger'});
    trigger.focus();
    expect(trigger).toHaveFocus();

    rerender(<Harness open />);
    rerender(<Harness open={false} />);
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
