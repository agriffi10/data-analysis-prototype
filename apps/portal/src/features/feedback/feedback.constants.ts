import type {FeedbackCategory} from './feedback.types';

/**
 * The categories, in the order the picker offers them, each with the wording a user reads.
 *
 * A list rather than a `Record`, because the ORDER is part of the design and a record's key order
 * is not something to rely on. The labels say what the category is *for* — "Something is broken"
 * rather than "Bug" — because the word alone leaves a user guessing which of two boxes their
 * problem belongs in, and a miscategorised report is worse than an uncategorised one.
 */
export const FEEDBACK_CATEGORIES: readonly {value: FeedbackCategory; label: string}[] = [
  {value: 'bug', label: 'Something is broken'},
  {value: 'idea', label: 'An idea or a request'},
  {value: 'question', label: 'A question'},
  {value: 'other', label: 'Something else'}
];

/**
 * The longest message the dialog will let a user submit.
 *
 * Mirrors `routes/feedback.py`'s own cap, which is the control — this one is a courtesy that
 * stops a user writing past the limit and losing the overflow to a refusal. A test holds the pair
 * together.
 */
export const MAX_FEEDBACK_MESSAGE_CHARS = 4000;

/**
 * The longest captured path the dialog will send.
 *
 * Mirrors `routes/feedback.py`'s own cap, and unlike the message cap this one is not a courtesy:
 * the app renders its shell on the `*` 404 route, so an arbitrarily long URL reaches the header
 * and the control. Unclipped, the route refuses the whole submission over a path the user never
 * typed and could not shorten.
 */
export const MAX_FEEDBACK_ROUTE_CHARS = 200;
