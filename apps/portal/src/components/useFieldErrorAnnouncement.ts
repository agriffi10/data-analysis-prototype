import {useEffect, useReducer, useRef, useState, type KeyboardEvent, type RefObject, type SetStateAction} from 'react';

type Field = HTMLInputElement | HTMLTextAreaElement;

/** Input types that take no typing, so focus in one of them is not someone typing elsewhere. */
const NOT_TYPED = new Set([
  'button',
  'checkbox',
  'color',
  'file',
  'hidden',
  'image',
  'radio',
  'range',
  'reset',
  'submit'
]);

function typingElsewhere(field: Field | null): boolean {
  const active = (field?.ownerDocument ?? document).activeElement;
  if (active === null || active === field) return false;
  if (active instanceof HTMLTextAreaElement) return true;
  if (active instanceof HTMLInputElement) return !NOT_TYPED.has(active.type);
  return active instanceof HTMLElement && active.isContentEditable;
}

/** Appended to repeat a message verbatim: identical text is no change, and a reader speaks only a change. */
const REPEAT = String.fromCharCode(0xa0);

/** The error as spoken away from the field: led by the field's name, unless the message already is. */
function spoken(field: Field | null, error: string): string {
  const name = (field?.getAttribute('aria-label') || field?.labels?.[0]?.textContent || '').trim();
  return name === '' || error.toLowerCase().startsWith(name.toLowerCase()) ? error : `${name}: ${error}`;
}

/**
 * When a field's validation error is spoken. The error itself is the field's description
 * (`aria-invalid` + `aria-describedby`), heard whenever the field is focused; this adds a POLITE
 * announcement at the moments the user can act on it, and never while they are typing — which
 * holds while the caller derives the error in the render its change produces, as every caller does:
 *
 * - when the field is **left** with an error they have not been told;
 * - when an error appears or changes **as the result of an action** — a button, a server reply,
 *   Enter handled by the form — which is any change not caused by typing in this field or by
 *   focus sitting in another text field;
 * - on **Enter** in the field, whatever error it then shows, even one already told: Enter asks
 *   for an outcome, and a disabled submit gives none.
 *
 * An error the field is created with is not spoken until the field is left or Enter is pressed in
 * it, so a blank row just
 * added does not interrupt before the user types — unless `speakInitial`, for a field that
 * reopens carrying a failure the user just caused. An `alert` instead would interrupt on every
 * keystroke that changes the message, and for another row's error while the user types in this one.
 *
 * The region carries no `role="status"`: every field renders one, and `aria-live="polite"` with
 * `aria-atomic` is spoken the same way without adding a status object per field.
 *
 * The announcement is set through state from the effect, a render after the change it reports —
 * for a Tab, meant to land after the next control's focus is announced rather than be cut off by
 * it; no screen reader has checked that ordering yet. It is cleared on focus, where the description
 * takes over, and whenever the error moves on from what was told.
 *
 * @param error - The field's current error; null, undefined or empty for none.
 * @param fieldRef - The field the error belongs to: its name leads the announcement, and focus in
 *   it is not focus elsewhere.
 * @param options - `speakInitial`: speak an error the field is created with, at once — and keep it
 *   through the first focus, which for a reopened dialog is its own autofocus in the same commit.
 * @returns The `announcement` for an always-present polite region, and handlers to call from the
 *   field's own — `onKeyDown` only for a single-line input, where Enter is not a newline.
 *
 * @example
 * const fieldRef = useRef<HTMLTextAreaElement>(null);
 * const spoken = useFieldErrorAnnouncement(error, fieldRef);
 * <textarea ref={fieldRef} onChange={(e) => { spoken.onChange(); onChange(e.target.value); }}
 *   onFocus={spoken.onFocus} onBlur={spoken.onBlur} … />
 * <span aria-live="polite" aria-atomic="true" className="sr-only">{spoken.announcement}</span>
 */
export function useFieldErrorAnnouncement(
  error: string | null | undefined,
  fieldRef: RefObject<Field | null>,
  {speakInitial = false}: {speakInitial?: boolean} = {}
) {
  const [announcement, setAnnouncement] = useState('');
  const [events, countEvent] = useReducer((n: number) => n + 1, 0);
  const typed = useRef(false);
  const left = useRef(false);
  const entered = useRef(false);
  const told = useRef<string | null>(null);
  const keepThroughFocus = useRef(false);
  const shown = useRef<string | null | undefined>(undefined);
  const current = error ? error : null;

  useEffect(() => {
    const before = shown.current;
    shown.current = current;
    const byTyping = typed.current;
    const byLeaving = left.current;
    const byEnter = entered.current;
    typed.current = false;
    left.current = false;
    entered.current = false;

    let next: SetStateAction<string> | null = null;
    if (current === null) {
      told.current = null;
      next = '';
    } else {
      const field = fieldRef.current;
      const initial = before === undefined;
      const raised = !initial && current !== before && !byTyping && !typingElsewhere(field);
      if (initial ? speakInitial : byEnter || ((byLeaving || raised) && current !== told.current)) {
        told.current = current;
        keepThroughFocus.current = initial;
        const text = spoken(field, current);
        next = (was) => (was === text ? text + REPEAT : text);
      } else if (!initial && current !== told.current) {
        next = '';
      }
    }
    if (next !== null) setAnnouncement(next);
  }, [current, events, fieldRef, speakInitial]);

  return {
    announcement,
    onChange: () => {
      typed.current = true;
      countEvent();
    },
    onFocus: () => {
      if (keepThroughFocus.current) keepThroughFocus.current = false;
      else setAnnouncement('');
    },
    onBlur: () => {
      left.current = true;
      countEvent();
    },
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key !== 'Enter' || e.nativeEvent.isComposing) return;
      entered.current = true;
      countEvent();
    }
  };
}
