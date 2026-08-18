import {useEffect, useId, useMemo, useRef, useState} from 'react';
import {Banner} from '../../components/Banner';
import {Button} from '../../components/Button';
import {Chip, ChipList} from '../../components/Chip';
import {FormDialog} from '../../components/FormDialog';
import {useFeature} from '../feature-flags';
import {useSpaceSuggestions} from '../shared-spaces/useSpaceSuggestions';
import {UsernameCombobox} from '../user-directory/UsernameCombobox';
import type {UsernameComboboxHandle} from '../user-directory/UsernameCombobox';
import {useUsernameSuggestions} from '../user-directory/useUsernameSuggestions';
import type {SendItem, SendRecipient} from './fileSend.types';
import {FIELD_LABEL, SECTION_CAPTION} from '../../components/fieldStyles';

type Props = {
  /** What the selection holds — read-only in the dialog. */
  items: SendItem[];
  /** In-flight while the request is being enqueued — locks the form and dismissal. */
  busy?: boolean;
  /** An enqueue failure to surface inline (the dialog stays open so the user can retry). */
  submitError?: string | null;
  onSubmit: (recipients: SendRecipient[]) => void;
  onCancel: () => void;
};

const KIND_LABEL: Record<SendRecipient['kind'], string> = {user: 'user', space: 'space'};

/** The name an item arrives under in the recipient's inbox — its last path segment. */
function itemName(item: SendItem): string {
  return item.key.replace(/\/$/, '').split('/').pop() ?? item.key;
}

/**
 * The note shown after committing a space name the user's own space list does not hold.
 *
 * It must NOT read as a rejection: any active space is a valid target whether or not the sender
 * belongs to it, and the suggestions cover only the sender's own spaces. That rule was established
 * this wording for the share dialog and it is the same claim here.
 *
 * @param names - The committed names absent from the suggestions; never empty.
 * @returns The sentence to show.
 */
function unlistedSpaceNote(names: string[]): string {
  return `${names.join(', ')} ${names.length === 1 ? 'is' : 'are'} not one of your shared spaces — you can still send to a space you are not a member of, and the name will be checked when the request is sent.`;
}

/**
 * The "Send to…" modal: a read-only summary of the selection, a Users / Shared spaces
 * toggle driving ONE combobox, and a combined removable chip list.
 *
 * It is `TableShareDialog` with the table name taken out, deliberately: both kinds suggest as you
 * type — usernames from the published directory, space names from the sender's own connections
 * cache — and NEITHER blocks a name it does not know. The control plane owns existence, and every
 * outcome comes back as a notification.
 */
