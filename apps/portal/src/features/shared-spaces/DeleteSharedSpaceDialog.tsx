import {useEffect, useRef, useState} from 'react';
import {Input} from '../../components/Input';
import {ConfirmDialog} from '../../components/ConfirmDialog';

type Props = {
  space: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

// SPEC-054 FR-002: an owner's IRREVERSIBLE confirm to delete a shared space. The
// cascade tears down everything (all files, all tables, the database, every
// member's access), so — matching the file-delete / drop-table precedent
// (SPEC-018/044) — the destructive button stays disabled until the owner types the
// exact space name. Composes the shared danger ConfirmDialog (alertdialog role +
// "This can't be undone." line) with a type-the-name guard.
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
      irreversible
      busy={busy}
      busyLabel="Deleting…"
      confirmDisabled={!matches}
      onConfirm={attempt}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">
        This permanently deletes <span className="font-mono">{space}</span> for everyone: all of its files, all of its
        tables, the database, and every member&apos;s access.
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
