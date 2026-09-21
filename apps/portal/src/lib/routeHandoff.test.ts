import {describe, expect, it} from 'vitest';
import {buildExploreSqlHandoff, readExploreSqlHandoff} from './routeHandoff';

describe('the Data Explorer hand-off', () => {
  it('reads back exactly what it built', () => {
    const state = buildExploreSqlHandoff({body: 'SELECT 1', label: 'x'});
    expect(state).toEqual({exploreSql: {body: 'SELECT 1', label: 'x'}});
    expect(readExploreSqlHandoff(state)).toEqual({body: 'SELECT 1', label: 'x'});
  });

  it.each([
    ['a non-string body', {exploreSql: {body: 42}}],
    ['a missing label', {exploreSql: {body: 'SELECT 1'}}],
    ['a blank body', {exploreSql: {body: '  ', label: 'x'}}],
    ['no state', null],
    ['an empty object', {}],
    ['an inherited hand-off', Object.create({exploreSql: {body: 'SELECT 1', label: 'x'}}) as object]
  ])('refuses %s', (_case, state) => {
    expect(readExploreSqlHandoff(state)).toBeNull();
  });
});