export function SendFilesDialog({items, busy = false, submitError, onSubmit, onCancel}: Props) {
  // With shared workspaces off there is one recipient kind and no toggle, and
  // `kind` can never leave 'user' because the only thing that sets it no longer renders.
  const sharedSpacesEnabled = useFeature('sharedWorkspaces');
  const [kind, setKind] = useState<SendRecipient['kind']>('user');
  const [entry, setEntry] = useState('');
  const [recipients, setRecipients] = useState<SendRecipient[]>([]);
  const [attempted, setAttempted] = useState(false);
  const entryRef = useRef<UsernameComboboxHandle>(null);
  const entryHelpId = useId();
  const userSuggestions = useUsernameSuggestions();
  const spaceSuggestions = useSpaceSuggestions();

  useEffect(() => {
    // The dialog opens on the user kind, so the combobox is what should have focus.
    entryRef.current?.focus();
  }, []);

  const names = useMemo(() => items.map(itemName), [items]);

  /** Add committed names under the CURRENT kind, preserving the per-kind dedupe. */
  const addNames = (added: string[], forKind: SendRecipient['kind'] = kind) => {
    const fresh = added.filter((n) => !recipients.some((r) => r.kind === forKind && r.name === n));
    if (fresh.length === 0) return;
    setRecipients((prev) => [...prev, ...fresh.map((n) => ({kind: forKind, name: n}))]);
  };

  const addPending = () => {
    // The Add button drives the combobox's OWN commit so the button and Enter take one path —
    // otherwise only one of them would surface the invalid tokens the combobox requires to be shown.
    entryRef.current?.commit();
    entryRef.current?.focus();
  };

  /** Names already listed under the CURRENT kind — hidden from suggestions, never refused. */
  const listed = useMemo(
    () => new Set(recipients.filter((r) => r.kind === kind).map((r) => r.name)),
    [kind, recipients]
  );

  const remove = (recipient: SendRecipient) =>
    setRecipients((prev) => prev.filter((r) => !(r.kind === recipient.kind && r.name === recipient.name)));

  const canSubmit = recipients.length > 0 && !busy;

  const attempt = () => {
    // The Send control stays ENABLED with no recipients, deliberately: the rule asks for the
    // send to be refused INLINE, and a disabled button explains nothing — the user who typed a
    // name and forgot to commit it presses Send and is told what is missing. `submitDisabled`
    // would make the banner below unreachable, which is what the first version of this dialog
    // did: dead code where an acceptance criterion was supposed to be.
    setAttempted(true);
    if (canSubmit) onSubmit(recipients);
  };

  return (
    // No `autoFocusRef`: the control this dialog wants focused is a combobox, not an `<input>`
    // ref. Focus therefore lands twice on open — `FormDialog`'s fallback first, then the effect
    // above — which is `TableShareDialog`'s shipped behaviour and the same trade-off.
    <FormDialog
      title="Send to…"
      ariaLabel={`Send ${names.length === 1 ? names[0] : `${names.length} items`}`}
      submitLabel="Send"
      busy={busy}
      busyLabel="Sending…"
      className="max-w-lg"
      scrollBody
      onSubmit={attempt}
      onCancel={onCancel}>
      <p className="mb-3 mt-1 text-sm text-text-2">
        Copies what you&rsquo;ve selected into each recipient&rsquo;s space — you keep yours. It runs in the background,
        and every outcome comes back as a notification.
      </p>

      <div className="mb-4">
        <span className={SECTION_CAPTION}>Sending {items.length === 1 ? '1 item' : `${items.length} items`}</span>
        <ul
          aria-label="Items being sent"
          className="mt-0.5 max-h-24 overflow-y-auto rounded-md border border-border bg-surface-2 px-2.5 py-1.5">
          {items.map((item) => (
            <li
              key={item.key}
              className="break-all font-mono text-sm text-text">
              {itemName(item)}
              {item.kind === 'folder' && <span className="text-text-3">/</span>}
            </li>
          ))}
        </ul>
      </div>

      {/* with `sharedWorkspaces` off there is exactly ONE recipient kind, so the
          toggle does not render at all — a single-option radio group is a control that asks a
          question with one answer, and implies the other option exists somewhere. */}
      {sharedSpacesEnabled && (
        <fieldset className="mb-3">
          <legend className={FIELD_LABEL}>Send to</legend>
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
                  name="file-send-kind"
                  value={option.value}
                  checked={kind === option.value}
                  disabled={busy}
                  onChange={() => {
                    // The entry is CLEARED with the toggle, not carried across it. `key={kind}`
                    // already remounts the field so a note cannot outlive its kind, but the
                    // typed text is this component's state — and half a username left in a
                    // space field silently prefixes whatever is typed next, which reads as the
                    // suggestions being broken.
                    setKind(option.value);
                    setEntry('');
                  }}
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
          {/* ONE field for both kinds, differing only in what it suggests and what it calls
              things. `key={kind}` REMOUNTS on a toggle so a note raised under one kind cannot
              linger over the other. The source is a PROP: this dialog calls neither
              suggestion hook from inside the field. */}
          <UsernameCombobox
            {...(kind === 'space' ? spaceSuggestions : userSuggestions)}
            key={kind}
            ref={entryRef}
            id="file-send-recipients"
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
        {/* Kept alongside Enter-to-commit: the button is the discoverable affordance, and it
            stays enabled whenever there is text so clicking it on a malformed entry EXPLAINS the
            problem rather than sitting dead. */}
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

      {/* Submitting with no recipients is refused INLINE and sends nothing. */}
      {attempted && recipients.length === 0 && (
        <Banner
          variant="warning"
          className="mt-4"
          role="alert">
          Add at least one recipient before sending.
        </Banner>
      )}

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
