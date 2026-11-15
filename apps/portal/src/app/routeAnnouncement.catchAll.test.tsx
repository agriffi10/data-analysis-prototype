import {act, waitFor} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {renderApp} from '../test/appRouter';
import {authenticated} from '../test/authFixtures';
import {announcements, standInRouter} from '../test/nextNavigation';
import {CATCH_ALL_RECORDS} from '../test/renderWithProviders';
import {AREAS} from '../lib/navigation';
import {formatPageTitle} from '../lib/formatPageTitle';
import {recordTitleWrites} from '../test/titleWrites';
import {catchAllPageName} from './[[...slug]]/catchAllPageName';

/** A view's first chunk is transformed on demand, which outlasts `waitFor`'s default on a cold cache. */
const LOADING = {timeout: 10_000};

/** Two such waits, which the test's own default of five seconds would cut short. */
const BUDGET = 20_000;

/** Every value written to `document.title` in each test, in order. */
const writes = recordTitleWrites();

/** Every path the route table names but its not-found match: what the catch-all's mount must name as the table does. */
const TABLE_PATHS = [
  ...Object.values(
    import.meta.glob<string>('../routes/table.tsx', {query: '?raw', import: 'default', eager: true})
  )[0].matchAll(/\bpath="([^"]+)"/g)
]
  .map(([, path]) => path)
  .filter((path) => path !== '*');

describe('the catch-all page’s first visit', () => {
  // The catch-all is visited once in this file, from a page the App Router serves, so its route
  // table's chunk is still loading when the router commits it.
  it(
    'announces Not Found for an unknown path, the title the table then sets',
    async () => {
      renderApp('/files', {auth: authenticated('alice'), routers: {files: 'app'}});
      await waitFor(() => expect(document.title).toBe('Files — Data Quarry'), LOADING);

      act(() => standInRouter().push('/nope'));
      await waitFor(() => expect(document.title).toBe('Not Found — Data Quarry'), LOADING);

      expect(announcements(), 'the catch-all titles itself as it mounts').toEqual(['Not Found — Data Quarry']);
    },
    BUDGET
  );

  // Its title is the product's alone, which the announcer read as the document hydrated, before any
  // page mounted, and it announces only a change.
  it(
    'is silent for the landing page on the first navigation after a document load',
    async () => {
      renderApp('/files', {auth: authenticated('alice'), routers: {files: 'app'}});
      await waitFor(() => expect(document.title).toBe('Files — Data Quarry'), LOADING);

      act(() => standInRouter().push('/'));
      // The mount's write, then the landing page's own.
      await waitFor(() => expect(writes.filter((write) => write === 'Data Quarry')).toHaveLength(2), LOADING);

      expect(document.title).toBe('Data Quarry');
      expect(announcements()).toEqual([]);
    },
    BUDGET
  );

  it.each(TABLE_PATHS)(
    'names %s as the route table’s element titles it',
    async (path) => {
      renderApp(path, {auth: authenticated('alice')});
      await waitFor(() => expect(writes.length).toBeGreaterThanOrEqual(2), LOADING);

      expect(writes).toEqual(writes.map(() => formatPageTitle(catchAllPageName(path, CATCH_ALL_RECORDS) ?? undefined)));
    },
    BUDGET
  );

  it('names each path as the route table serves it', () => {
    expect(catchAllPageName('/', AREAS)).toBe('');
    expect(catchAllPageName('/nope', AREAS)).toBe('Not Found');
    expect(catchAllPageName('/Files', CATCH_ALL_RECORDS)).toBe('Not Found');
    expect(catchAllPageName('/files', CATCH_ALL_RECORDS)).toBeNull();
    expect(catchAllPageName('/files', AREAS)).toBe('Not Found');
  });
});
