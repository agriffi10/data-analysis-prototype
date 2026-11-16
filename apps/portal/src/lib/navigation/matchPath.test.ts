import {describe, expect, it} from 'vitest';
import {matchPath} from './matchPath';

type Row = {path: string; end?: boolean; pathname: string; params: Record<string, string> | null};

/**
 * Every shape the seam's callers match: the area records' whole paths, `linkFlags`' prefixes and
 * the report's parameters, each given the path `decodePath` produces. A row's `params` is null when
 * the pattern must not match.
 */
const CORPUS: Row[] = [
  {path: '/files', pathname: '/files', params: {}},
  {path: '/files', pathname: '/files/', params: {}},
  {path: '/files', pathname: '/files//', params: {}},
  {path: '/files', pathname: '/Files', params: null},
  {path: '/files', pathname: '/files/extra', params: null},
  {path: '/files', pathname: '/filesystem', params: null},
  {path: '/files', pathname: '//files', params: null},
  {path: '/', pathname: '/', params: {}},
  {path: '/', pathname: '/files', params: null},
  {path: '/', end: false, pathname: '/files', params: {}},
  {path: '/files', end: false, pathname: '/files/alice', params: {}},
  {path: '/files', end: false, pathname: '/files', params: {}},
  {path: '/files', end: false, pathname: '/filesystem', params: null},
  {path: '/files', end: false, pathname: '/Files/alice', params: null},
  {
    path: '/data-quality/:space/:requestId',
    pathname: '/data-quality/alice/r1',
    params: {space: 'alice', requestId: 'r1'}
  },
  {
    path: '/data-quality/:space/:requestId',
    pathname: '/data-quality/a@b c/r1',
    params: {space: 'a@b c', requestId: 'r1'}
  },
  {
    path: '/data-quality/:space/:requestId',
    pathname: '/data-quality/a%40b/r1',
    params: {space: 'a%40b', requestId: 'r1'}
  },
  {
    path: '/data-quality/:space/:requestId',
    pathname: '/data-quality/a%2Fb/r1',
    params: {space: 'a/b', requestId: 'r1'}
  },
  {
    path: '/data-quality/:space/:requestId',
    pathname: '/data-quality/50%252F/r1',
    params: {space: '50%252F', requestId: 'r1'}
  },
  {
    path: '/data-quality/:space/:requestId',
    pathname: '/data-quality/alice/r1/',
    params: {space: 'alice', requestId: 'r1'}
  },
  {path: '/data-quality/:space/:requestId', pathname: '/data-quality/alice', params: null},
  {path: '/data-quality/:space/:requestId', pathname: '/data-quality//r1', params: null},
  {path: '/data-quality/:space/:requestId', pathname: '/data-quality/alice/r1/extra', params: null},
  {path: '/data-quality/:space/:requestId', pathname: '/Data-quality/alice/r1', params: null},
  {path: '/data-quality/:space', end: false, pathname: '/data-quality/alice/r1', params: {space: 'alice'}},
  {path: '/data-quality', pathname: '/data-quality/alice/r1', params: null},
  {path: '/query', end: false, pathname: '/query', params: {}},
  {path: '/help', pathname: '/help', params: {}}
];

describe('the seam’s matchPath', () => {
  it.each(CORPUS)('matches $path (end: $end) against $pathname as recorded', ({path, end, pathname, params}) => {
    const match = matchPath({path, end}, pathname);

    expect(match === null ? null : match.params).toEqual(params);
  });

  it('takes a bare string as a whole-path pattern', () => {
    expect(matchPath('/data-quality/:space/:requestId', '/data-quality/alice/r1')).toEqual({
      params: {space: 'alice', requestId: 'r1'}
    });
    expect(matchPath('/files', '/files/extra')).toBeNull();
  });

  it('refuses a splat or an optional segment rather than matching it wrongly', () => {
    expect(() => matchPath('/files/*', '/files/a')).toThrow(/does not model/);
    expect(() => matchPath('/files/:name?', '/files')).toThrow(/does not model/);
  });
});
