import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import {Input} from '../../components/Input';
import {cx} from '../../lib/cx';
import {useUserDirectory} from './useUserDirectory';
import {parseMemberInputDetailed} from '../shared-spaces/memberInput';
import {CATALOG_IDENTIFIER_RULE} from '../../lib/catalogIdentifier';

export type UsernameComboboxProps = {
  label: string;
  value: string;
  onChange: (next: string) => void;
  onCommit: (username: string) => void;
  /**
   * Bulk commit for a multi-token entry or paste, split by `parseMemberInputDetailed`.
   * Optional — but `TableShareDialog`'s user entry is a bulk field today, so a consumer that
   * omits this loses that shipped capability for everything after the first token.
   */
  onCommitMany?: (usernames: string[]) => void;
  /** Names REFUSED on commit, with `excludeReason`, and hidden from the suggestions. */
  exclude?: ReadonlySet<string>;
  excludeReason?: (username: string) => string;
  /**
   * Names hidden from the suggestions but NOT refused — committing one is a silent no-op for
   * the consumer to absorb. This is what already-committed chips are: offering one again is
   * noise, but refusing it with an error would turn a harmless double-click into a complaint.
   */
  suppress?: ReadonlySet<string>;
  placeholder?: string;
  disabled?: boolean;
  id?: string;
  /** Extra ids to attach to the input's `aria-describedby` (a caller's help line). */
  describedBy?: string;
};

/**
 * What a caller can drive from outside.
 *
 * `commit` exists for `TableShareDialog`, which keeps its **Add** button beside the field.
 * The button must go through the SAME path as Enter — otherwise the two would drift, and
 * SPEC-148 FR-003 requires invalid tokens to be surfaced however the commit was triggered.
 * One commit path, two ways to reach it.
 */
export type UsernameComboboxHandle = {
  /** Commit the highlighted option, or the typed text split into tokens. */
  commit: () => void;
  focus: () => void;
};

/** Results shown at once. Eight fits a phone dropdown without scrolling. */
const MAX_SUGGESTIONS = 8;

/** How long the announcement waits, so a fast typist is not read a queue of counts. */
const ANNOUNCE_DEBOUNCE_MS = 400;

/** Roughly the list's own height; below this much room it flips above the field. */
const ESTIMATED_LIST_HEIGHT = 260;

/**
 * An accessible single-value username typeahead over the published directory (SPEC-146).
 *
 * **The directory is ADVISORY and this component never blocks a name it does not know.** It is
 * up to a day stale, it misses users not yet provisioned, and it is not the authority on who
 * exists — the control plane is, and it *already reports an unknown name*: `add_members.py`
 * notifies the space owner by name, and table-share reports unresolved recipients. So a name
 * absent from the directory is a SLOWER path, not a lost one, and refusing it here would turn a
 * stale cache into a hard failure in a flow whose current behaviour is at least permissive.
 * Suggestions are suggestions; valid free text always commits.
 *
 * Built on the ARIA combobox pattern rather than on this repo's `Menu` primitive, which is
 * `role="menu"` with arrow-key roving — correct for a menu and wrong here. A combobox keeps DOM
 * focus in the text input at all times and moves a *virtual* cursor with `aria-activedescendant`
 * (WCAG 4.1.2). Reusing `Menu` would look fine and be unusable with a screen reader.
 *
 * @example
 * <UsernameCombobox label="Usernames" value={entry} onChange={setEntry}
 *   onCommit={(name) => add([name])} onCommitMany={add} />
 */
