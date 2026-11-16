import {screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {renderApp} from './appRouter';
import {authenticated} from './authFixtures';
import {patternOf, selectPage} from './pageSelection';

/** A file map with every segment kind the app uses, so precedence has something to decide. */
const FILES = [
  'page.tsx',
  'shop/[[...path]]/page.tsx',
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
    ['/', 'page.tsx', {}],
    ['/shop', 'shop/[[...path]]/page.tsx', {}],
    ['/shop/a/b', 'shop/[[...path]]/page.tsx', {path: ['a', 'b']}],
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

  it.each(['/nope', '/files/extra', '/Files'])('serves %s from no page', (pathname) => {
    expect(selectPage(FILES, pathname)).toBeNull();
  });

  it('reads a route group as adding nothing to the address', () => {
    expect(patternOf('(signed-in)/files/page.tsx')).toBe('/files');
    expect(patternOf('(signed-in)/data-quality/[space]/[requestId]/page.tsx')).toBe('/data-quality/:space/:requestId');
    expect(patternOf('page.tsx')).toBe('/');
    expect(patternOf('shop/[[...path]]/page.tsx')).toBeNull();
  });
});

describe('the pages a render serves', () => {
  it('let a supplied page replace one on disk at the same path', async () => {
    renderApp('/', {pages: {'page.tsx': () => <p>replaced landing page</p>}});

    expect(await screen.findByText('replaced landing page')).toBeInTheDocument();
  });

  it('render the not-found page from disk at an address no page serves', async () => {
    renderApp('/nope', {auth: authenticated('alice')});

    expect(await screen.findByRole('heading', {name: 'Page not found'})).toBeInTheDocument();
  });
});
