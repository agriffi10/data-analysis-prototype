import type {FeedbackSubmitRequest} from '../../types/apiContract.generated';

/**
 * Which kind of feedback a submission is.
 *
 * Derived from the generated request type rather than written out again: the vocabulary is
 * declared in Python and emitted into the contract, so a fifth category added there widens this
 * automatically, and one removed there fails `tsc -b` at the picker rather than at runtime.
 */
export type FeedbackCategory = FeedbackSubmitRequest['category'];
