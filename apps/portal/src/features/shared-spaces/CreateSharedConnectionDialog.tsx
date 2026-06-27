import {useEffect, useRef, useState} from 'react';
import {Button} from '../../components/Button';
import {Input} from '../../components/Input';
import {Modal} from '../../components/Modal';
import {CATALOG_IDENTIFIER_RE} from '../query/query.constants';

type Props = {
  // In-flight while the create request is being enqueued — locks Create + dismiss.
  busy?: boolean;
  onCreate: (name: string) => void;
  onCancel: () => void;
};

// SPEC-051 FR-001: name-prompt modal for a new shared connection. The name is
// validated against the shared catalog-safe identifier rule (SPEC-033) — it becomes
// the S3 prefix AND the Glue database, exactly like a username — so Create stays
// disabled (with an inline error) until it passes. The copy states the name is
// permanent (no rename) and globally unique, so a later collision reads as expected
// UX, not a surprise. Composes the shared Modal/Input/Button primitives.
export function CreateSharedConnectionDialog({busy = false, onCreate, onCancel}: Props) {
  const [name, setName] = useState('');
  const [touched, setTouched] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const trimmed = name.trim();
  const valid = CATALOG_IDENTIFIER_RE.test(trimmed);
  const error =
    touched && !valid && trimmed.length > 0
      ? 'Use 3–63 characters: lowercase letters, digits, or underscore, starting with a letter.'
      : undefined;

  const attempt = () => {
    if (valid && !busy) onCreate(trimmed);
  };

  return (
    <Modal
      ariaLabel="Create shared connection"
      onDismiss={onCancel}
      dismissible={!busy}>
      <div className="px-5 pb-4 pt-5">
        <h2 className="mb-3 text-md font-semibold text-text">New shared connection</h2>
        <p className="mb-3 text-sm text-text-2">
          You&apos;ll be the owner and can add members. The name is{' '}
          <strong className="font-semibold text-text">permanent</strong> (it can&apos;t be renamed) and must be{' '}
          <strong className="font-semibold text-text">globally unique</strong> across all spaces.
        </p>
        <Input
          ref={inputRef}
          id="shared-connection-name"
          label="Connection name"
          required
          aria-required="true"
          value={name}
          placeholder="e.g. sales_data"
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
