import {useEffect, useId, useMemo, useRef, useState} from 'react';
import {Button} from '../../components/Button';
import {Chip, ChipList} from '../../components/Chip';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {UsernameCombobox} from '../user-directory/UsernameCombobox';
import type {UsernameComboboxHandle} from '../user-directory/UsernameCombobox';
import {useUsernameSuggestions} from '../user-directory/useUsernameSuggestions';
import {Banner} from '../../components/Banner';
import {CATALOG_IDENTIFIER_RE, CATALOG_IDENTIFIER_RULE} from '../../lib/catalogIdentifier';
import {useSpaceSuggestions} from '../shared-spaces/useSpaceSuggestions';
import {useFeature} from '../feature-flags';
import type {ShareRecipient} from './tableShare.types';
import type {ShareTarget} from './useTableShare';
import {FIELD_LABEL, SECTION_CAPTION} from '../../components/fieldStyles';

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
 * The note shown after committing a space name the user's own space list does not hold.
 *
 * It must NOT read as a rejection: any active space is a valid recipient whether or not the
 * sender belongs to it (`test_recipient_space_membership_not_required`), and the suggestions
 * cover only the sender's own spaces. This note is the one place a user could be misled into
 * thinking the name was wrong.
 *
 * @param names - The committed names absent from the suggestions; never empty.
 *
 * @returns The sentence to show.
 */
function unlistedSpaceNote(names: string[]): string {
  return `${names.join(', ')} ${names.length === 1 ? 'is' : 'are'} not one of your shared spaces — you can still share to a space you are not a member of, and the name will be checked when the request is sent.`;
}

/**
 * The "Share table" modal: recipient-kind toggle (users / shared
 * spaces), multi-entry recipient chips, and a catalog-safe result table name
 * defaulted to the source name. Submit stays disabled until there is at least
 * one recipient and the name is valid; the server re-validates authoritatively
 *, so validation here is UX only.
 *
 * BOTH kinds suggest as you type — usernames from the published directory
 *, space names from the signed-in user's own connections cache
 * — and NEITHER blocks a name it does not know. Free text still
 * commits: the pipeline owns existence checks, and outcomes arrive as
 * notifications.
 */
