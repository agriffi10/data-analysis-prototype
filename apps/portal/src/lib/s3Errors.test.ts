import {describe, it, expect} from 'vitest';
import {isNotFound} from './s3Errors';

describe('isNotFound', () => {
  it.each([
    {label: 'GetObject on a missing key', err: {name: 'NoSuchKey'}},
    {label: 'HeadObject on a missing key', err: {name: 'NotFound'}},
    {label: 'a 404 in $metadata', err: {name: 'SomethingElse', $metadata: {httpStatusCode: 404}}}
  ])('is true for $label', ({err}) => {
    expect(isNotFound(err)).toBe(true);
  });

  it.each([
    {label: 'a denial', err: {name: 'AccessDenied', $metadata: {httpStatusCode: 403}}},
    {label: 'an ordinary Error', err: new Error('network down')}
  ])('is false for $label', ({err}) => {
    expect(isNotFound(err)).toBe(false);
  });

  // A non-object throw must be answered, not re-thrown: this is a predicate a
  // catch block calls before deciding what the error means (SPEC-150 FR-009).
  it.each([
    {label: 'null', value: null},
    {label: 'undefined', value: undefined},
    {label: 'a string', value: 'NoSuchKey'},
    {label: 'a number', value: 404}
  ])('returns false for $label rather than throwing', ({value}) => {
    expect(() => isNotFound(value)).not.toThrow();
    expect(isNotFound(value)).toBe(false);
  });
});
