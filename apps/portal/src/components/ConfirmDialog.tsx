import {useEffect, useRef, type ReactNode} from 'react';
import {Button} from './Button';
import {Modal} from './Modal';

type ConfirmDialogProps = {
  title: string;
  ariaLabel: string;
  confirmLabel: string;
  cancelLabel?: string;
  /** Confirm button style. Default 'primary'. */
  confirmVariant?: 'primary' | 'danger';
  /** Show the warning-circle icon beside the title (destructive actions). */
  tone?: 'danger';
  /** Append the standard "This can't be undone." line under the body. */
  irreversible?: boolean;
  /** In-flight: locks both buttons + dismissal; confirm shows `busyLabel`. */
  busy?: boolean;
  busyLabel?: string;
  /**
   * Independently disable the confirm button (e.g. a type-the-name guard) while
   * keeping Cancel + dismissal live. `busy` still disables both.
   */
  confirmDisabled?: boolean;
  /**
   * WHY confirm is unavailable (SPEC-186 FR-002, on SPEC-172's `Button.disabledReason`).
   * Supplied alongside `confirmDisabled`, it swaps the native `disabled` for `aria-disabled`
   * so the reason keeps its place in the tab order — a `disabled` button with no title is
   * "greyed out and I can't find out why". `busy` still wins and stays natively disabled:
   * an operation in flight is not a refusal.
   */
  confirmDisabledReason?: string;
  /** Informational single-button mode (no Cancel) — e.g. a limit notice. */
  dismissOnly?: boolean;
  /**
   * Focus the confirm button on open instead of Cancel (default: Cancel, or
   * confirm when `dismissOnly`).
   */
  focusConfirm?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
};

/**
 * Warn-and-confirm dialog composed on `Modal` (`role="alertdialog"`). Renders a
 * title, optional body, and Cancel/confirm buttons. Initial focus defaults to
 * Cancel so a stray Enter never triggers a destructive action.
 *
 * @example
 * <ConfirmDialog
 *   title="Delete report.csv?"
 *   ariaLabel="Confirm delete"
 *   confirmLabel="Delete"
 *   confirmVariant="danger"
 *   tone="danger"
 *   irreversible
 *   busy={deleting}
 *   busyLabel="Deleting…"
 *   onConfirm={handleDelete}
 *   onCancel={() => setConfirming(false)}>
 *   <p>The file will be removed from your space.</p>
 * </ConfirmDialog>
 */
export function ConfirmDialog({
  title,
  ariaLabel,
  confirmLabel,
  cancelLabel = 'Cancel',
  confirmVariant = 'primary',
  tone,
  irreversible,
  busy = false,
  busyLabel,
  confirmDisabled = false,
  confirmDisabledReason,
  dismissOnly = false,
  focusConfirm,
  onConfirm,
  onCancel,
  children
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  const focusTheConfirm = focusConfirm ?? dismissOnly;
  useEffect(() => {
    if (focusTheConfirm) confirmRef.current?.focus();
    else cancelRef.current?.focus();
  }, [focusTheConfirm]);

  return (
    <Modal
      role="alertdialog"
      ariaLabel={ariaLabel}
      dismissible={!busy}
      onDismiss={onCancel}>
      <div className="px-5 pb-4 pt-5">
        {tone === 'danger' ? (
          <div className="flex items-start gap-3">
            <span className="shrink-0 rounded-full bg-danger-soft p-1 text-danger">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-6 w-6"
                aria-hidden="true">
                <circle
                  cx="12"
                  cy="12"
                  r="9"
                />
                <path
                  strokeLinecap="round"
                  d="M12 8v5M12 16h.01"
                />
              </svg>
            </span>
            <h2 className="text-md font-semibold text-text">{title}</h2>
          </div>
        ) : (
          <h2 className="text-md font-semibold text-text">{title}</h2>
        )}

        {children}

        {irreversible && <p className="mt-2 text-sm font-medium text-danger">This can’t be undone.</p>}
      </div>

      <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
        {!dismissOnly && (
          <Button
            ref={cancelRef}
            variant="ghost"
            onClick={onCancel}
            disabled={busy}>
            {cancelLabel}
          </Button>
        )}
        <Button
          ref={confirmRef}
          variant={confirmVariant}
          onClick={onConfirm}
          // A reason turns the refusal into an `aria-disabled` one; without it the control is
          // natively disabled as before. `busy` is never a refusal, so it keeps `disabled`.
          disabled={busy || (confirmDisabled && !confirmDisabledReason)}
          disabledReason={!busy && confirmDisabled ? confirmDisabledReason : undefined}>
          {busy && busyLabel ? busyLabel : confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
