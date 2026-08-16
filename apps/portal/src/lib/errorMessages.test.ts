import {describe, expect, it} from 'vitest';
import {toUserMessage} from './errorMessages';

// The two Athena failures that arrive as the SAME AWS name, `InvalidRequestException`,
// and must not resolve to the same sentence. Transcribed from real 400 bodies observed
// against deployed prod on 2026-08-15.
const STILL_RUNNING = {
  name: 'InvalidRequestException',
  message: 'Query has not yet finished. Current state: QUEUED'
};
const MALFORMED = {
  name: 'InvalidRequestException',
  message: "line 3:36: mismatched input '>'. Expecting: ')', ','"
};

describe('toUserMessage — reading results too early', () => {
  it('says the query is still running, not "Contact the Administrator"', () => {
    const {message} = toUserMessage(STILL_RUNNING);

    expect(message).toBe('The query is still running. Give it a moment and try again.');
    // The regression in one assertion: this exact error, on an ordinary first load, used
    // to render the app's most alarming sentence because nothing matched it.
    expect(message).not.toMatch(/Contact the Administrator/i);
  });

  it('still calls a malformed query a syntax error', () => {
    // The guard that matters for the rule ABOVE it. Both errors carry the same AWS name,
    // so keying the new rule on `name` would have been a `code` rule — and `code` rules
    // win over every message rule, which would have turned every syntax error in the app
    // into "the query is still running". Ordering inside MATCH_RULES is load-bearing too:
    // delete the `line \d+:\d+` alternative and this passes for the wrong reason.
    expect(toUserMessage(MALFORMED).message).toBe('There’s a syntax error in your query. Check the SQL and try again.');
  });

  it('matches the state error on the Athena error code as well as the sentence', () => {
    // Athena sends `AthenaErrorCode: INVALID_QUERY_EXECUTION_STATE` alongside the prose,
    // and the prose is the half AWS is free to reword.
    expect(toUserMessage({name: 'InvalidRequestException', message: 'INVALID_QUERY_EXECUTION_STATE'}).message).toBe(
      'The query is still running. Give it a moment and try again.'
    );
  });

  it('leaves a genuinely unknown error on the generic fallback', () => {
    // The fallback must keep working: this rule narrows what reaches it, and does not
    // pretend to recognise everything.
    expect(toUserMessage({name: 'SomethingNobodyMapped', message: 'kaboom'}).message).toBe(
      'Something went wrong. Contact the Administrator.'
    );
  });
});
