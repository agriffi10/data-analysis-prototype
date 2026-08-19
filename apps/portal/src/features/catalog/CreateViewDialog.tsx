import {useRef, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {CATALOG_IDENTIFIER_RE, CATALOG_IDENTIFIER_RULE} from '../../lib/catalogIdentifier';

type Props = {
  /** In-flight while the CREATE VIEW runs in the background — locks Create + dismiss. */
  busy?: boolean;
  /** The database the view will be created in — derived from the query body, shown read-only. */
  targetDatabase: string;
  onCreate: (name: string) => void;
  onCancel: () => void;
};

/**
 * Name-prompt modal for "Create view". The target database is derived from the
 * query body and shown read-only (not chosen here). The name is validated
 * against the shared catalog-safe identifier rule — Create stays disabled, with
 * an inline error, until it passes.
 */
export function CreateViewDialog({busy = false, targetDatabase, onCreate, onCancel}: Props) {
  const [name, setName] = useState('');
  const [touched, setTouched] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const trimmed = name.trim();
  const valid = CATALOG_IDENTIFIER_RE.test(trimmed);
  // Surface why Create is unavailable in text (WCAG 3.3.1), not just via disabling.
  const error = touched && !valid && trimmed.length > 0 ? CATALOG_IDENTIFIER_RULE : undefined;

  const attempt = () => {
    if (valid && !busy) onCreate(trimmed);
  };

  return (
    <FormDialog
      title="Create view"
      ariaLabel="Create view"
      submitLabel="Create"
      busy={busy}
      busyLabel="Creating…"
      submitDisabled={!valid}
      autoFocusRef={inputRef}
      onSubmit={attempt}
      onCancel={onCancel}>
      {/* `mt-3` reproduces the gap the old markup got from an `mb-3` on the heading. */}
      <p className="mb-3 mt-3 text-sm text-text-2">
        Save the current query as a reusable view in{' '}
        <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-text">{targetDatabase}</code>.
      </p>
      <Input
        ref={inputRef}
        id="create-view-name"
        label="View name"
        required
        aria-required="true"
        value={name}
        placeholder="e.g. monthly_revenue"
        error={error}
        disabled={busy}
        onChange={(e) => {
          setTouched(true);
          setName(e.target.value);
        }}
      />
    </FormDialog>
  );
}
