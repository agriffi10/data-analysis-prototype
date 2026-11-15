import {act, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {renderApp} from '../test/appRouter';
import {authenticated} from '../test/authFixtures';
import {announcements, standInRouter} from '../test/nextNavigation';
import {patternOf} from '../test/pageSelection';
import {areaOf} from '../lib/navigation';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));

/** Every signed-in page file, with an address it serves and the area it belongs to. */
const PAGES = Object.keys(import.meta.glob('./**/page.tsx'))
  .map((file) => file.slice('./'.length))
  .filter((file) => file.startsWith('(signed-in)/'))
  .map((file) => {
    const path = (patternOf(file) ?? '').replace(/:(\w+)/g, (_, name: string) => `${name}-1`);
    const area = areaOf(path)?.area;
    if (!area) throw new Error(`${file} serves no area`);
    return {file, path, area};
  });

/** A view's first chunk is transformed on demand, which outlasts `waitFor`'s default on a cold cache. */
const LOADING = {timeout: 10_000};

/** Every value written to `document.title` in this test, in order. */
const writes: string[] = [];
const TITLE = Object.getOwnPropertyDescriptor(Document.prototype, 'title') as PropertyDescriptor;

beforeEach(() => {
  writes.length = 0;
  Object.defineProperty(document, 'title', {
    configurable: true,
    get: () => TITLE.get?.call(document) as string,
    set: (value: string) => {
      writes.push(value);
      TITLE.set?.call(document, value);
    }
  });
});
afterEach(() => {
  Reflect.deleteProperty(document, 'title');
});

describe('an App Router page’s first visit', () => {
  it('lists every signed-in page', () => {
    expect(PAGES.map(({file}) => file)).toContain('(signed-in)/files/page.tsx');
    expect(PAGES.length).toBeGreaterThanOrEqual(8);
  });

  // Each page is visited once in this file, so its view's chunk is still loading when the router
  // commits it, as on a user's first visit; a page left from the catch-all titles itself. The wait
  // for a write after the commit is what shows it: a view already loaded titles itself in the commit.
  it.each(PAGES)('announces the title its view sets: $file', async ({path, area}) => {
    renderApp(area === 'files' ? '/help' : '/files', {auth: authenticated('alice'), routers: {[area]: 'app'}});
    await waitFor(() => expect(writes.length).toBeGreaterThan(0), LOADING);
    const left = document.title;

    act(() => standInRouter().push(path));
    const committed = writes.length;
    await waitFor(() => expect(writes.length).toBeGreaterThan(committed), LOADING);

    expect(document.title).not.toBe(left);
    expect(announcements()).toEqual([document.title]);
  });
});
