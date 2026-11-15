import {act, screen, waitFor} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import {renderApp} from '../test/appRouter';
import {authenticated} from '../test/authFixtures';
import {announcements, standInRouter} from '../test/nextNavigation';
import {getNotifications} from '../features/notifications/notifications.service';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));
vi.mock('../features/notifications/notifications.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../features/notifications/notifications.service')>()),
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []})
}));

/** A view's first chunk is transformed on demand, which outlasts `waitFor`'s default on a cold cache. */
const LOADING = {timeout: 10_000};

const UNREAD = [0, 1, 2].map((i) => ({
  id: `n${i}`,
  message: `m${i}`,
  read: false,
  timestamp: '2026-11-10T00:00:00.000Z'
}));

// What a first visit announces is the page's name, because the commit that mounts the page comes
// before its view: a title the view derives from state is read at the next navigation, never the
// page left. Each page is visited once in this file, so its view's chunk is still loading.
describe('a first visit to a page whose view’s title depends on state', () => {
  it('announces Notifications by its name while the bell already counts three unread', async () => {
    vi.mocked(getNotifications).mockResolvedValue({success: true, data: UNREAD});
    renderApp('/files', {auth: authenticated('alice'), routers: {notifications: 'app'}});
    await screen.findByRole('link', {name: /3 unread/}, LOADING);

    act(() => standInRouter().push('/notifications'));
    await waitFor(() => expect(document.title).toBe('Notifications (3) — Data Quarry'), LOADING);

    expect(announcements()).toEqual(['Notifications — Data Quarry']);
  });

  it('announces Query by its name when its flag is off', async () => {
    renderApp('/files', {auth: authenticated('alice'), routers: {query: 'app'}, featureFlags: {query: false}});
    await waitFor(() => expect(document.title).toBe('Files — Data Quarry'), LOADING);

    act(() => standInRouter().push('/query'));
    await waitFor(() => expect(document.title).toBe('Query unavailable — Data Quarry'), LOADING);

    expect(announcements()).toEqual(['Query — Data Quarry']);
  });
});