export function TableShareDialog({source, busy = false, submitError, onSubmit, onCancel}: Props) {
  // With shared workspaces off there is one recipient kind and no toggle.
  // `kind` stays state rather than becoming a constant so the space branch is exercised by
  // the same code path when the flag is on — and it can never LEAVE 'user' while off, because
  // the only thing that sets it is the control that no longer renders.
  const sharedSpacesEnabled = useFeature('sharedWorkspaces');
  const [kind, setKind] = useState<ShareRecipient['kind']>('user');
  const [entry, setEntry] = useState('');
  const [recipients, setRecipients] = useState<ShareRecipient[]>([]);
  const [name, setName] = useState(source.table);
  const [nameTouched, setNameTouched] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const entryRef = useRef<UsernameComboboxHandle>(null);
  const entryHelpId = useId();
  const userSuggestions = useUsernameSuggestions();
  const spaceSuggestions = useSpaceSuggestions();

  useEffect(() => {
    // The dialog opens on the user kind, so the combobox is what should have focus.
    entryRef.current?.focus();
  }, []);

  const trimmedName = name.trim();
  const nameValid = CATALOG_IDENTIFIER_RE.test(trimmedName);
  const nameError = nameTouched && !nameValid && trimmedName.length > 0 ? CATALOG_IDENTIFIER_RULE : undefined;

  /** Add committed names under the CURRENT kind, preserving the existing per-kind dedupe. */
  const addNames = (names: string[], forKind: ShareRecipient['kind'] = kind) => {
    const fresh = names.filter((n) => !recipients.some((r) => r.kind === forKind && r.name === n));
    if (fresh.length === 0) return;
    setRecipients((prev) => [...prev, ...fresh.map((n) => ({kind: forKind, name: n}))]);
  };

  const addPending = () => {
    // The Add button drives the combobox's OWN commit, so the button and Enter take one path —
    // otherwise the two would drift, and only one of them would surface the invalid tokens
    // SPEC-148 FR-003 requires to be shown. Since SPEC-158 that holds for BOTH kinds: the space
    // entry is the same combobox, so the pre-parse that used to gate this button for spaces
    // would now be a second, quieter parser beside the one that actually commits.
    entryRef.current?.commit();
    // Focus goes back to the field, as it always has after an add — otherwise the second name
    // costs a click.
    entryRef.current?.focus();
  };

  /** Names already listed under the CURRENT kind — hidden from suggestions, never refused. */
  const listed = useMemo(
    () => new Set(recipients.filter((r) => r.kind === kind).map((r) => r.name)),
    [kind, recipients]
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
        <span className={SECTION_CAPTION}>Table</span>
        <p
          className="mt-0.5 break-all rounded-md border border-border bg-surface-2 px-2.5 py-1.5 font-mono text-sm text-text"
          title={`${source.database}.${source.table}`}>
          {source.database}.{source.table}
        </p>
      </div>

      {/* with `sharedWorkspaces` off there is exactly ONE recipient kind, so
          the toggle does not render at all. A single-option radio group is a control that
          asks a question with one answer — worse than no control, because it implies the
          other option exists somewhere. The field below then labels itself for usernames,
          which `kind` already does, because `kind` is pinned to 'user' at that point. */}
      {sharedSpacesEnabled && (
        <fieldset className="mb-3">
          <legend className={FIELD_LABEL}>Share with</legend>
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
      )}

      <div className="mb-1 flex items-end gap-2">
        <div className="min-w-0 flex-1">
          {/* ONE field for both kinds since SPEC-158, differing only in what it suggests and
              what it calls things. It stays a BULK field — `onCommitMany` is what keeps
              `bob, cara` producing two chips, which it has done since SPEC-093.

              The current user is deliberately NOT excluded from the user kind: sharing a table
              into your own database is something the pipeline allows, and the field must not
              invent a restriction the control plane does not have. The space kind's suggestions
              are the user's OWN spaces, and any active space is a valid recipient — hence the
              softer unlisted-name wording.

              `key={kind}` REMOUNTS on a toggle, so a note or error raised under one kind cannot
              linger over the other. The two branches used to be different components, which gave
              this for free. */}
          <UsernameCombobox
            {...(kind === 'space' ? spaceSuggestions : userSuggestions)}
            key={kind}
            ref={entryRef}
            id="table-share-recipients"
            label={kind === 'space' ? 'Space names' : 'Usernames'}
            value={entry}
            placeholder={kind === 'space' ? 'e.g. salesteam' : 'e.g. bob, cara'}
            disabled={busy}
            describedBy={entryHelpId}
            suppress={listed}
            {...(kind === 'space' ? {unlistedNote: unlistedSpaceNote} : {})}
            onChange={setEntry}
            onCommit={(committed) => addNames([committed], kind)}
            onCommitMany={(committed) => addNames(committed, kind)}
          />
        </div>
        {/* KEPT for both kinds. Enter-to-commit is ADDED, not substituted: the button is the
              discoverable affordance, and removing it would be a silent UX regression. It stays
              enabled whenever there is text, because the combobox owns the parse and clicking it
              on a malformed entry EXPLAINS the problem rather than sitting dead. */}
        <Button
          variant="default"
          onClick={addPending}
          disabled={busy || entry.trim() === ''}>
          Add
        </Button>
      </div>
      <p
        id={entryHelpId}
        className="mb-2 text-xs text-text-3">
        One or more names, separated by spaces or commas. Unknown names are reported back as a notification.
      </p>

      {recipients.length > 0 && (
        <ChipList
          ariaLabel="Recipients"
          className="mb-2">
          {recipients.map((r) => (
            <Chip
              key={`${r.kind}:${r.name}`}
              name={r.name}
              tag={KIND_LABEL[r.kind]}
              removeLabel={`Remove ${KIND_LABEL[r.kind]} ${r.name}`}
              disabled={busy}
              onRemove={() => remove(r)}
            />
          ))}
        </ChipList>
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
