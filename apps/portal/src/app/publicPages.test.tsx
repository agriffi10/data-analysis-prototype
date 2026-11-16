import {screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {renderApp} from '../test/appRouter';
import {authenticated, unauthenticated} from '../test/authFixtures';
import {documentLoads, traverse} from '../test/nextNavigation';
import {AuthProvider} from '../features/auth';
import {getCurrentAuthUser} from '../features/auth/auth.service';
import {Link, useLocation, useNavigationType} from '../lib/navigation';
import {peekReturnPath, setReturnPath} from '../lib/returnPath';

/**
 * The two public pages the App Router serves outside the sign-in gate: the landing page at `/` and
 * the not-found page at every address no page serves, each read from disk through `renderApp`.
 */

vi.mock('../features/auth/auth.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../features/auth/auth.service')>()),
  getCurrentAuthUser: vi.fn()
}));
vi.mock('../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));
// The real gate and shell, counted as they render, since an empty shell draws nothing of its own.
const gate = vi.hoisted(() => ({renders: 0}));
vi.mock('../components/ProtectedLayout', async (importOriginal) => {
  const original = await importOriginal<typeof import('../components/ProtectedLayout')>();
  return {
    ...original,
    ProtectedLayout: (props: Parameters<typeof original.ProtectedLayout>[0]) => {
      gate.renders += 1;
      return <original.ProtectedLayout {...props} />;
    }
  };
});

/** A stand-in Files page that says where it is and how it was reached. */
function FilesReadout() {
  const {pathname, search} = useLocation();
  return (
    <>
      <h1>Files stand-in</h1>
      <output aria-label="arrived">{`${useNavigationType()} ${pathname}${search}`}</output>
    </>
  );
}

const FILES_STAND_IN = {'(signed-in)/files/page.tsx': FilesReadout};

/** Whether the sign-in gate and the shell rendered; the last test shows it does on a signed-in page. */
const shellMounted = () => gate.renders > 0;

beforeEach(() => {
  sessionStorage.clear();
  gate.renders = 0;
});
afterEach(() => vi.restoreAllMocks());

describe('the landing page', () => {
  it('offers sign-in and sign-up at / to a signed-out visitor, without the shell', async () => {
    renderApp('/', {auth: unauthenticated()});

    expect((await screen.findAllByRole('button', {name: /^sign in$/i})).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', {name: /create account/i}).length).toBeGreaterThan(0);
    expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();
    expect(shellMounted()).toBe(false);
  });

  // The session routes send a failed or cancelled sign-in back here with this signal, which the auth
  // provider reads; the landing page is where it shows.
  it('says a sign-in failed when the session routes send it back with ?signin=failed', async () => {
    vi.mocked(getCurrentAuthUser).mockResolvedValue({success: false, error: {message: '', code: 'SessionExpired'}});

    renderApp('/?signin=failed', {auth: AuthProvider});

    expect(await screen.findByText('Sign-in failed or was cancelled.')).toBeInTheDocument();
  });

  it('sends a user who has just signed in on to the saved return path, by a replace, and forgets it', async () => {
    setReturnPath('/files?space=finance');

    renderApp('/', {auth: authenticated('alice'), pages: FILES_STAND_IN});

    expect(await screen.findByLabelText('arrived')).toHaveTextContent('REPLACE /files?space=finance');
    expect(peekReturnPath()).toBeNull();
  });

  it('offers a signed-in user with nothing saved the first enabled destination, and goes there', async () => {
    const {user, location} = renderApp('/', {auth: authenticated('alice'), pages: FILES_STAND_IN});

    await user.click((await screen.findAllByRole('button', {name: /go to files/i}))[0]);

    expect(await screen.findByRole('heading', {name: 'Files stand-in'})).toBeInTheDocument();
    expect(location().pathname).toBe('/files');
  });
});

describe('the not-found page', () => {
  it.each([
    ['signed out', unauthenticated()],
    ['signed in', authenticated('alice')]
  ])('renders at an address no page serves, %s, without the shell', async (_status, auth) => {
    renderApp('/nope', {auth});

    expect(await screen.findByRole('heading', {name: 'Page not found'})).toBeInTheDocument();
    expect(shellMounted()).toBe(false);
  });

  // Matched case-sensitively, as Next routes: a gate that folded case would call the path signed in
  // while Next served the not-found page inside the shell.
  it('serves /Files as the not-found page to a signed-in user, without the shell', async () => {
    renderApp('/Files', {auth: authenticated('alice')});

    expect(await screen.findByRole('heading', {name: 'Page not found'})).toBeInTheDocument();
    expect(shellMounted()).toBe(false);
  });

  // Outside the gate too: a gate that claimed the path would send a signed-out user to `/`.
  it('serves /Files as the not-found page to a signed-out user, with no redirect', async () => {
    const {location} = renderApp('/Files', {auth: unauthenticated()});

    expect(await screen.findByRole('heading', {name: 'Page not found'})).toBeInTheDocument();
    expect(location().pathname).toBe('/Files');
  });

  // Matched decoded: `/fil%65s` is Files to the gate, so a signed-out user goes to `/` rather than
  // seeing anything at that address outside the gate.
  it('claims a percent-encoded spelling of an area’s path for the gate', async () => {
    const {location} = renderApp('/fil%65s', {auth: unauthenticated()});

    await waitFor(() => expect(location().pathname).toBe('/'));
  });

  // Written natively, a move between the two public pages would leave the not-found page on screen
  // under `/`, since neither changes the page Next renders without its router. Back onto the
  // not-found page is a document load, as every navigation to a path no page serves is.
  it('links to the landing page, and Back loads the not-found page’s document again', async () => {
    const {user} = renderApp('/nope', {auth: unauthenticated()});

    await user.click(await screen.findByRole('link', {name: 'Back to home'}));
    expect((await screen.findAllByRole('button', {name: /^sign in$/i})).length).toBeGreaterThan(0);
    expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();

    await traverse(-1);

    expect(documentLoads()).toEqual(['/nope']);
  });

  it('is left for a signed-in page, inside the shell, by a link from the landing page', async () => {
    const {user} = renderApp('/nope', {
      auth: authenticated('alice'),
      pages: {...FILES_STAND_IN, 'page.tsx': () => <Link to="/files">To files</Link>}
    });
    await user.click(await screen.findByRole('link', {name: 'Back to home'}));
    expect(shellMounted()).toBe(false);

    await user.click(await screen.findByRole('link', {name: 'To files'}));

    expect(await screen.findByRole('heading', {name: 'Files stand-in'})).toBeInTheDocument();
    await waitFor(() => expect(shellMounted()).toBe(true));
  });
});
