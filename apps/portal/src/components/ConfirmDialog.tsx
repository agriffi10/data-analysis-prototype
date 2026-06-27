import {useEffect, useRef, type ReactNode} from 'react';
import {Button} from './Button';
import {Modal} from './Modal';

type ConfirmDialogProps = {
  title: string;
  ariaLabel: string;
  confirmLabel: string;
  cancelLabel?: string;
  // Confirm button style. Default 'primary'.
  confirmVariant?: 'primary' | 'danger';
  // Show the warning-circle icon beside the title (destructive actions).
  tone?: 'danger';
  // Append the standard "This can't be undone." line under the body.
  irreversible?: boolean;
  // In-flight: locks both buttons + dismissal; confirm shows `busyLabel`.
  busy?: boolean;
  busyLabel?: string;
  // Informational single-button mode (no Cancel) — e.g. a limit notice.
  dismissOnly?: boolean;
  // Focus the confirm button on open instead of Cancel (default: Cancel, or
  // confirm when `dismissOnly`).
  focusConfirm?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
};

// SPEC-026 warn-and-confirm dialog (react-best-practices abstraction pass).
// Consolidates ClearQuery / CloseTab / DropTable / TabLimit / delete-confirm /
// overwrite-confirm, which were near-identical. Composes `Modal`. Focus defaults
// to Cancel so a stray Enter never triggers a destructive action.
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
          disabled={busy}>
          {busy && busyLabel ? busyLabel : confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
