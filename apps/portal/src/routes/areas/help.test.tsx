import {afterEach, beforeEach, describe, it, expect, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderApp} from '../../test/appRouter';
import {authenticated} from '../../test/authFixtures';
import {requests, traverse} from '../../test/nextNavigation';
import {getNotifications} from '../../features/notifications/notifications.service';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));
// The services the pages a contextual link starts from reach: Files and Notifications.
vi.mock('../../features/file-browser/fileBrowser.service', async (importActual) => ({
  ...(await importActual<typeof import('../../features/file-browser/fileBrowser.service')>()),
  ensurePrefixMarker: vi.fn().mockResolvedValue({success: true}),
  listFiles: vi.fn().mockResolvedValue({
    success: true,
    data: {files: [], folders: [{type: 'folder', prefix: 'alice/docs/', name: 'docs'}], isTruncated: false}
  })
}));
vi.mock('../../features/shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn().mockResolvedValue({success: true, data: {version: 1, connections: []}}),
  enqueueSharedSpaceRequest: vi.fn()
}));
vi.mock('../../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

describe('App routing', () => {
  it('renders a protected route through the layout for an authenticated user', async () => {
    renderApp('/help', {auth: authenticated('alice')});
    expect(await screen.findByRole('main')).toBeInTheDocument();
    expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();
  });
});

/**
 * Wait until the page settles on the area's own content or on the catch-all's 404, then fail naming
 * the 404 if that is what rendered: an area page missing from disk falls through to it.
 */
async function servedByItsPage(content: () => HTMLElement | null) {
  const notFound = () => screen.queryByRole('heading', {name: 'Page not found'});
  await waitFor(() => expect(content() ?? notFound()).not.toBeNull());
  expect(notFound()).not.toBeInTheDocument();
  expect(content()).toBeInTheDocument();
}

/**
 * The Help page's own rail, which no other page renders: unlike the section heading, which Files
 * and Notifications render too, it cannot be on screen unless Help is.
 */
const helpRail = () => screen.queryByRole('complementary', {name: 'Guides navigation'});

/** The section the rail marks current, by its button's name. */
function currentSection(): string | null {
  const rail = helpRail();
  if (!rail) return null;
  const current = within(rail)
    .getAllByRole('button')
    .find((button) => button.getAttribute('aria-current') === 'true');
  return current?.textContent ?? null;
}

describe('Help on the App Router', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
    vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('is served by its own page, where the catch-all would render the 404', async () => {
    renderApp('/help', {auth: authenticated('alice'), routers: {help: 'app'}});

    await servedByItsPage(helpRail);
  });

  // A section is a hash on the same path, so the seam writes it natively and Back is a traversal
  // between two entries of one page.
  it('goes Back to the previous section after one is chosen, and Forward to it again', async () => {
    const {user, location} = renderApp('/help', {auth: authenticated('alice'), routers: {help: 'app'}});
    const rail = await screen.findByRole('complementary', {name: 'Guides navigation'});

    await user.click(within(rail).getByRole('button', {name: /Notifications/}));
    await waitFor(() => expect(location().hash).toBe('#notifications'));
    expect(screen.getByRole('heading', {level: 1})).toHaveTextContent('Notifications');

    await traverse(-1);
    await waitFor(() => expect(screen.getByRole('heading', {level: 1})).toHaveTextContent('Files'));
    expect(location().hash).toBe('');
    expect(currentSection()).toMatch(/^Files/);

    await traverse(1);
    await waitFor(() => expect(screen.getByRole('heading', {level: 1})).toHaveTextContent('Notifications'));
    expect(location().hash).toBe('#notifications');
    expect(requests()).toEqual([]);
  });

  // Files is Help's first section, so on that row a lost hash would look the same; the Notifications
  // row is the one that tells the section apart. Both prove Help rendered in place of the page.
  it.each([
    ['/files', () => screen.queryByRole('checkbox', {name: 'Select folder docs'}), '#files', /^Files/],
    ['/notifications', () => screen.queryByText('You’re all caught up'), '#notifications', /^Notifications/]
  ])('opens Help at the section the contextual panel on %s links to', async (from, ownContent, hash, section) => {
    vi.mocked(getNotifications).mockResolvedValue({success: true, data: []});
    const {user, location} = renderApp(from, {
      auth: authenticated('alice'),
      routers: {help: 'app', files: 'app', notifications: 'app'}
    });
    await waitFor(() => expect(ownContent()).not.toBeNull());

    await user.click(screen.getByRole('button', {name: 'Help for this page'}));
    await user.click(await screen.findByRole('link', {name: 'Open the full guide'}));

    await waitFor(() => expect(helpRail()).not.toBeNull());
    expect(currentSection()).toMatch(section);
    expect(location().hash).toBe(hash);
    // The address too: a router push that dropped the hash would leave a reload or a shared link at the first section.
    expect(window.location.hash).toBe(hash);
    expect(ownContent()).not.toBeInTheDocument();
    expect(requests()).toEqual(['/help']);
  });
});
