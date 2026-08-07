import {useEffect, useId, useMemo, useRef, useState} from 'react';
import {Button} from '../../components/Button';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {UsernameCombobox} from '../../components/UsernameCombobox';
import type {UsernameComboboxHandle} from '../../components/UsernameCombobox';
import {Banner} from '../../components/Banner';
import {CATALOG_IDENTIFIER_RE, CATALOG_IDENTIFIER_RULE} from '../../lib/catalogIdentifier';
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
  const spaceEntryRef = useRef<HTMLInputElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const userEntryRef = useRef<UsernameComboboxHandle>(null);
  const entryHelpId = useId();

  useEffect(() => {
    // The dialog opens on the user kind, so the combobox is what should have focus.
    userEntryRef.current?.focus();
  }, []);

  const trimmedName = name.trim();
  const nameValid = CATALOG_IDENTIFIER_RE.test(trimmedName);
  const nameError = nameTouched && !nameValid && trimmedName.length > 0 ? CATALOG_IDENTIFIER_RULE : undefined;

  // Valid catalog-safe names in the entry box (comma/space separated), tagged with the selected
  // kind and deduped against what's already listed. Still `parseMemberInput` — the SPACE kind
  // keeps the original silent-drop parser, because space names are not in the user directory and
  // this dialog's space path is deliberately unchanged (SPEC-148 FR-002).
  const pendingNames = parseMemberInput(entry).filter((n) => !recipients.some((r) => r.kind === kind && r.name === n));

  /** Add committed names under the CURRENT kind, preserving the existing per-kind dedupe. */
  const addNames = (names: string[], forKind: ShareRecipient['kind'] = kind) => {
    const fresh = names.filter((n) => !recipients.some((r) => r.kind === forKind && r.name === n));
    if (fresh.length === 0) return;
    setRecipients((prev) => [...prev, ...fresh.map((n) => ({kind: forKind, name: n}))]);
  };

  const addPending = () => {
    // For the user kind the Add button drives the combobox's OWN commit, so the button and Enter
    // take one path — otherwise the two would drift, and only one of them would surface the
    // invalid tokens FR-003 requires to be shown.
    if (kind === 'user') {
      userEntryRef.current?.commit();
      // Focus goes back to the field, as it always has after an add — otherwise the second name
      // costs a click, and only the space kind would return focus.
      userEntryRef.current?.focus();
      return;
    }
    if (pendingNames.length === 0) return;
    addNames(pendingNames, 'space');
    setEntry('');
    spaceEntryRef.current?.focus();
  };

  /** Names already listed under `user` — hidden from suggestions, never refused. */
  const listedUsers = useMemo(
    () => new Set(recipients.filter((r) => r.kind === 'user').map((r) => r.name)),
    [recipients]
  );

  const remove = (recipient: ShareRecipient) =>
    setRecipients((prev) => prev.filter((r) => !(r.kind === recipient.kind && r.name === recipient.name)));

  const canSubmit = recipients.length > 0 && nameValid && !busy;

  const attempt = () => {
    if (canSubmit) onSubmit({tableName: trimmedName, recipients});
  };

  return (
    // No `autoFocusRef`: the combobox this dialog wants focused is not an `<input>` ref.
    // Focus therefore lands TWICE on open — `FormDialog`'s fallback runs first (parent
    // effects flush after child ones, and the effect above is in THIS component, the
    // parent of `FormDialog`) and takes the first focusable control, the "Share with"
    // radio; the effect above then moves it to the combobox. The end state is right and
    // the intermediate one is never painted, but do not read this as the fallback
    // standing aside — it does that only for a genuine descendant, as in
    // `AddMembersDialog`. Untangling it means changing where this dialog focuses, which
    // is not this spec's business.
    <FormDialog
      title="Share table"
      ariaLabel={`Share table ${source.table}`}
      submitLabel="Share"
      busy={busy}
      busyLabel="Submitting…"
      submitDisabled={!canSubmit}
      submitOnEnterRef={nameRef}
      className="max-w-lg"
      scrollBody
      onSubmit={attempt}
      onCancel={onCancel}>
      {/* `mt-1` reproduces the gap the old markup got from an `mb-1` on the heading. */}
      <p className="mb-3 mt-1 text-sm text-text-2">
        Copies the table&rsquo;s data into each recipient&rsquo;s space and creates the table in their database. It runs
        in the background — recipients are notified, and outcomes appear in your notifications.
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
          {kind === 'user' ? (
            // The USER kind gets suggestions. It stays a BULK field — `onCommitMany` is what
            // keeps `bob, cara` producing two chips, which it has done since SPEC-093.
            //
            // The current user is deliberately NOT excluded: sharing a table into your own
            // database is something the pipeline allows, and the field must not invent a
            // restriction the control plane does not have.
            <UsernameCombobox
              ref={userEntryRef}
              id="table-share-recipients"
              label="Usernames"
              value={entry}
              placeholder="e.g. bob, cara"
              disabled={busy}
              describedBy={entryHelpId}
              suppress={listedUsers}
              onChange={setEntry}
              onCommit={(username) => addNames([username], 'user')}
              onCommitMany={(usernames) => addNames(usernames, 'user')}
            />
          ) : (
            // The SPACE kind is unchanged: space names are not in the user directory, so there
            // is nothing to suggest and offering usernames here would be actively wrong.
            <Input
              ref={spaceEntryRef}
              id="table-share-recipients"
              label="Space names"
              value={entry}
              placeholder="e.g. salesteam"
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
          )}
        </div>
        {/* KEPT for both kinds. Enter-to-commit is ADDED, not substituted: the button is the
              discoverable affordance, and removing it would be a silent UX regression in a
              dialog this spec is only meant to be improving. For the user kind it stays enabled
              whenever there is text, because the combobox owns the parse. */}
        <Button
          variant="default"
          onClick={addPending}
          disabled={busy || (kind === 'user' ? entry.trim() === '' : pendingNames.length === 0)}>
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
          ref={nameRef}
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
    </FormDialog>
  );
}
