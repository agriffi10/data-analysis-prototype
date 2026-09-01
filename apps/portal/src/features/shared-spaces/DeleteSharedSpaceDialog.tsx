import {useEffect, useRef, useState} from 'react';
import {Input} from '../../components/Input';
import {ConfirmDialog} from '../../components/ConfirmDialog';

type Props = {
  space: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * Owner's confirm to delete a shared space. Deleting removes every member's access,
 * the owner's included, and the space disappears from everyone's list — but the files
 * and tables are retained by administrators rather than destroyed, so this dialog does
 * NOT carry ConfirmDialog's `irreversible` line. That line is still true of the dialogs
 * that share the component, which is why the wording changed here rather than there.
 *
 * What is irreversible is the name: it can never be used for a new space. The button
 * stays disabled until the owner types the exact name, which is unchanged.
 */
export function DeleteSharedSpaceDialog({space, busy = false, onConfirm, onCancel}: Props) {
  const [confirmText, setConfirmText] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const matches = confirmText.trim() === space;
  const attempt = () => {
    if (matches && !busy) onConfirm();
  };

  return (
    <ConfirmDialog
      title="Delete shared space"
      ariaLabel={`Delete ${space}`}
      tone="danger"
      confirmVariant="danger"
      confirmLabel="Delete"
      busy={busy}
      busyLabel="Deleting…"
      confirmDisabled={!matches}
      onConfirm={attempt}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">
        This removes <span className="font-mono">{space}</span> for everyone: every member loses access, including you,
        and it disappears from everyone&apos;s list. Its files and tables are kept by administrators rather than
        destroyed. The name can never be used again.
      </p>
      <div className="mt-3">
        <Input
          ref={inputRef}
          id="delete-shared-space-confirm"
          label={`Type “${space}” to confirm`}
          value={confirmText}
          autoComplete="off"
          disabled={busy}
          onChange={(e) => setConfirmText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              attempt();
            }
          }}
        />
      </div>
    </ConfirmDialog>
  );
}
