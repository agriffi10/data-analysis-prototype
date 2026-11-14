import {useId, useRef, useState} from 'react';
import {useLocation} from '../../lib/navigation';
import {ErrorBanner} from '../../components/ErrorBanner';
import {FIELD_HINT, FIELD_LABEL, SELECT_CLASS} from '../../components/fieldStyles';
import {FormDialog} from '../../components/FormDialog';
import {useToast} from '../../components/toastContext';
import {FEEDBACK_CATEGORIES, MAX_FEEDBACK_MESSAGE_CHARS, MAX_FEEDBACK_ROUTE_CHARS} from './feedback.constants';
import type {FeedbackCategory} from './feedback.types';
import {useSubmitFeedback} from './useSubmitFeedback';

type FeedbackDialogProps = {
  /** Closes the dialog. Called on cancel, on dismissal, and after a successful submission. */
  onClose: () => void;
};

/**
 * The Give feedback modal: a category, a message, and the page you were on.
 *
 * The captured path is read ONCE, when this component mounts — which is when the dialog opens,
 * because the host mounts it only while open. Reading it at submit time would record where the
 * user ended up rather than where they were when something went wrong, and a user who navigates
 * mid-sentence is exactly the case worth getting right.
 *
 * No category is preselected. A default would be the modal answer to every submission, and the
 * field exists to record a choice somebody made — so the picker opens on a placeholder and Send
 * stays disabled until it is replaced.
 *
 * Enter submits from the CATEGORY select and from nowhere else: the message is a textarea, where
 * Enter has to insert a newline. `FormDialog` suppresses the browser's implicit submission for
 * every input and select in the form and then submits only from `submitOnEnterRef`, so this is
 * one prop rather than a keydown handler here.
 *
 * @example
 * {open && <FeedbackDialog onClose={() => setOpen(false)} />}
 */
export function FeedbackDialog({onClose}: FeedbackDialogProps) {
  const {pathname} = useLocation();
  // Clipped to the route's own cap. The `*` 404 route renders inside the shell, so the header —
  // and this control — appear on any garbage URL, which is precisely when somebody wants to
  // report something. Unclipped, the server refuses the submission and the user reads
  // "Something went wrong" for a path they did not type.
  const [capturedRoute] = useState(() => pathname.slice(0, MAX_FEEDBACK_ROUTE_CHARS));
  const [category, setCategory] = useState<FeedbackCategory | ''>('');
  const [message, setMessage] = useState('');
  const [failure, setFailure] = useState<unknown>(null);
  const categoryRef = useRef<HTMLSelectElement>(null);
  const categoryId = useId();
  const messageId = useId();
  const routeNoteId = useId();
  const toast = useToast();
  const submit = useSubmitFeedback();

  const ready = category !== '' && message.trim() !== '';

  const send = async () => {
    // Defence in depth, not the enforcement: `FormDialog` already refuses to submit while
    // `submitDisabled` or `busy` is set, so neither arm is reachable from the dialog's own
    // controls. It is here for a caller that invokes this directly.
    if (!ready || submit.isPending) return;
    setFailure(null);
    const result = await submit
      .mutateAsync({category, message: message.trim(), route: capturedRoute})
      // `apiRequest` returns a result on every path and never throws, so this arm is unreachable
      // today. It is here because the alternative to an unreachable arm is an unhandled
      // rejection: a click that clears the busy state, renders nothing, and loses the message.
      //
      // It carries a CODE like every other authored failure. Without one the dialog would reach
      // the generic sentence by accident rather than by decision, which is the distinction
      // `errorMessages` exists to keep.
      .catch(() => ({success: false, error: {message: '', code: 'InternalError'}}) as const);
    if (!result.success) {
      setFailure(result.error);
      return;
    }
    // Cleared before closing so reopening the dialog does not show the last submission — the
    // component unmounts either way today, and resting on that would make this silently wrong
    // the first time somebody keeps it mounted.
    setMessage('');
    setCategory('');
    onClose();
    toast.push({variant: 'success', message: 'Thanks — your feedback has been sent.'});
  };

  return (
    <FormDialog
      title="Give feedback"
      ariaLabel="Give feedback"
      submitLabel="Send"
      busy={submit.isPending}
      busyLabel="Sending…"
      submitDisabled={!ready}
      // Only `submitOnEnterRef`: `autoFocusRef` is typed for an input and calls `.select()`,
      // which a select element does not have. FormDialog's own fallback focuses the form's first
      // focusable control, which is this same picker.
      submitOnEnterRef={categoryRef}
      onSubmit={() => void send()}
      onCancel={onClose}>
      <p className="mt-3 text-sm text-text-2">
        Tell us what is on your mind. We read everything that comes through, though we cannot reply here.
      </p>

      <div className="mt-4">
        <label
          htmlFor={categoryId}
          className={FIELD_LABEL}>
          What is this about?
        </label>
        <select
          id={categoryId}
          ref={categoryRef}
          required
          aria-required="true"
          value={category}
          disabled={submit.isPending}
          onChange={(e) => setCategory(e.target.value as FeedbackCategory | '')}
          className={`${SELECT_CLASS} w-full`}>
          <option value="">Choose one…</option>
          {FEEDBACK_CATEGORIES.map((option) => (
            <option
              key={option.value}
              value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div className="mt-4">
        <label
          htmlFor={messageId}
          className={FIELD_LABEL}>
          Your feedback
        </label>
        <textarea
          id={messageId}
          required
          aria-required="true"
          value={message}
          rows={6}
          maxLength={MAX_FEEDBACK_MESSAGE_CHARS}
          disabled={submit.isPending}
          aria-describedby={routeNoteId}
          onChange={(e) => setMessage(e.target.value)}
          className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        />
        <p
          id={routeNoteId}
          className={FIELD_HINT}>
          The page you were on (<code>{capturedRoute}</code>) is included with your message.
        </p>
      </div>

      {failure != null && (
        <ErrorBanner
          className="mt-4"
          error={failure}
        />
      )}
    </FormDialog>
  );
}
