import {createRef, useEffect, useRef} from 'react';
import {render, screen, fireEvent} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, it, expect, vi} from 'vitest';
import {FormDialog} from './FormDialog';
import {Input} from './Input';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../test/axe';

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
