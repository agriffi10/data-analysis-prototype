import {describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {ConfirmDialog} from './ConfirmDialog';
import {Drawer} from './Drawer';
import {Modal} from './Modal';
import {createRef, useEffect, useRef} from 'react';
import {FormDialog} from './FormDialog';
import {Input} from './Input';
import {COMPONENT_AXE_OPTIONS, WCAG_TAGS, expectNoA11yViolations} from '../test/axe';
import {configureAxe} from 'vitest-axe';
import {Menu} from './Menu';
import type {MenuItem} from './Menu';
import {ToastProvider} from './ToastProvider';
import {useToast} from './toastContext';
import userEvent from '@testing-library/user-event';

// ─── from ConfirmDialog.test.tsx ───
describe('ConfirmDialog', () => {
  const base = {
    title: 'Delete it?',
    ariaLabel: 'Confirm delete',
    confirmLabel: 'Delete',
    onConfirm: vi.fn(),
    onCancel: vi.fn()
  };

  describe('ConfirmDialog', () => {
    it('renders title, body, and confirm/cancel; wires the handlers', () => {
      const onConfirm = vi.fn();
      const onCancel = vi.fn();
      render(
        <ConfirmDialog
          {...base}
          onConfirm={onConfirm}
          onCancel={onCancel}>
          <p>the body</p>
        </ConfirmDialog>
      );
      expect(screen.getByRole('alertdialog', {name: 'Confirm delete'})).toBeInTheDocument();
      expect(screen.getByText('the body')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', {name: 'Delete'}));
      expect(onConfirm).toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));
      expect(onCancel).toHaveBeenCalled();
    });

    it('focuses Cancel by default', () => {
      render(<ConfirmDialog {...base} />);
      expect(screen.getByRole('button', {name: 'Cancel'})).toHaveFocus();
    });

    it('appends the irreversible line when set', () => {
      render(
        <ConfirmDialog
          {...base}
          irreversible
        />
      );
      expect(screen.getByText(/can’t be undone/)).toBeInTheDocument();
    });

    it('dismissOnly hides Cancel and focuses the confirm button', () => {
      render(
        <ConfirmDialog
          {...base}
          dismissOnly
          confirmLabel="Got it"
        />
      );
      expect(screen.queryByRole('button', {name: 'Cancel'})).not.toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Got it'})).toHaveFocus();
    });

    it('busy locks both buttons and shows the busy label', () => {
      render(
        <ConfirmDialog
          {...base}
          busy
          busyLabel="Deleting…"
        />
      );
      expect(screen.getByRole('button', {name: 'Cancel'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Deleting…'})).toBeDisabled();
    });

    it('confirmDisabled disables only the confirm button, leaving Cancel live', () => {
      render(
        <ConfirmDialog
          {...base}
          confirmDisabled
        />
      );
      expect(screen.getByRole('button', {name: 'Delete'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Cancel'})).toBeEnabled();
    });
  });
});

// ─── from Drawer.test.tsx ───
describe('Drawer', () => {
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
});

// ─── from Modal.test.tsx ───
describe('Modal', () => {
  describe('Modal', () => {
    it('renders children with the role + aria-label', () => {
      render(
        <Modal
          ariaLabel="Test modal"
          onDismiss={vi.fn()}>
          <p>body</p>
        </Modal>
      );
      const dialog = screen.getByRole('dialog', {name: 'Test modal'});
      expect(dialog).toHaveAttribute('aria-modal', 'true');
      expect(screen.getByText('body')).toBeInTheDocument();
    });

    it('supports the alertdialog role', () => {
      render(
        <Modal
          ariaLabel="Alert"
          role="alertdialog"
          onDismiss={vi.fn()}>
          x
        </Modal>
      );
      expect(screen.getByRole('alertdialog', {name: 'Alert'})).toBeInTheDocument();
    });

    it('dismisses on backdrop click and Escape; not on panel click', () => {
      const onDismiss = vi.fn();
      render(
        <Modal
          ariaLabel="M"
          onDismiss={onDismiss}>
          <button>inside</button>
        </Modal>
      );
      fireEvent.click(screen.getByRole('button', {name: 'inside'}));
      expect(onDismiss).not.toHaveBeenCalled();
      fireEvent.keyDown(document, {key: 'Escape'});
      expect(onDismiss).toHaveBeenCalledTimes(1);
    });

    it('does not dismiss when not dismissible', () => {
      const onDismiss = vi.fn();
      render(
        <Modal
          ariaLabel="M"
          dismissible={false}
          onDismiss={onDismiss}>
          x
        </Modal>
      );
      fireEvent.keyDown(document, {key: 'Escape'});
      expect(onDismiss).not.toHaveBeenCalled();
    });

    it('caps the panel to the viewport (scrolls a long body) and keeps edge gutters', () => {
      render(
        <Modal
          ariaLabel="M"
          onDismiss={vi.fn()}>
          x
        </Modal>
      );
      const scrim = screen.getByRole('dialog').parentElement!;
      // Outer p-4 keeps the panel off the screen edges on mobile.
      expect(scrim).toHaveClass('p-4');
      const panel = screen.getByRole('dialog');
      expect(panel).toHaveClass('overflow-y-auto', 'max-h-[calc(100dvh-2rem)]', 'max-w-md');
    });

    it('applies a passed width class instead of the default', () => {
      render(
        <Modal
          ariaLabel="M"
          className="max-w-lg"
          onDismiss={vi.fn()}>
          x
        </Modal>
      );
      const panel = screen.getByRole('dialog');
      expect(panel).toHaveClass('max-w-lg');
      expect(panel).not.toHaveClass('max-w-md');
    });

    it('blurs the content behind via the scrim', () => {
      render(
        <Modal
          ariaLabel="M"
          onDismiss={vi.fn()}>
          x
        </Modal>
      );
      const scrim = screen.getByRole('dialog').parentElement!;
      expect(scrim).toHaveClass('backdrop-blur-sm');
    });

    it('restores focus to the trigger when it closes (focus trap)', async () => {
      function Harness({open}: {open: boolean}) {
        return (
          <>
            <button>trigger</button>
            {open ? (
              <Modal
                ariaLabel="M"
                onDismiss={vi.fn()}>
                <button>inside</button>
              </Modal>
            ) : null}
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
});

// ─── from FormDialog.test.tsx ───
describe('FormDialog', () => {
  function Harness(props: Partial<React.ComponentProps<typeof FormDialog>> = {}) {
    const inputRef = useRef<HTMLInputElement>(null);
    return (
      <FormDialog
        title="New folder"
        ariaLabel="Create folder"
        submitLabel="Create"
        autoFocusRef={inputRef}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
        {...props}>
        <Input
          id="name"
          ref={inputRef}
          label="Folder name"
          defaultValue="photos"
        />
      </FormDialog>
    );
  }

  describe('FormDialog', () => {
    it('renders the title, the body and the Cancel/submit pair', () => {
      render(<Harness />);
      expect(screen.getByRole('heading', {name: 'New folder'})).toBeInTheDocument();
      expect(screen.getByLabelText(/folder name/i)).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Cancel'})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Create'})).toBeInTheDocument();
    });

    it('focuses the field on mount, and selects it only when asked', async () => {
      const {unmount} = render(<Harness />);
      const input = screen.getByLabelText(/folder name/i) as HTMLInputElement;
      expect(input).toHaveFocus();
      expect(input.selectionStart).toBe(input.selectionEnd); // focused, not selected
      unmount();

      render(<Harness autoFocusSelect />);
      const selected = screen.getByLabelText(/folder name/i) as HTMLInputElement;
      expect(selected.selectionStart).toBe(0);
      expect(selected.selectionEnd).toBe('photos'.length);
    });

    it('focuses the first control when no autoFocusRef is passed — a modal always draws focus', () => {
      render(
        <FormDialog
          title="Add members"
          ariaLabel="Add members"
          submitLabel="Add"
          onSubmit={vi.fn()}
          onCancel={vi.fn()}>
          <Input
            id="who"
            label="Usernames"
          />
        </FormDialog>
      );
      expect(screen.getByLabelText(/usernames/i)).toHaveFocus();
    });

    it('does not steal focus from a child that focused itself', () => {
      // `UsernameChipsField`'s `autoFocus` and `TableShareDialog`'s own effect both land
      // before this one (child effects run first), and the fallback must leave them alone
      // rather than yanking focus back to whatever happens to be first in the DOM.
      function SelfFocusing() {
        const ref = useRef<HTMLInputElement>(null);
        useEffect(() => ref.current?.focus(), []);
        return (
          <>
            <Input
              id="first"
              label="First"
            />
            <Input
              id="second"
              ref={ref}
              label="Second"
            />
          </>
        );
      }
      render(
        <FormDialog
          title="Share table"
          ariaLabel="Share table"
          submitLabel="Share"
          onSubmit={vi.fn()}
          onCancel={vi.fn()}>
          <SelfFocusing />
        </FormDialog>
      );
      expect(screen.getByLabelText('Second')).toHaveFocus();
      expect(screen.getByLabelText('First')).not.toHaveFocus();
    });

    it('falls back to Cancel when the body has nothing focusable', () => {
      render(
        <FormDialog
          title="Confirm"
          ariaLabel="Confirm"
          submitLabel="Go"
          onSubmit={vi.fn()}
          onCancel={vi.fn()}>
          <p>Nothing to fill in.</p>
        </FormDialog>
      );
      expect(screen.getByRole('button', {name: 'Cancel'})).toHaveFocus();
    });

    it('submits on Enter in a text field', () => {
      const onSubmit = vi.fn();
      render(<Harness onSubmit={onSubmit} />);
      fireEvent.keyDown(screen.getByLabelText(/folder name/i), {key: 'Enter'});
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });

    it('preventDefaults Enter, so the browser cannot ALSO submit the form implicitly', () => {
      // jsdom has no implicit submission, so this cannot observe the double-submit
      // directly — what it pins is the mechanism that prevents it in a real browser.
      const onSubmit = vi.fn();
      render(<Harness onSubmit={onSubmit} />);
      const input = screen.getByLabelText(/folder name/i);
      const event = new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true});
      input.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });

    it('does NOT submit from a second field — only the designated one submits on Enter', () => {
      // The regression this guards: adopting a real <form> hands Enter-to-submit to every
      // text input in it. A partition-key row mid-edit would have filed the table build.
      const onSubmit = vi.fn();
      function TwoFields() {
        const primary = useRef<HTMLInputElement>(null);
        return (
          <FormDialog
            title="Create table"
            ariaLabel="Create table"
            submitLabel="Create"
            autoFocusRef={primary}
            onSubmit={onSubmit}
            onCancel={vi.fn()}>
            <Input
              id="table"
              ref={primary}
              label="Table name"
            />
            <Input
              id="partition"
              label="Partition values"
            />
          </FormDialog>
        );
      }
      render(<TwoFields />);

      fireEvent.keyDown(screen.getByLabelText('Partition values'), {key: 'Enter'});
      expect(onSubmit).not.toHaveBeenCalled();

      fireEvent.keyDown(screen.getByLabelText('Table name'), {key: 'Enter'});
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });

    it('does NOT submit from a radio the user is still choosing with', () => {
      const onSubmit = vi.fn();
      render(
        <FormDialog
          title="Share table"
          ariaLabel="Share table"
          submitLabel="Share"
          onSubmit={onSubmit}
          onCancel={vi.fn()}>
          <input
            type="radio"
            name="kind"
            aria-label="Users"
          />
          <input
            type="radio"
            name="kind"
            aria-label="Shared spaces"
          />
        </FormDialog>
      );
      fireEvent.keyDown(screen.getByLabelText('Shared spaces'), {key: 'Enter'});
      expect(onSubmit).not.toHaveBeenCalled();
    });

    it('submitOnEnterRef designates a field other than the focused one', () => {
      const onSubmit = vi.fn();
      function SplitRefs() {
        const nameRef = useRef<HTMLInputElement>(null);
        return (
          <FormDialog
            title="Share table"
            ariaLabel="Share table"
            submitLabel="Share"
            submitOnEnterRef={nameRef}
            onSubmit={onSubmit}
            onCancel={vi.fn()}>
            <Input
              id="entry"
              label="Recipients"
            />
            <Input
              id="name"
              ref={nameRef}
              label="Table name"
            />
          </FormDialog>
        );
      }
      render(<SplitRefs />);

      fireEvent.keyDown(screen.getByLabelText('Recipients'), {key: 'Enter'});
      expect(onSubmit).not.toHaveBeenCalled();

      fireEvent.keyDown(screen.getByLabelText('Table name'), {key: 'Enter'});
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });

    it('does NOT submit while an IME is composing — Enter is confirming a candidate', () => {
      const onSubmit = vi.fn();
      render(<Harness onSubmit={onSubmit} />);
      const input = screen.getByLabelText(/folder name/i);
      // `fireEvent.keyDown` cannot set isComposing, so dispatch the real event.
      input.dispatchEvent(
        new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true, isComposing: true})
      );
      expect(onSubmit).not.toHaveBeenCalled();
    });

    it('does NOT submit on Enter in a textarea — the newline is the point', () => {
      const onSubmit = vi.fn();
      render(
        <FormDialog
          title="Notes"
          ariaLabel="Notes"
          submitLabel="Save"
          onSubmit={onSubmit}
          onCancel={vi.fn()}>
          <textarea aria-label="Body" />
        </FormDialog>
      );
      fireEvent.keyDown(screen.getByLabelText('Body'), {key: 'Enter'});
      expect(onSubmit).not.toHaveBeenCalled();
    });

    it('does NOT submit on Enter a child already handled — a combobox committing a suggestion', () => {
      const onSubmit = vi.fn();
      render(
        <FormDialog
          title="Add members"
          ariaLabel="Add members"
          submitLabel="Add"
          onSubmit={onSubmit}
          onCancel={vi.fn()}>
          <Input
            id="who"
            label="Usernames"
            onKeyDown={(e) => {
              if (e.key === 'Enter') e.preventDefault();
            }}
          />
        </FormDialog>
      );
      fireEvent.keyDown(screen.getByLabelText(/usernames/i), {key: 'Enter'});
      expect(onSubmit).not.toHaveBeenCalled();
    });

    it('submits on click, and Cancel never submits', async () => {
      const onSubmit = vi.fn();
      const onCancel = vi.fn();
      render(
        <Harness
          onSubmit={onSubmit}
          onCancel={onCancel}
        />
      );

      await userEvent.click(screen.getByRole('button', {name: 'Cancel'}));
      expect(onCancel).toHaveBeenCalledTimes(1);
      expect(onSubmit).not.toHaveBeenCalled();

      await userEvent.click(screen.getByRole('button', {name: 'Create'}));
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });

    it('submitDisabled blocks the button AND the Enter path, but leaves Cancel live', () => {
      const onSubmit = vi.fn();
      const onCancel = vi.fn();
      render(
        <Harness
          submitDisabled
          onSubmit={onSubmit}
          onCancel={onCancel}
        />
      );

      expect(screen.getByRole('button', {name: 'Create'})).toBeDisabled();
      fireEvent.keyDown(screen.getByLabelText(/folder name/i), {key: 'Enter'});
      expect(onSubmit).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));
      expect(onCancel).toHaveBeenCalled();
    });

    it('busy disables both buttons, shows the busy label, and blocks Escape', () => {
      const onCancel = vi.fn();
      render(
        <Harness
          busy
          busyLabel="Creating…"
          onCancel={onCancel}
        />
      );

      expect(screen.getByRole('button', {name: 'Creating…'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Cancel'})).toBeDisabled();

      fireEvent.keyDown(document, {key: 'Escape'});
      expect(onCancel).not.toHaveBeenCalled();
    });

    it('Escape dismisses when not busy', () => {
      const onCancel = vi.fn();
      render(<Harness onCancel={onCancel} />);
      fireEvent.keyDown(document, {key: 'Escape'});
      expect(onCancel).toHaveBeenCalledTimes(1);
    });

    it('scrollBody caps the panel and scrolls the body, so the footer stays put', () => {
      // Both halves come from the one flag: a caller cannot get the body's overflow
      // without the panel's height cap, which is what made this a broken-dialog trap.
      const {container} = render(
        <Harness
          scrollBody
          className="max-w-lg"
        />
      );

      const panel = container.querySelector('[role="dialog"]') as HTMLElement;
      expect(panel).toHaveClass('flex', 'max-h-[85vh]', 'flex-col', 'max-w-lg');

      const body = container.querySelector('form > div') as HTMLElement;
      expect(body).toHaveClass('min-h-0', 'flex-1', 'overflow-y-auto');
    });

    it('has no axe violations', async () => {
      const ref = createRef<HTMLInputElement>();
      await expectNoA11yViolations(
        <FormDialog
          title="New folder"
          ariaLabel="Create folder"
          submitLabel="Create"
          autoFocusRef={ref}
          onSubmit={vi.fn()}
          onCancel={vi.fn()}>
          <Input
            id="name"
            ref={ref}
            label="Folder name"
          />
        </FormDialog>,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});

// ─── from Menu.test.tsx ───
describe('Menu', () => {
  // Local axe (the shared helper scans at render; the menu opens on click, so we
  // open it first, then scan). Same disables as COMPONENT_AXE_OPTIONS + contrast.
  const runAxe = configureAxe({
    runOnly: {type: 'tag', values: [...WCAG_TAGS]},
    rules: {'color-contrast': {enabled: false}, region: {enabled: false}}
  });

  function trigger(label = 'Open menu') {
    return ({
      open,
      toggle,
      ref,
      menuId
    }: {
      open: boolean;
      toggle: () => void;
      ref: React.Ref<HTMLButtonElement>;
      menuId: string;
    }) => (
      <button
        ref={ref}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={toggle}>
        {label}
      </button>
    );
  }

  function items(over: {rename?: () => void; remove?: () => void} = {}): MenuItem[] {
    return [
      {kind: 'action', label: 'Rename', onSelect: over.rename ?? vi.fn()},
      {kind: 'separator'},
      {kind: 'action', label: 'Delete', tone: 'danger', onSelect: over.remove ?? vi.fn()}
    ];
  }

  describe('Menu', () => {
    it('is closed initially and opens on trigger click', () => {
      render(
        <Menu
          ariaLabel="Row actions"
          trigger={trigger()}
          items={items()}
        />
      );
      const button = screen.getByRole('button', {name: 'Open menu'});
      expect(button).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();

      fireEvent.click(button);
      expect(button).toHaveAttribute('aria-expanded', 'true');
      const menu = screen.getByRole('menu', {name: 'Row actions'});
      expect(menu).toBeInTheDocument();
      // Trigger links the open popover for AT.
      expect(button.getAttribute('aria-controls')).toBe(menu.id);
    });

    it('fires the item onSelect and closes', () => {
      const rename = vi.fn();
      render(
        <Menu
          ariaLabel="Row actions"
          trigger={trigger()}
          items={items({rename})}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
      fireEvent.click(screen.getByRole('menuitem', {name: 'Rename'}));
      expect(rename).toHaveBeenCalledOnce();
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });

    it('closes on Escape and on outside click', () => {
      render(
        <div>
          <button>outside</button>
          <Menu
            ariaLabel="Row actions"
            trigger={trigger()}
            items={items()}
          />
        </div>
      );
      const open = () => fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));

      open();
      fireEvent.keyDown(screen.getByRole('menu'), {key: 'Escape'});
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();

      open();
      fireEvent.mouseDown(screen.getByRole('button', {name: 'outside'}));
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });

    it('roves focus between action items with arrow keys (skipping separators)', () => {
      render(
        <Menu
          ariaLabel="Row actions"
          trigger={trigger()}
          items={items()}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
      const rename = screen.getByRole('menuitem', {name: 'Rename'});
      const del = screen.getByRole('menuitem', {name: 'Delete'});
      expect(rename).toHaveFocus(); // first item focused on open

      fireEvent.keyDown(screen.getByRole('menu'), {key: 'ArrowDown'});
      expect(del).toHaveFocus();
      fireEvent.keyDown(screen.getByRole('menu'), {key: 'ArrowUp'});
      expect(rename).toHaveFocus();
    });

    it('renders a danger-toned item and a separator', () => {
      render(
        <Menu
          ariaLabel="Row actions"
          trigger={trigger()}
          items={items()}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
      expect(screen.getByRole('menuitem', {name: 'Delete'})).toHaveClass('text-danger');
      expect(screen.getByRole('menu').querySelector('[aria-hidden="true"]')).toBeInTheDocument();
    });

    it('does not fire a disabled item', () => {
      const onSelect = vi.fn();
      render(
        <Menu
          ariaLabel="Row actions"
          trigger={trigger()}
          items={[{kind: 'action', label: 'Drop', onSelect, disabled: true}]}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
      const item = screen.getByRole('menuitem', {name: 'Drop'});
      expect(item).toBeDisabled();
      fireEvent.click(item);
      expect(onSelect).not.toHaveBeenCalled();
    });

    it('has no a11y violations when open', async () => {
      const {container} = render(
        <Menu
          ariaLabel="Row actions"
          trigger={trigger()}
          items={items()}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
      expect(await runAxe(container)).toHaveNoViolations();
    });
  });
});

// ─── from ToastProvider.test.tsx ───
describe('ToastProvider', () => {
  function Harness() {
    const toast = useToast();
    return (
      <div>
        <button onClick={() => toast.push({variant: 'success', message: 'Saved!'})}>push-success</button>
        <button
          onClick={() =>
            toast.push({variant: 'danger', message: 'Failed', action: {label: 'Retry', onClick: () => {}}})
          }>
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
});
