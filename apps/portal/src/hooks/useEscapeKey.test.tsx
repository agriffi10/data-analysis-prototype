import {useState} from 'react';
import {describe, it, expect, vi} from 'vitest';
import {render, renderHook, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {fireEvent} from '@testing-library/dom';
import {useEscapeKey} from './useEscapeKey';
import {Drawer} from '../components/Drawer';
import {Modal} from '../components/Modal';
import {ConfirmDialog} from '../components/ConfirmDialog';

describe('useEscapeKey', () => {
  it('calls the handler on Escape while enabled', () => {
    const onEscape = vi.fn();
    renderHook(() => useEscapeKey(onEscape));
    fireEvent.keyDown(document, {key: 'Escape'});
    expect(onEscape).toHaveBeenCalledTimes(1);
  });

  it('ignores other keys', () => {
    const onEscape = vi.fn();
    renderHook(() => useEscapeKey(onEscape));
    fireEvent.keyDown(document, {key: 'Enter'});
    expect(onEscape).not.toHaveBeenCalled();
  });

  it('does nothing when disabled', () => {
    const onEscape = vi.fn();
    renderHook(() => useEscapeKey(onEscape, false));
    fireEvent.keyDown(document, {key: 'Escape'});
    expect(onEscape).not.toHaveBeenCalled();
  });

  it('removes the listener on unmount', () => {
    const onEscape = vi.fn();
    const {unmount} = renderHook(() => useEscapeKey(onEscape));
    unmount();
    fireEvent.keyDown(document, {key: 'Escape'});
    expect(onEscape).not.toHaveBeenCalled();
  });
});

/**
 * These drive the REAL `Drawer`/`Modal`/`ConfirmDialog` composition, not two synthetic
 * hook roots. That distinction is the whole point: an earlier implementation ordered
 * layers by registration time and passed a synthetic test while getting every real
 * nesting backwards — child effects run before their parent's, so "registered last" is
 * the OUTER layer.
 */
describe('Escape goes to the deepest layer (SPEC-155 FR-006)', () => {
  function DrawerWithDialog({onDrawerClose, onDialogClose}: {onDrawerClose: () => void; onDialogClose: () => void}) {
    const [dialogOpen, setDialogOpen] = useState(false);
    const [tick, setTick] = useState(0);
    return (
      <Drawer
        open
        onClose={onDrawerClose}
        title="Manage members">
        <button onClick={() => setDialogOpen(true)}>Add members</button>
        {/* Re-rendering the drawer's owner is what used to reorder the layers. */}
        <button onClick={() => setTick((t) => t + 1)}>Poll {tick}</button>
        {dialogOpen && (
          <ConfirmDialog
            title="Add members"
            ariaLabel="Add members"
            confirmLabel="Add"
            onConfirm={vi.fn()}
            onCancel={() => {
              setDialogOpen(false);
              onDialogClose();
            }}
          />
        )}
      </Drawer>
    );
  }

  it('closes a dialog opened inside a drawer, and leaves the drawer open', async () => {
    const user = userEvent.setup();
    const onDrawerClose = vi.fn();
    const onDialogClose = vi.fn();
    render(
      <DrawerWithDialog
        onDrawerClose={onDrawerClose}
        onDialogClose={onDialogClose}
      />
    );

    await user.click(screen.getByRole('button', {name: 'Add members'}));
    await user.keyboard('{Escape}');

    expect(onDialogClose).toHaveBeenCalledTimes(1);
    expect(onDrawerClose).not.toHaveBeenCalled();
  });

  it('still does, after the drawer’s owner re-renders', async () => {
    // The regression this pins: with `[onEscape]` in the effect deps and an inline
    // arrow at every call site, one re-render re-registered the drawer on top and
    // Escape started closing the drawer instead — discarding whatever was typed.
    const user = userEvent.setup();
    const onDrawerClose = vi.fn();
    const onDialogClose = vi.fn();
    render(
      <DrawerWithDialog
        onDrawerClose={onDrawerClose}
        onDialogClose={onDialogClose}
      />
    );

    await user.click(screen.getByRole('button', {name: 'Add members'}));
    await user.click(screen.getByRole('button', {name: /^Poll/}));
    await user.keyboard('{Escape}');

    expect(onDialogClose).toHaveBeenCalledTimes(1);
    expect(onDrawerClose).not.toHaveBeenCalled();
  });

  it('gets a SAME-COMMIT nesting right, where registration order is inverted', async () => {
    // Both layers mount in one commit, and React runs the child's effect FIRST — so
    // "most recently registered" names the drawer, not the dialog. Only depth from the
    // tree separates them, which is why this fixture opens the dialog on first render
    // rather than by a click.
    const user = userEvent.setup();
    const onDrawerClose = vi.fn();
    const onDialogClose = vi.fn();
    render(
      <Drawer
        open
        onClose={onDrawerClose}
        title="Manage members">
        <ConfirmDialog
          title="Remove member"
          ariaLabel="Confirm remove"
          confirmLabel="Remove"
          onConfirm={vi.fn()}
          onCancel={onDialogClose}
        />
      </Drawer>
    );

    await user.keyboard('{Escape}');

    expect(onDialogClose).toHaveBeenCalledTimes(1);
    expect(onDrawerClose).not.toHaveBeenCalled();
  });

  it('returns Escape to the drawer once the dialog closes', async () => {
    const user = userEvent.setup();
    const onDrawerClose = vi.fn();
    render(
      <DrawerWithDialog
        onDrawerClose={onDrawerClose}
        onDialogClose={vi.fn()}
      />
    );

    await user.click(screen.getByRole('button', {name: 'Add members'}));
    await user.keyboard('{Escape}'); // closes the dialog
    await user.keyboard('{Escape}'); // now the drawer's turn

    expect(onDrawerClose).toHaveBeenCalledTimes(1);
  });

  it('a busy modal SWALLOWS Escape rather than letting it dismiss the drawer behind it', async () => {
    // `dismissible={false}` means "not now" — it must not become "dismiss the layer
    // underneath instead", which is what fall-through did while a request was in flight.
    const user = userEvent.setup();
    const onDrawerClose = vi.fn();
    const onModalDismiss = vi.fn();
    render(
      <Drawer
        open
        onClose={onDrawerClose}
        title="Manage members">
        <Modal
          ariaLabel="Removing member"
          dismissible={false}
          onDismiss={onModalDismiss}>
          <p>Removing…</p>
        </Modal>
      </Drawer>
    );

    await user.keyboard('{Escape}');

    expect(onModalDismiss).not.toHaveBeenCalled();
    expect(onDrawerClose).not.toHaveBeenCalled();
  });

  it('a CLOSED drawer holds nothing — Escape reaches the dialog beside it', async () => {
    // `Drawer` calls the hook before its own `open` early-return, so a closed drawer
    // must register nothing at all; otherwise it would swallow the key for its depth.
    const user = userEvent.setup();
    const onDrawerClose = vi.fn();
    const onDialogClose = vi.fn();
    render(
      <>
        <Drawer
          open={false}
          onClose={onDrawerClose}
          title="History">
          <p>Nothing here while closed.</p>
        </Drawer>
        <ConfirmDialog
          title="Delete saved query?"
          ariaLabel="Confirm delete"
          confirmLabel="Delete"
          onConfirm={vi.fn()}
          onCancel={onDialogClose}
        />
      </>
    );

    await user.keyboard('{Escape}');

    expect(onDialogClose).toHaveBeenCalledTimes(1);
    expect(onDrawerClose).not.toHaveBeenCalled();
  });

  it('a dialog rendered BESIDE an open drawer still wins — it mounted later', async () => {
    // `SavedQueriesPanel` renders its confirm as a sibling of the drawer, not a child,
    // so depth alone cannot separate them; the newest layer at a depth is on top.
    const user = userEvent.setup();
    const onDrawerClose = vi.fn();
    const onDialogClose = vi.fn();

    function PanelWithSiblingDialog() {
      const [confirming, setConfirming] = useState(false);
      const [tick, setTick] = useState(0);
      return (
        <>
          <Drawer
            open
            // Inline, as every real call site is — a stable handler would hide a
            // re-registration bug behind an identity that never changes.
            onClose={() => onDrawerClose()}
            title="Saved queries">
            <button onClick={() => setConfirming(true)}>Delete</button>
            <button onClick={() => setTick((t) => t + 1)}>Poll {tick}</button>
          </Drawer>
          {confirming && (
            <ConfirmDialog
              title="Delete saved query?"
              ariaLabel="Confirm delete"
              confirmLabel="Delete"
              onConfirm={vi.fn()}
              onCancel={onDialogClose}
            />
          )}
        </>
      );
    }

    render(<PanelWithSiblingDialog />);
    await user.click(screen.getByRole('button', {name: 'Delete'}));
    // …and a re-render must not hand the drawer its layer back: at equal depth the
    // order is fixed at mount, which is why the effect does not depend on `onEscape`.
    await user.click(screen.getByRole('button', {name: /^Poll/}));
    await user.keyboard('{Escape}');

    expect(onDialogClose).toHaveBeenCalledTimes(1);
    expect(onDrawerClose).not.toHaveBeenCalled();
  });
});
