import {act, screen, waitFor} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {renderApp} from '../test/appRouter';
import {authenticated} from '../test/authFixtures';
import {announcements, documentLoads, standInRouter} from '../test/nextNavigation';
import {recordTitleWrites} from '../test/titleWrites';

/** A view's first chunk is transformed on demand, which outlasts `waitFor`'s default on a cold cache. */
const LOADING = {timeout: 10_000};

/** Two such waits, which the test's own default of five seconds would cut short. */
const BUDGET = 20_000;

/** Every value written to `document.title` in each test, in order. */
const writes = recordTitleWrites();

describe('a public page’s first visit', () => {
  // A document load of the not-found page shows the root layout's title until the view's chunk
  // arrives, so the page names itself in the commit that mounts it, before the view has loaded.
  it('titles the not-found page as it mounts, before its view loads', () => {
    renderApp('/nope', {auth: authenticated('alice')});

    expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();
    expect(document.title).toBe('Not Found — Data Quarry');
  });

  // Next loads the document for a path no page serves, so the route announcer never reads the
  // not-found page: the browser announces the new document instead.
  it(
    'reaches an address no page serves by a document load, which the announcer never reads',
    async () => {
      renderApp('/files', {auth: authenticated('alice')});
      await waitFor(() => expect(document.title).toBe('Files — Data Quarry'), LOADING);

      act(() => standInRouter().push('/nope'));

      expect(documentLoads()).toEqual(['/nope']);
      expect(announcements()).toEqual([]);
    },
    BUDGET
  );

  // Its title is the product's alone, which the announcer read as the document hydrated, before any
  // page mounted, and it announces only a change.
  it(
    'is silent for the landing page on the first navigation after a document load',
    async () => {
      renderApp('/files', {auth: authenticated('alice')});
      await waitFor(() => expect(document.title).toBe('Files — Data Quarry'), LOADING);

      act(() => standInRouter().push('/'));
      // The page file's write, then the landing page's own.
      await waitFor(() => expect(writes.filter((write) => write === 'Data Quarry')).toHaveLength(2), LOADING);

      expect(document.title).toBe('Data Quarry');
      expect(announcements()).toEqual([]);
    },
    BUDGET
  );
});
