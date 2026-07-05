import {useEffect, useId, useRef, useState} from 'react';
import {Button} from '../../components/Button';
import {Input} from '../../components/Input';
import {Modal} from '../../components/Modal';
import {Banner} from '../../components/Banner';
import {CATALOG_IDENTIFIER_RE} from '../query/query.constants';
import {parseMemberInput} from '../shared-spaces';
import type {ShareRecipient} from './tableShare.types';
import type {ShareTarget} from './useTableShare';

type Props = {
  /** The table being shared (read-only in the dialog). */
  source: ShareTarget;
  /** In-flight while the request is being enqueued — locks the form + dismissal. */
  busy?: boolean;
  /** A send failure to surface inline (the dialog stays open so the user can retry). */
  submitError?: string | null;
  onSubmit: (args: {tableName: string; recipients: ShareRecipient[]}) => void;
  onCancel: () => void;
};

const KIND_LABEL: Record<ShareRecipient['kind'], string> = {user: 'user', space: 'space'};

/**
 * The "Share table" modal (SPEC-093): recipient-kind toggle (users / shared
 * spaces), multi-entry recipient chips (free text — the server owns existence
 * checks; outcomes arrive as notifications), and a catalog-safe result table
 * name defaulted to the source name. Submit stays disabled until there is at
 * least one recipient and the name is valid; the server re-validates
 * authoritatively (SPEC-089), so validation here is UX only.
 */
export function TableShareDialog({source, busy = false, submitError, onSubmit, onCancel}: Props) {
  const [kind, setKind] = useState<ShareRecipient['kind']>('user');
  const [entry, setEntry] = useState('');
  const [recipients, setRecipients] = useState<ShareRecipient[]>([]);
  const [name, setName] = useState(source.table);
  const [nameTouched, setNameTouched] = useState(false);
  const entryRef = useRef<HTMLInputElement>(null);
  const entryHelpId = useId();

  useEffect(() => {
    entryRef.current?.focus();
  }, []);

  const trimmedName = name.trim();
  const nameValid = CATALOG_IDENTIFIER_RE.test(trimmedName);
  const nameError =
    nameTouched && !nameValid && trimmedName.length > 0
      ? 'Use 3–63 characters: lowercase letters, digits, or underscore, starting with a letter.'
      : undefined;

  // Valid catalog-safe names in the entry box (comma/space separated), tagged with
  // the selected kind and deduped against what's already listed.
  const pendingNames = parseMemberInput(entry).filter((n) => !recipients.some((r) => r.kind === kind && r.name === n));

  const addPending = () => {
    if (pendingNames.length === 0) return;
    setRecipients((prev) => [...prev, ...pendingNames.map((n) => ({kind, name: n}))]);
    setEntry('');
    entryRef.current?.focus();
  };

  const remove = (recipient: ShareRecipient) =>
    setRecipients((prev) => prev.filter((r) => !(r.kind === recipient.kind && r.name === recipient.name)));

  const canSubmit = recipients.length > 0 && nameValid && !busy;

  const attempt = () => {
    if (canSubmit) onSubmit({tableName: trimmedName, recipients});
  };

  return (
    <Modal
      ariaLabel={`Share table ${source.table}`}
      onDismiss={onCancel}
      dismissible={!busy}
      className="flex max-h-[85vh] max-w-lg flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-4 pt-5">
        <h2 className="mb-1 text-md font-semibold text-text">Share table</h2>
        <p className="mb-3 text-sm text-text-2">
          Copies the table&rsquo;s data into each recipient&rsquo;s space and creates the table in their database. It
          runs in the background — recipients are notified, and outcomes appear in your notifications.
        </p>

        <div className="mb-4">
          <span className="text-xs font-medium uppercase tracking-wide text-text-2">Table</span>
          <p
            className="mt-0.5 break-all rounded-md border border-border bg-surface-2 px-2.5 py-1.5 font-mono text-sm text-text"
            title={`${source.database}.${source.table}`}>
            {source.database}.{source.table}
          </p>
        </div>

        <fieldset className="mb-3">
          <legend className="mb-1.5 block text-sm font-medium text-text">Share with</legend>
          <div className="flex gap-4">
            {(
              [
                {value: 'user', label: 'Users'},
                {value: 'space', label: 'Shared spaces'}
              ] as const
            ).map((option) => (
              <label
                key={option.value}
                className="flex items-center gap-1.5 text-sm text-text">
                <input
                  type="radio"
                  name="table-share-kind"
                  value={option.value}
                  checked={kind === option.value}
                  disabled={busy}
                  onChange={() => setKind(option.value)}
                  className="h-4 w-4 accent-accent"
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>

        <div className="mb-1 flex items-end gap-2">
          <div className="min-w-0 flex-1">
            <Input
              ref={entryRef}
              id="table-share-recipients"
              label={kind === 'user' ? 'Usernames' : 'Space names'}
              value={entry}
              placeholder={kind === 'user' ? 'e.g. bob, cara' : 'e.g. salesteam'}
              disabled={busy}
              aria-describedby={entryHelpId}
              onChange={(e) => setEntry(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addPending();
                }
              }}
            />
          </div>
          <Button
            variant="default"
            onClick={addPending}
            disabled={busy || pendingNames.length === 0}>
            Add
          </Button>
        </div>
        <p
          id={entryHelpId}
          className="mb-2 text-xs text-text-3">
          One or more names, separated by spaces or commas. Unknown names are reported back as a notification.
        </p>

        {recipients.length > 0 && (
          <ul
            aria-label="Recipients"
            className="mb-2 flex flex-wrap gap-1.5">
            {recipients.map((r) => (
              <li
                key={`${r.kind}:${r.name}`}
                className="flex items-center gap-1 rounded-full border border-border bg-surface-2 py-0.5 pl-2.5 pr-1 text-sm text-text">
                <span className="text-xs uppercase tracking-wide text-text-3">{KIND_LABEL[r.kind]}</span>
                <span className="font-mono">{r.name}</span>
                <button
                  type="button"
                  aria-label={`Remove ${KIND_LABEL[r.kind]} ${r.name}`}
                  disabled={busy}
                  onClick={() => remove(r)}
                  className="grid h-5 w-5 place-items-center rounded-full text-text-3 hover:bg-surface hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-45">
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    className="h-3 w-3"
                    aria-hidden="true">
                    <path d="M6 6l12 12M18 6L6 18" />
                  </svg>
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-4">
          <Input
            id="table-share-name"
            label="Table name for recipients"
            required
            aria-required="true"
            value={name}
            error={nameError}
            disabled={busy}
            onChange={(e) => {
              setNameTouched(true);
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

        {submitError && (
          <Banner
            variant="danger"
            className="mt-4"
            role="alert">
            {submitError}
          </Banner>
        )}
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
          disabled={!canSubmit}>
          {busy ? 'Submitting…' : 'Share'}
        </Button>
      </div>
    </Modal>
  );
}
