import {act, waitFor} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import {renderApp} from '../test/appRouter';
import {authenticated} from '../test/authFixtures';
import {announcements, standInRouter} from '../test/nextNavigation';
import {CATCH_ALL_RECORDS} from '../test/renderWithProviders';
import {AREAS} from '../lib/navigation';
import {catchAllPageName} from './[[...slug]]/catchAllPageName';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));

/** A view's first chunk is transformed on demand, which outlasts `waitFor`'s default on a cold cache. */
const LOADING = {timeout: 10_000};

describe('the catch-all page’s first visit', () => {
  // The catch-all is visited once in this file, from a page the App Router serves, so its route
  // table's chunk is still loading when the router commits it.
  it('announces Not Found for an unknown path, the title the table then sets', async () => {
    renderApp('/files', {auth: authenticated('alice'), routers: {files: 'app'}});
    await waitFor(() => expect(document.title).toBe('Files — Data Quarry'), LOADING);

    act(() => standInRouter().push('/nope'));
    await waitFor(() => expect(document.title).toBe('Not Found — Data Quarry'), LOADING);

    expect(announcements(), 'the catch-all titles itself as it mounts').toEqual(['Not Found — Data Quarry']);
  });

  it('names each path as the route table serves it', () => {
    expect(catchAllPageName('/', AREAS)).toBe('');
    expect(catchAllPageName('/nope', AREAS)).toBe('Not Found');
    expect(catchAllPageName('/Files', CATCH_ALL_RECORDS)).toBe('Not Found');
    expect(catchAllPageName('/files', CATCH_ALL_RECORDS)).toBeNull();
    expect(catchAllPageName('/files', AREAS)).toBe('Not Found');
  });
});
