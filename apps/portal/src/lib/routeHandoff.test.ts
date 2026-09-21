import {describe, expect, it} from 'vitest';
import {buildExploreSqlHandoff, buildOpenSqlHandoff, readExploreSqlHandoff, readOpenSqlHandoff} from './routeHandoff';

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

describe('the Query hand-off', () => {
  it('reads back exactly what it built', () => {
    const state = buildOpenSqlHandoff({sql: 'SELECT 1', label: 'x'});
    expect(state).toEqual({openSql: {sql: 'SELECT 1', label: 'x'}});
    expect(readOpenSqlHandoff(state)).toEqual({sql: 'SELECT 1', label: 'x'});
  });

  it.each([
    ['a non-string statement', {openSql: {sql: 1}}],
    ['a missing label', {openSql: {sql: 'SELECT 1'}}],
    ['no state', null],
    ['an empty object', {}],
    ['the other hand-off', {exploreSql: {body: 'SELECT 1', label: 'x'}}],
    ['an inherited hand-off', Object.create({openSql: {sql: 'SELECT 1', label: 'x'}}) as object]
  ])('refuses %s', (_case, state) => {
    expect(readOpenSqlHandoff(state)).toBeNull();
  });
});
