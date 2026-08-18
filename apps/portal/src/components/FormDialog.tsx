import {useEffect, useRef, type ReactNode, type RefObject} from 'react';
import {Button} from './Button';
import {Modal} from './Modal';
import {cx} from '../lib/cx';

/** Tab-order-ish: enough to find a dialog's first real control, in DOM order. */
const FOCUSABLE = [
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'button:not([disabled])',
  '[href]',
  '[tabindex]:not([tabindex="-1"])'
].join(', ');

type FormDialogProps = {
  title: string;
  ariaLabel: string;
  submitLabel: string;
  cancelLabel?: string;
  /** Submit button style. Default 'primary'. */
  submitVariant?: 'primary' | 'danger';
  /** In-flight: locks both buttons + dismissal; submit shows `busyLabel`. */
  busy?: boolean;
  busyLabel?: string;
  /**
   * Independently disable the submit button (e.g. an empty or invalid field)
   * while keeping Cancel + dismissal live. `busy` still disables both.
   */
  submitDisabled?: boolean;
  /**
   * Focused on mount. Omit when a DESCENDANT field focuses itself (`UsernameChipsField`'s
   * `autoFocus`) or when the first focusable control is the right target — see the
   * fallback in the body. A focus effect in the CALLER runs after this one, so it wins
   * but only after the fallback has already moved focus once.
   *
   * Three cases where passing a ref beats the fallback: a long dialog, where landing
   * mid-form skips the body a screen reader should hear first; a body whose first
   * control is a radio group, where arrow keys then mutate a choice the user never
   * made; and anything destructive, where `ConfirmDialog`'s "focus Cancel so a stray
   * Enter destroys nothing" reasoning applies.
   */
  autoFocusRef?: RefObject<HTMLInputElement | null>;
  /** Select the focused field's text too — for a pre-filled name the user is likely to replace. */
  autoFocusSelect?: boolean;
  /**
   * The ONE field Enter submits from. Defaults to `autoFocusRef`; pass it explicitly
   * when the dialog's primary field is not the one it focuses. Enter anywhere else in
   * the form does nothing — see the keydown handler for why that is deliberate.
   */
  submitOnEnterRef?: RefObject<HTMLElement | null>;
  /** Panel width/shape classes, passed through to `Modal`. */
  className?: string;
  /**
   * For a long body: caps the panel and scrolls the body inside it, so the footer stays
   * put. Supplies the panel's own flex/height classes as well as the body's, because
   * half of that pair is a broken dialog and nothing would catch it — pass `className`
   * only to change the WIDTH. Off by default: a short dialog scrolls as a whole.
   */
  scrollBody?: boolean;
  onSubmit: () => void;
  onCancel: () => void;
  children: ReactNode;
};

/**
 * Name-a-thing dialog composed on `Modal` — the sibling of `ConfirmDialog`, and
 * deliberately the same prop shape (`title`, `ariaLabel`, `busy`/`busyLabel`,
 * a `*Disabled` escape hatch, `on*` handlers last).
 *
 * Owns the chrome eleven dialogs had each written out: the `px-5 pb-4 pt-5` body,
 * the footer's class string and its Cancel/primary pair, and focus-on-mount.
 * Callers keep their validation rule and their fields, nothing else.
 *
 * ENTER SUBMITS FROM ONE FIELD, not from anywhere in the form. The body is a real
 * `<form>` with a `type="submit"` primary button (so `Button`'s `type="button"` default
 * keeps Cancel from submitting, and Enter on the submit button works natively), but the
 * browser's implicit submission is deliberately suppressed: it fires from EVERY text
 * input in a form, which would hand Enter-to-submit to fields that never had it — a
 * partition-key row mid-edit, a radio the user is still choosing with. Each dialog had
 * exactly one field that submitted on Enter before, and `submitOnEnterRef` (defaulting
 * to `autoFocusRef`) is that field. A child that already handled the key wins over both.
 *
 * @example
 * <FormDialog
 *   title="New folder"
 *   ariaLabel="Create folder"
 *   submitLabel="Create"
 *   autoFocusRef={inputRef}
 *   onSubmit={submit}
 *   onCancel={onCancel}>
 *   <Input ref={inputRef} label="Folder name" … />
 * </FormDialog>
 */
