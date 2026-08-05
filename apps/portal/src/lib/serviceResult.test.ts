import {describe, it, expect} from 'vitest';
import {unwrap, toServiceError} from './serviceResult';

// The four values a `throw` can produce that are not objects. `toServiceError`
// runs INSIDE a catch, in a function documented as never throwing, so a raised
// TypeError here would replace the error being reported with a different one
// (SPEC-150 FR-009).
const NON_OBJECT_THROWS = [
  {label: 'null', value: null},
  {label: 'undefined', value: undefined},
  {label: 'a string', value: 'boom'},
  {label: 'a number', value: 42}
];

describe('toServiceError', () => {
  it.each(NON_OBJECT_THROWS)('returns the fallback failure for $label, without throwing', ({value}) => {
    expect(() => toServiceError(value, 'Failed to list files')).not.toThrow();
    expect(toServiceError(value, 'Failed to list files')).toEqual({
      success: false,
      error: {message: 'Failed to list files', code: undefined}
    });
  });

  it('takes message and code from a normal Error', () => {
    const err = Object.assign(new Error('Access Denied'), {name: 'AccessDenied'});

    expect(toServiceError(err, 'Failed to list files')).toEqual({
      success: false,
      error: {message: 'Access Denied', code: 'AccessDenied'}
    });
  });

  it('takes them from an AWS SDK error object too', () => {
    const awsErr = {name: 'NoSuchKey', message: 'The specified key does not exist.', $metadata: {httpStatusCode: 404}};

    expect(toServiceError(awsErr, 'Failed to read')).toEqual({
      success: false,
      error: {message: 'The specified key does not exist.', code: 'NoSuchKey'}
    });
  });

  it('falls back when an object carries no message', () => {
    expect(toServiceError({name: 'Weird'}, 'Failed to read').error.message).toBe('Failed to read');
  });
});

describe('unwrap', () => {
  it('returns the data on success', () => {
    expect(unwrap({success: true, data: ['a']})).toEqual(['a']);
  });

  it('throws an Error carrying the message and code on failure', () => {
    expect(() => unwrap({success: false, error: {message: 'Sign in required', code: 'NotAuthenticated'}})).toThrow(
      'Sign in required'
    );

    try {
      unwrap({success: false, error: {message: 'Sign in required', code: 'NotAuthenticated'}});
    } catch (err) {
      expect((err as {code?: string}).code).toBe('NotAuthenticated');
    }
  });
});
