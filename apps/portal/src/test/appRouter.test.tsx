import {screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {AREAS} from '../lib/navigation';
import {pagesFor, renderApp} from './appRouter';
import {authenticated} from './authFixtures';
import {patternOf, selectPage} from './pageSelection';

/** A file map with every segment kind the app uses, so precedence has something to decide. */
const FILES = [
  '[[...slug]]/page.tsx',
  '(signed-in)/files/page.tsx',
  '(signed-in)/data-quality/page.tsx',
  '(signed-in)/data-quality/[space]/[requestId]/page.tsx',
  'docs/intro/page.tsx',
  'docs/[topic]/page.tsx',
  'docs/[...rest]/page.tsx'
];

describe('page selection, by Next’s rules', () => {
  it.each([
    ['/files', '(signed-in)/files/page.tsx', {}],
    ['/', '[[...slug]]/page.tsx', {}],
    ['/nope', '[[...slug]]/page.tsx', {slug: ['nope']}],
    ['/files/extra', '[[...slug]]/page.tsx', {slug: ['files', 'extra']}],
    [
      '/data-quality/a%40b%20c/r1',
      '(signed-in)/data-quality/[space]/[requestId]/page.tsx',
      {space: 'a%40b%20c', requestId: 'r1'}
    ],
    ['/docs/intro', 'docs/intro/page.tsx', {}],
    ['/docs/other', 'docs/[topic]/page.tsx', {topic: 'other'}],
    ['/docs/a/b', 'docs/[...rest]/page.tsx', {rest: ['a', 'b']}]
  ])('serves %s from %s', (pathname, file, params) => {
    expect(selectPage(FILES, pathname)).toEqual({file, params});
  });

  it('reads a route group as adding nothing to the address', () => {
    expect(patternOf('(signed-in)/files/page.tsx')).toBe('/files');
    expect(patternOf('(signed-in)/data-quality/[space]/[requestId]/page.tsx')).toBe('/data-quality/:space/:requestId');
    expect(patternOf('[[...slug]]/page.tsx')).toBeNull();
  });
});

describe('the pages a render serves', () => {
  const Page = () => null;
  const disk = {'[[...slug]]/page.tsx': Page, '(signed-in)/files/page.tsx': Page};
  const filesOn = (router: 'app' | 'catch-all') =>
    AREAS.map((record) => (record.area === 'files' ? {...record, router} : record));

  it('ignore an area’s page on disk while the catch-all serves it', () => {
    expect(Object.keys(pagesFor(disk, {}, filesOn('catch-all')))).toEqual(['[[...slug]]/page.tsx']);
  });

  it('take an area’s page, on disk or supplied, while the App Router serves it', () => {
    const Supplied = () => null;
    expect(pagesFor(disk, {}, filesOn('app'))['(signed-in)/files/page.tsx']).toBe(Page);
    expect(pagesFor(disk, {'(signed-in)/files/page.tsx': Supplied}, filesOn('app'))['(signed-in)/files/page.tsx']).toBe(
      Supplied
    );
  });

  it('let a supplied page replace one on disk at the same path', async () => {
    renderApp('/nope', {pages: {'[[...slug]]/page.tsx': () => <p>replaced catch-all</p>}});

    expect(await screen.findByText('replaced catch-all')).toBeInTheDocument();
  });

  it('render the real catch-all page from disk otherwise', async () => {
    renderApp('/nope', {auth: authenticated('alice')});

    expect(await screen.findByRole('heading', {name: 'Page not found'})).toBeInTheDocument();
  });
});