export function FormDialog({
  title,
  ariaLabel,
  submitLabel,
  cancelLabel = 'Cancel',
  submitVariant = 'primary',
  busy = false,
  busyLabel,
  submitDisabled = false,
  autoFocusRef,
  autoFocusSelect = false,
  submitOnEnterRef,
  className,
  scrollBody = false,
  onSubmit,
  onCancel,
  children
}: FormDialogProps) {
  const formRef = useRef<HTMLFormElement>(null);

  const submit = () => {
    if (!busy && !submitDisabled) onSubmit();
  };

  // A MODAL DRAWS FOCUS, and that is enforced here rather than left to each caller to
  // remember. Three ways it can already be handled, in order: an explicit `autoFocusRef`;
  // a child that focuses itself (child effects run before this one, so it has already
  // won by the time we look); otherwise the first focusable control — the body precedes
  // the footer, so that is a field where there is one and Cancel where there isn't.
  // `Modal` passes `initialFocus: false` and only falls back to the panel, so without
  // this a dialog that asks for nothing opens a Tab away from its own first control.
  useEffect(() => {
    if (autoFocusRef) {
      autoFocusRef.current?.focus();
      if (autoFocusSelect) autoFocusRef.current?.select();
      return;
    }
    const form = formRef.current;
    if (!form || form.contains(document.activeElement)) return;
    form.querySelector<HTMLElement>(FOCUSABLE)?.focus();
  }, [autoFocusRef, autoFocusSelect]);

  return (
    <Modal
      ariaLabel={ariaLabel}
      dismissible={!busy}
      // THE WIDTH IS SUPPLIED HERE, not left to `Modal`'s default. Fixing
      // only `Modal`'s empty-string fallback closed half the trap: with `scrollBody` and no
      // `className` this `cx` returns a TRUTHY string, `Modal`'s `className || 'max-w-md'`
      // never fires, and the panel takes `w-full` — the identical failure one branch over, and
      // exactly the call shape this component's own doc comment advertises. Every current
      // `scrollBody` caller happens to pass a width, so nothing was broken; that is luck, and
      // the next one to omit it would have fallen in.
      className={cx(scrollBody && 'flex max-h-[85vh] flex-col', className || 'max-w-md')}
      onDismiss={onCancel}>
      <form
        ref={formRef}
        noValidate
        className={scrollBody ? 'flex min-h-0 flex-1 flex-col' : undefined}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        onKeyDown={(e) => {
          if (e.key !== 'Enter' || e.defaultPrevented) return;
          // An IME is confirming a candidate, not submitting a form. Enter during
          // composition is how every Japanese/Chinese name gets typed, and without this
          // the dialog would submit the pre-conversion text.
          if (e.nativeEvent.isComposing) return;
          // Inputs and SELECTS are intercepted: a `textarea` keeps its newline, Enter on
          // a button stays a click on that button (including the submit button, which
          // then submits natively), and a combobox that already `preventDefault`ed
          // keeps its selection via the bail above.
          //
          // A `<select>` belongs here for exactly the reason an input does, and it is
          // easy to miss because jsdom implements no implicit submission at all — a test
          // asserting "Enter on the select does not submit" passes in this environment
          // whatever this handler does. Browsers submit the form when Enter is pressed on
          // a closed select, which would file a save from the destination control
          // (SPEC-175 FR-004 AC8). An OPEN dropdown is the browser's own modal and its
          // Enter never reaches here.
          if (!(e.target instanceof HTMLInputElement) && !(e.target instanceof HTMLSelectElement)) return;
          // Suppress the browser's implicit submission for EVERY such control, then submit
          // only from the designated field. Without the blanket `preventDefault`, a
          // partition-key row or a radio would submit the dialog natively.
          e.preventDefault();
          if (e.target === (submitOnEnterRef ?? autoFocusRef)?.current) submit();
        }}>
        <div className={cx(scrollBody && 'min-h-0 flex-1 overflow-y-auto', 'px-5 pb-4 pt-5')}>
          <h2 className="text-md font-semibold text-text">{title}</h2>
          {children}
        </div>

        <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
          <Button
            variant="ghost"
            onClick={onCancel}
            disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            type="submit"
            variant={submitVariant}
            disabled={busy || submitDisabled}>
            {busy && busyLabel ? busyLabel : submitLabel}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