export const UsernameCombobox = forwardRef<UsernameComboboxHandle, UsernameComboboxProps>(function UsernameCombobox(
  {
    label,
    value,
    onChange,
    onCommit,
    onCommitMany,
    exclude,
    excludeReason,
    suppress,
    placeholder,
    disabled = false,
    id,
    describedBy
  },
  ref
) {
  const reactId = useId();
  const inputId = id ?? `${reactId}-input`;
  const listboxId = `${reactId}-listbox`;
  const noteId = `${reactId}-note`;

  const {status, search} = useUserDirectory();
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [announced, setAnnounced] = useState<{query: string; count: number} | null>(null);
  const [dropUp, setDropUp] = useState(false);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const query = value.trim();
  // Memoised so its identity is stable across renders — `commit` depends on it, and an array
  // rebuilt every render would rebuild every callback that reads it.
  const suggestions = useMemo(
    () =>
      status === 'ready' && query
        ? // Ask for enough headroom that filtering cannot empty the list while matches remain.
          search(query, MAX_SUGGESTIONS + (exclude?.size ?? 0) + (suppress?.size ?? 0))
            .filter((result) => !exclude?.has(result.username) && !suppress?.has(result.username))
            .slice(0, MAX_SUGGESTIONS)
        : [],
    [exclude, query, search, status, suppress]
  );
  const listOpen = open && suggestions.length > 0;

  // CLAMPED, because `suggestions` can shrink for reasons the input never sees. The keyboard
  // handlers reset the highlight on typing, Escape, Tab and commit — but not when a caller
  // changes `exclude`/`suppress`, which is exactly what SPEC-148 does (`exclude` is the member
  // list, backed by a refetchable query). Without this, `aria-activedescendant` can point at an
  // element that no longer exists — no option reports itself active, and Enter quietly commits
  // the raw typed text instead of the option that was last announced.
  const active = highlighted < suggestions.length ? highlighted : -1;

  // Announce the result count politely and late. `role="status"` reaches AT without moving
  // focus (WCAG 4.1.3); the delay is what stops a fast typist being read every intermediate
  // count on the way to the name they wanted.
  //
  // The debounced count is STAMPED WITH THE QUERY IT COUNTED, and the announcement is derived
  // from that rather than cleared by a second effect. Two things fall out: the effect never
  // calls setState synchronously (react-hooks/set-state-in-effect), and a count can never be
  // read out against a query it did not describe — which is what a bare "clear it on change"
  // would allow in the window before the next timer fires.
  useEffect(() => {
    if (!open || !query || status !== 'ready') return;
    const counted = suggestions.length;
    const timer = setTimeout(() => setAnnounced({query, count: counted}), ANNOUNCE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [open, query, status, suggestions.length]);

  const announcement =
    open && status === 'ready' && announced?.query === query
      ? announced.count === 0
        ? 'No matches'
        : `${announced.count} matches`
      : '';

  // Flip above the field when there is not room below. A bounded max-height plus this flip is
  // sufficient — no positioning library, which would be a Tech Stack change (SPEC-147 FR-008).
  useLayoutEffect(() => {
    if (!listOpen) return;
    const box = wrapperRef.current?.getBoundingClientRect();
    if (!box) return;
    setDropUp(window.innerHeight - box.bottom < ESTIMATED_LIST_HEIGHT && box.top > ESTIMATED_LIST_HEIGHT);
  }, [listOpen]);

  useEffect(() => {
    if (!listOpen) return;
    function onPointerDown(event: MouseEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [listOpen]);

  /**
   * Commit what is allowed; return the refusal message for anything excluded, or null.
   *
   * It RETURNS the refusal rather than setting the error itself so that the caller can set the
   * error exactly once. An earlier version set it here and then had `commit` overwrite it a
   * line later, which silently swallowed every exclusion message.
   */
  const commitNames = useCallback(
    (names: string[]): string | null => {
      const allowed: string[] = [];
      let refusal: string | null = null;
      for (const name of names) {
        if (exclude?.has(name)) {
          refusal ??= excludeReason?.(name) ?? `${name} is already on the list.`;
          continue;
        }
        allowed.push(name);
      }
      if (allowed.length === 0) {
        // Nothing was committed, so any note describing an EARLIER commit is now stale — it
        // would read as if it described the name just refused.
        setNote(null);
        return refusal;
      }

      // The unlisted-name note is shown only when the directory is READY. While it is loading
      // or unavailable a note would either arrive a second after the name was accepted (reading
      // as a delayed rejection) or tell the user their colleague "was not found" because a
      // background fetch failed — worse than saying nothing.
      if (status === 'ready') {
        const unlisted = allowed.filter((name) => search(name, 1)[0]?.username !== name);
        setNote(
          unlisted.length === 0
            ? null
            : `${unlisted.join(', ')} ${unlisted.length === 1 ? 'is' : 'are'} not in the directory — the name will be checked when the request is sent.`
        );
      } else {
        setNote(null);
      }

      if (onCommitMany) onCommitMany(allowed);
      else onCommit(allowed[0]);
      setOpen(false);
      setHighlighted(-1);
      return refusal;
    },
    [exclude, excludeReason, onCommit, onCommitMany, search, status]
  );

  /**
   * Commit `raw` as a token list.
   *
   * NOT verbatim: a comma- or whitespace-separated entry commits every valid token, and the
   * invalid ones stay in the input to be fixed instead of silently vanishing — the departure
   * from `parseMemberInput`'s silent drop that this component exists to afford.
   */
  const commitTyped = useCallback(
    (raw: string) => {
      const {valid, invalid} = parseMemberInputDetailed(raw);
      if (valid.length === 0 && invalid.length === 0) return;
      const refusal = commitNames(valid);
      // BOTH reasons are reported when both apply. An earlier version showed only the rule
      // sentence whenever there was malformed input, so a paste like `bob, cara, 1bad` — with
      // `cara` already a member — dropped `cara` with no chip and no explanation. That is the
      // exact silent drop this component exists to remove, reintroduced one branch deeper.
      //
      // Still ONE `setError` call, so neither message can overwrite the other.
      const reasons = [invalid.length > 0 ? CATALOG_IDENTIFIER_RULE : null, refusal].filter(Boolean);
      setError(reasons.length > 0 ? reasons.join(' ') : null);
      onChange(invalid.join(' '));
    },
    [commitNames, onChange]
  );

  /** Commit the highlighted option, or whatever is typed. */
  const commit = useCallback(() => {
    if (active >= 0 && suggestions[active]) {
      setError(commitNames([suggestions[active].username]));
      onChange('');
      return;
    }
    commitTyped(value);
  }, [active, commitNames, commitTyped, onChange, suggestions, value]);

  useImperativeHandle(ref, () => ({commit, focus: () => inputRef.current?.focus()}), [commit]);

  /**
   * A pasted LIST commits immediately; a pasted single name is an ordinary paste.
   *
   * The split is deliberate. Someone pasting `bob, cara` has already told you they are done
   * with both names, and making them press Enter afterwards is a step with no decision in it.
   * Someone pasting one name very often wants to correct a character first, so auto-committing
   * would take the field away from them.
   */
  function onPaste(event: React.ClipboardEvent<HTMLInputElement>) {
    const pasted = event.clipboardData.getData('text');
    if (!/[\s,]/.test(pasted.trim())) return;
    event.preventDefault();
    // Spliced at the caret rather than appended, so a paste over a selection REPLACES it and a
    // mid-word paste does not silently glue two tokens together. `selectionStart/End` are the
    // browser's own view of the field; the `?? value.length` fallback covers a target with no
    // selection.
    const field = event.currentTarget;
    const start = field.selectionStart ?? value.length;
    const end = field.selectionEnd ?? value.length;
    commitTyped(`${value.slice(0, start)} ${pasted} ${value.slice(end)}`);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      // Only intercept when the list is open. With it closed, Escape is not touched at all, so
      // the enclosing Modal/Drawer dismisses normally.
      //
      // `stopPropagation` is what does the work, VERIFIED rather than assumed (SPEC-147
      // FR-004): React delegates events at its root container, which sits BELOW the `document`
      // listener `useEscapeKey` registers, so stopping the native event there means the hook
      // never fires. Measured — a Modal's `onDismiss` is called zero times. `useEscapeKey`
      // therefore needed no `defaultPrevented` guard and did not get one.
      //
      // `preventDefault` is not redundant: some browsers treat Escape in a text input as
      // "revert the value", and this is a field whose content must survive closing the list.
      if (!listOpen) return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      setHighlighted(-1);
      return;
    }
    if (event.key === 'Tab') {
      // Closes the list and commits NOTHING — the typed text stays put. A Tab that committed
      // would turn "move on to the next field" into an action the user did not ask for.
      setOpen(false);
      setHighlighted(-1);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      commit();
      return;
    }
    if (suggestions.length === 0) return;
    const last = suggestions.length - 1;
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        setOpen(true);
        setHighlighted(active >= last ? 0 : active + 1);
        break;
      case 'ArrowUp':
        event.preventDefault();
        setOpen(true);
        setHighlighted(active <= 0 ? last : active - 1);
        break;
      case 'Home':
        if (!listOpen) return;
        event.preventDefault();
        setHighlighted(0);
        break;
      case 'End':
        if (!listOpen) return;
        event.preventDefault();
        setHighlighted(last);
        break;
      default:
    }
  }

  const optionId = (index: number) => `${reactId}-option-${index}`;

  return (
    <div
      ref={wrapperRef}
      className="relative">
      <Input
        ref={inputRef}
        id={inputId}
        label={label}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        error={error}
        role="combobox"
        aria-expanded={listOpen}
        aria-controls={listboxId}
        aria-autocomplete="list"
        // Absent rather than empty when nothing is highlighted: an empty value is a broken
        // reference, and some screen readers announce it as one.
        aria-activedescendant={listOpen && active >= 0 ? optionId(active) : undefined}
        aria-describedby={cx(describedBy, note ? noteId : undefined) || undefined}
        autoComplete="off"
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
          setHighlighted(-1);
          setError(null);
          setNote(null);
        }}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
      />

      {listOpen && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label={`${label} suggestions`}
          className={cx(
            'absolute z-20 max-h-60 w-full overflow-y-auto rounded-md border border-border bg-surface py-1 shadow-lg',
            dropUp ? 'bottom-full mb-1' : 'top-full mt-1'
          )}>
          {suggestions.map((suggestion, index) => (
            <li
              key={suggestion.username}
              id={optionId(index)}
              role="option"
              aria-selected={index === active}
              // onMouseDown, not onClick: mousedown fires before the input's blur, so the
              // commit lands while the field still exists.
              onMouseDown={(event) => {
                event.preventDefault();
                setError(commitNames([suggestion.username]));
                onChange('');
                inputRef.current?.focus();
              }}
              onMouseEnter={() => setHighlighted(index)}
              className={cx(
                'flex min-h-11 cursor-pointer items-center px-3 font-mono text-sm text-text tablet:min-h-9',
                index === active && 'bg-surface-2'
              )}>
              {suggestion.username}
            </li>
          ))}
        </ul>
      )}

      {note && (
        <p
          id={noteId}
          className="mt-1.5 text-xs text-text-3">
          {note}
        </p>
      )}

      <span
        role="status"
        aria-live="polite"
        className="sr-only">
        {announcement}
      </span>
    </div>
  );
});
