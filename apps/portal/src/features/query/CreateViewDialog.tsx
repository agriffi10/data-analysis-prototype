import {useEffect, useRef, useState} from 'react';
import {Button} from '../../components/Button';
import {Input} from '../../components/Input';
import {Modal} from '../../components/Modal';
import {CATALOG_IDENTIFIER_RE} from './query.constants';

type Props = {
  /** In-flight while the CREATE VIEW runs in the background — locks Create + dismiss. */
  busy?: boolean;
  /** The database the view will be created in — derived from the query body (SPEC-077 FR-008), shown read-only. */
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

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const trimmed = name.trim();
  const valid = CATALOG_IDENTIFIER_RE.test(trimmed);
  // Surface why Create is unavailable in text (WCAG 3.3.1), not just via disabling.
  const error =
    touched && !valid && trimmed.length > 0
      ? 'Use 3–63 characters: lowercase letters, digits, or underscore, starting with a letter.'
      : undefined;

  const attempt = () => {
    if (valid && !busy) onCreate(trimmed);
  };

  return (
    <Modal
      ariaLabel="Create view"
      onDismiss={onCancel}
      dismissible={!busy}>
      <div className="px-5 pb-4 pt-5">
        <h2 className="mb-3 text-md font-semibold text-text">Create view</h2>
        <p className="mb-3 text-sm text-text-2">
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
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              attempt();
            }
          }}
        />
      </div>
      <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
        <Button
          variant="ghost"
          onClick={onCancel}
          disabled={busy}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={attempt}
          disabled={!valid || busy}>
          {busy ? 'Creating…' : 'Create'}
        </Button>
      </div>
    </Modal>
  );
}
