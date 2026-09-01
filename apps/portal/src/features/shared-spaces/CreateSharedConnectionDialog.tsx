import {useRef, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {CATALOG_IDENTIFIER_RE, CATALOG_IDENTIFIER_RULE} from '../../lib/catalogIdentifier';

type Props = {
  /** In-flight while the create request is being enqueued — locks Create + dismiss. */
  busy?: boolean;
  onCreate: (name: string) => void;
  onCancel: () => void;
};

/**
 * Name-prompt modal for a new shared connection. The name becomes the S3 prefix AND
 * the Glue database, so it's validated against the catalog-safe identifier rule and
 * Create stays disabled (with an inline error) until it passes. The copy states the
 * name is permanent and globally unique so a later collision reads as expected UX. It also
 * says the name is never reusable, because a deleted space keeps its record forever and the
 * refusal would otherwise first be met at the moment of creating, with no warning.
 */
export function CreateSharedConnectionDialog({busy = false, onCreate, onCancel}: Props) {
  const [name, setName] = useState('');
  const [touched, setTouched] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const trimmed = name.trim();
  const valid = CATALOG_IDENTIFIER_RE.test(trimmed);
  const error = touched && !valid && trimmed.length > 0 ? CATALOG_IDENTIFIER_RULE : undefined;

  const attempt = () => {
    if (valid && !busy) onCreate(trimmed);
  };

  return (
    <FormDialog
      title="New shared connection"
      ariaLabel="Create shared connection"
      submitLabel="Create"
      busy={busy}
      busyLabel="Creating…"
      submitDisabled={!valid}
      autoFocusRef={inputRef}
      onSubmit={attempt}
      onCancel={onCancel}>
      {/* `mt-3` reproduces the gap the old markup got from an `mb-3` on the heading. */}
      <p className="mb-3 mt-3 text-sm text-text-2">
        You&apos;ll be the owner and can add members. The name is{' '}
        <strong className="font-semibold text-text">permanent</strong> — it can&apos;t be renamed, and it can&apos;t be
        reused later even if the space is deleted — and must be{' '}
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
      />
    </FormDialog>
  );
}
