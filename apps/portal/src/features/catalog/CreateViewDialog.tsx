import {useRef, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {CATALOG_IDENTIFIER_RE, CATALOG_IDENTIFIER_RULE} from '../../lib/catalogIdentifier';

type Props = {
  /** In-flight while the CREATE VIEW runs in the background — locks Create + dismiss. */
  busy?: boolean;
  /** The database the view will be created in — derived from the query body, shown read-only. */
  targetDatabase: string;
  /**
   * The statement the view wraps, shown read-only. The Query workspace passes it because it picks
   * one of several statements by selection or cursor, a choice the user cannot otherwise see before
   * `OR REPLACE` acts on it. An exploration's view wraps the one query on screen, so the Explorer
   * passes none.
   */
  statement?: string;
  onCreate: (name: string) => void;
  onCancel: () => void;
};

/**
 * Name-prompt modal for "Create view". The target database is derived from the
 * query body and shown read-only (not chosen here). The name is validated
 * against the shared catalog-safe identifier rule — Create stays disabled, with
 * an inline error, until it passes.
 */
export function CreateViewDialog({busy = false, targetDatabase, statement, onCreate, onCancel}: Props) {
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
        {statement === undefined ? 'Save the current query' : 'Save this statement'} as a reusable view in{' '}
        <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-text">{targetDatabase}</code>. A view
        already there with the same name is replaced.
      </p>
      {statement !== undefined && (
        // Capped so a long statement cannot push the database and the name field out of view, and a
        // named, focusable region so a keyboard can scroll what the cap hides and a reader hears what it is.
        <pre
          role="region"
          aria-label="Statement to save"
          tabIndex={0}
          className="mb-3 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded border border-border bg-surface-2 px-3 py-2 font-mono text-xs text-text">
          {statement}
        </pre>
      )}
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
