import {useEffect, useState, type ComponentType, type ReactNode} from 'react';
import {afterEach, beforeEach, describe, expect, it, onTestFinished, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderApp} from '../../test/appRouter';
import {documentLoads, requests} from '../../test/nextNavigation';
import {authenticated, unauthenticated} from '../../test/authFixtures';
import {AuthContext} from '../../features/auth/authContext';
import {AuthProvider, type AuthContextValue} from '../../features/auth';
import {getCurrentAuthUser, startSignOut} from '../../features/auth/auth.service';
import * as fileService from '../../features/file-browser/fileBrowser.service';
import {submitFileOperation} from '../../features/file-browser/fileOps.service';
import {readSharedConnectionsCache} from '../../features/shared-spaces/sharedSpaces.service';
import {getNotifications} from '../../features/notifications/notifications.service';
import {Link} from '../../lib/navigation';
import {disarmLeaveGuard} from '../../lib/leaveGuard';
import type {FileListPage} from '../../types/s3.types';
import {FilesView} from './files';

/**
 * What a page change must leave alone, driven through the REAL chrome and the REAL pages.
 *
 * The signed-in shell holds two session-scoped records — the upload queue and the in-flight file
 * operations — and both are only worth anything if neither a click on a nav tab nor a page that
 * throws remounts the shell. Nothing below the chrome can see that: a test that composes its own
 * layouts cannot catch a `key` somewhere above them, and one did exactly that in production, while
 * each nav-tab click aborted the uploads in progress.
 *
 * Every navigation here is a click on a link the app really renders, and each one waits for the
 * destination before asserting, so a click that failed to change the page cannot pass for one that
 * did. Only the service boundary is mocked. Files is the subject, so the shell's survival lives here.
 */
// The real auth provider, for the tests whose subject is what IT does on sign-out; every other test
// injects a fixed auth value and never reaches the service.
vi.mock('../../features/auth/auth.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../features/auth/auth.service')>()),
  getCurrentAuthUser: vi.fn(),
  startSignOut: vi.fn()
}));
vi.mock('../../features/file-browser/fileBrowser.service', async (importActual) => ({
  ...(await importActual<typeof fileService>()),
  ensurePrefixMarker: vi.fn().mockResolvedValue({success: true}),
  listFiles: vi.fn(),
  getObjectMetadata: vi.fn(),
  getDownloadUrl: vi.fn(),
  folderExists: vi.fn(),
  objectExists: vi.fn(),
  firstFreeName: vi.fn(),
  uploadFile: vi.fn(),
  createFolder: vi.fn(),
  deleteObject: vi.fn(),
  moveObject: vi.fn(),
  copyObject: vi.fn()
}));
vi.mock('../../features/file-browser/fileOps.service', () => ({submitFileOperation: vi.fn()}));
vi.mock('../../features/shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn().mockResolvedValue({success: true, data: {version: 1, connections: []}}),
  enqueueSharedSpaceRequest: vi.fn()
}));
vi.mock('../../features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));
// A signed-in page standing in for any eager page's render defect: it throws wherever the test
// says it does, so one scenario can crash it from its own tab and another can crash it only
// behind a query string that the tab does not carry.
const standIn = vi.hoisted(() => ({throwsAt: (() => true) as (search: string) => boolean}));
vi.mock('../DataQualityPage', async () => {
  const navigation = await import('../../lib/navigation');
  return {
    default: function DataQualityStandIn() {
      const {search} = navigation.useLocation();
      if (standIn.throwsAt(search)) throw new Error('render failed');
      return <p>Data quality stand-in</p>;
    }
  };
});
// Query, standing in for another signed-in page: Monaco and the catalog clients are not this file's
// subject, only that another page renders.
vi.mock('../QueryPage', () => ({
  default: function QueryStandIn() {
    return <h1>Query stand-in</h1>;
  }
}));

const mock = vi.mocked(fileService);
const ok = <T,>(data: T) => ({success: true as const, data});

const page: FileListPage = {
  files: [{type: 'file', key: 'alice/report.csv', name: 'report.csv', size: 10, lastModified: new Date('2026-03-04')}],
  folders: [{type: 'folder', prefix: 'alice/docs/', name: 'docs'}],
  isTruncated: false
};

/** Files, served by its page on disk. */
const renderFiles = (route: string) => renderApp(route, {auth: authenticated('alice')});

type User = ReturnType<typeof renderFiles>['user'];

/**
 * Hold every upload open at 50%, settling it as Cancelled on abort the way the real uploader
 * settles, so an abort shows on the signal and in the row alike.
 *
 * @returns A reader for whether each upload started so far was aborted, in start order.
 */
function holdUploadsOpen(): () => boolean[] {
  const seen: AbortSignal[] = [];
  mock.uploadFile.mockImplementation((({signal, onProgress}: Parameters<typeof fileService.uploadFile>[0]) => {
    if (signal) seen.push(signal);
    onProgress?.(50, 100);
    return new Promise((resolve) => {
      signal?.addEventListener('abort', () =>
        resolve({success: false, error: {message: 'aborted', code: 'Cancelled'}})
      );
    });
  }) as never);
  return () => seen.map((signal) => signal.aborted);
}

/** Start uploads from the Files page, then close the drawer — closing it is not what aborts one. */
async function startUploads(user: User, names = ['up.txt']) {
  await user.click(await screen.findByRole('button', {name: 'Upload'}));
  await user.upload(
    await screen.findByLabelText('Choose files'),
    names.map((name) => new File(['data'], name, {type: 'text/plain'}))
  );
  await screen.findByRole('progressbar', {name: `Uploading ${names[0]}`});
  await user.keyboard('{Escape}');
}

/** A `beforeunload` as the browser raises it, and whether the page asked to stay. */
function unloadIsCancelled(): boolean {
  const event = new Event('beforeunload', {cancelable: true});
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

/** The Files page with the two ways off the signed-in pages beside it. */
function FilesWithPublicLinks() {
  return (
    <>
      <FilesView />
      <Link to="/">To the landing page</Link>
      <Link to="/nope">To nowhere</Link>
    </>
  );
}

/** Files served by {@link FilesWithPublicLinks} in place of its page on disk. */
const FILES_WITH_PUBLIC_LINKS = {
  auth: authenticated('alice'),
  pages: {'(signed-in)/files/page.tsx': FilesWithPublicLinks}
} as const;

/** Come back to Files by its tab, and wait for the listing. */
async function backToFiles(user: User) {
  await user.click(screen.getByRole('link', {name: 'Files'}));
  await screen.findByRole('checkbox', {name: 'Select folder docs'});
}

/** Leave Files for the notifications page by its header link, and come back by the Files tab. */
async function roundTripThroughNotifications(user: User) {
  await user.click(screen.getByRole('link', {name: /^Notifications,/}));
  await screen.findByRole('heading', {name: 'Notifications', level: 1});
  await backToFiles(user);
}

/**
 * The auth state, flipped to signed-out by the Sign out control.
 *
 * The real provider's sign-out moves the document away, which jsdom cannot do, so it never flips the
 * status here. What is under test is what the shell does when the status flips, so the flip is
 * supplied directly.
 */
function SignOutable({children}: {children: ReactNode}) {
  const [signedIn, setSignedIn] = useState(true);
  const value: AuthContextValue = signedIn
    ? {...authenticated('alice'), signOut: async () => setSignedIn(false)}
    : unauthenticated();
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  standIn.throwsAt = () => true;
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  mock.listFiles.mockResolvedValue(ok(page));
  mock.folderExists.mockResolvedValue(ok(true));
  vi.mocked(submitFileOperation).mockResolvedValue({success: true, data: undefined});
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('the signed-in shell outlives the page', () => {
  it('keeps an upload running, and still listed, after leaving Files and coming back', async () => {
    const aborted = holdUploadsOpen();
    const {user} = renderFiles('/files');
    await startUploads(user);

    await roundTripThroughNotifications(user);
    await user.click(screen.getByRole('button', {name: 'Upload'}));

    expect(aborted()).toEqual([false]);
    expect(await screen.findByRole('progressbar', {name: 'Uploading up.txt'})).toHaveAttribute('aria-valuenow', '50');
  });

  it('keeps an in-flight folder operation on screen, and its space gated, across a route change', async () => {
    const {user} = renderFiles('/files');
    await user.click(await screen.findByRole('checkbox', {name: 'Select folder docs'}));
    await user.click(screen.getByRole('button', {name: 'Delete selected items'}));
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await screen.findByRole('region', {name: 'File operations in progress'});

    await roundTripThroughNotifications(user);
    await user.click(screen.getByRole('checkbox', {name: 'Select folder docs'}));

    const region = screen.getByRole('region', {name: 'File operations in progress'});
    expect(within(region).getByText('Deleting docs')).toBeInTheDocument();
    const move = screen.getByRole('button', {name: 'Move selected items'});
    await waitFor(() => expect(move).toHaveAttribute('aria-disabled', 'true'));
    // The reason, so a gate closed for any other cause cannot stand in for this one.
    expect(move.getAttribute('title')).toMatch(/still running here/);
  });

  // A public page renders outside the gate, so following a link to the landing page ends the shell.
  it('ends on the landing page: a link to it aborts the upload and drops the shell', async () => {
    const aborted = holdUploadsOpen();
    const {user} = renderApp('/files', FILES_WITH_PUBLIC_LINKS);
    await startUploads(user);

    await user.click(screen.getByRole('link', {name: 'To the landing page'}));

    await waitFor(() => expect(aborted()).toEqual([true]));
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Upload'})).not.toBeInTheDocument();
  });

  // No page serves an unknown path, so Next loads the document there rather than rendering it: the
  // shell stays until the document goes, and the unload guard asks first while an upload runs.
  it('leaves the document for a link to nowhere, asking first while an upload runs', async () => {
    const aborted = holdUploadsOpen();
    const {user} = renderApp('/files', FILES_WITH_PUBLIC_LINKS);
    await startUploads(user);

    await user.click(screen.getByRole('link', {name: 'To nowhere'}));

    expect(documentLoads()).toEqual(['/nope']);
    expect(aborted()).toEqual([false]);
    expect(unloadIsCancelled()).toBe(true);
  });

  // The other side of the same claim: a fix that kept the providers alive by hoisting them above
  // the auth gate would pass every test above, and leave a signed-out tab uploading.
  it('ends with the session: signing out aborts the upload and drops the operations', async () => {
    const aborted = holdUploadsOpen();
    const {user} = renderApp('/files', {auth: SignOutable});
    await startUploads(user);
    await user.click(screen.getByRole('checkbox', {name: 'Select folder docs'}));
    await user.click(screen.getByRole('button', {name: 'Delete selected items'}));
    await user.click(await screen.findByRole('button', {name: 'Delete'}));
    await screen.findByRole('region', {name: 'File operations in progress'});

    await user.click(screen.getByRole('button', {name: 'Account: alice'}));
    await user.click(await screen.findByRole('menuitem', {name: 'Sign out'}));

    await waitFor(() => expect(aborted()).toEqual([true]));
    expect(screen.queryByRole('region', {name: 'File operations in progress'})).not.toBeInTheDocument();
  });
});

describe('a signed-in page that throws', () => {
  // Caught ABOVE the shell, a page's throw would swap the shell for the fallback, and the
  // providers' unmount would abort the uploads exactly as a remount did. The panel's one button
  // reloads, which would cancel the uploads the shell just kept — so the panel says so. Four
  // files, because three run at once: the fourth is still queued, and a reload loses it too.
  it('is caught inside the shell, keeps the uploads going, and says a reload would cancel them', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    onTestFinished(() => consoleError.mockRestore());
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    onTestFinished(() => consoleWarn.mockRestore());
    const aborted = holdUploadsOpen();
    const {user} = renderFiles('/files');
    await startUploads(user, ['a.txt', 'b.txt', 'c.txt', 'd.txt']);

    await user.click(screen.getByRole('link', {name: 'Data quality'}));

    const panel = await screen.findByRole('alert');
    const notice = screen.getByText(
      'Reloading cancels the 4 uploads still in progress — to keep them, open another page instead.'
    );
    // Outside the alert, which re-announces its whole content whenever any of it changes — and
    // this line changes each time an upload finishes.
    expect(panel).not.toContainElement(notice);
    expect(aborted()).toEqual([false, false, false]);
  });

  // The path is the same, so a reset keyed on the path alone would never fire, and the page's own
  // tab — the first thing a user clicks — would leave the fallback where it was.
  it('recovers when its own tab drops the query string that broke it', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    onTestFinished(() => consoleError.mockRestore());
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    onTestFinished(() => consoleWarn.mockRestore());
    standIn.throwsAt = (search) => search.includes('broken');
    const {user} = renderFiles('/data-quality?broken=1');
    await screen.findByRole('alert');
    // Nothing is uploading, so a reload costs nothing and the panel does not say it would.
    expect(screen.queryByText(/Reloading cancels/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('link', {name: 'Data quality'}));

    expect(await screen.findByText('Data quality stand-in')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('an unfinished upload asks before the document goes', () => {
  // A navigation to or from an App Router page becomes a document load after a deploy or an
  // outage, and a document load ends the shell; so does a reload or a closed tab. While anything
  // would be lost, the browser is asked to confirm.
  it('asks while an upload runs, and not once every upload has settled', async () => {
    // Done, failed and cancelled: every way an upload ends.
    mock.uploadFile.mockImplementation((async ({key}: {key: string}) =>
      key.endsWith('good.txt')
        ? {success: true, data: undefined}
        : key.endsWith('bad.txt')
          ? {success: false, error: {message: 'refused', code: 'AccessDenied'}}
          : {success: false, error: {message: 'cancelled', code: 'Cancelled'}}) as never);
    const {user} = renderFiles('/files');
    await user.click(await screen.findByRole('button', {name: 'Upload'}));
    await user.upload(
      await screen.findByLabelText('Choose files'),
      ['good.txt', 'bad.txt', 'gone.txt'].map((name) => new File(['data'], name, {type: 'text/plain'}))
    );
    await waitFor(() => expect(mock.uploadFile).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument());
    await user.keyboard('{Escape}');

    expect(unloadIsCancelled()).toBe(false);

    holdUploadsOpen();
    await startUploads(user);

    expect(unloadIsCancelled()).toBe(true);
  });

  // A download is a navigation to the presigned URL, and Chrome raises `beforeunload` inside its
  // click before it knows the response is an attachment; asked there, Stay cancelled the download.
  it('lets a download go without asking while an upload runs', async () => {
    holdUploadsOpen();
    mock.getDownloadUrl.mockResolvedValue(
      ok({url: 'https://user-space.s3.amazonaws.com/alice/report.csv?sig=1'}) as never
    );
    const asked: boolean[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      if (this.href.startsWith('https://user-space.')) asked.push(unloadIsCancelled());
    });
    onTestFinished(() => click.mockRestore());
    const {user} = renderFiles('/files');
    await startUploads(user);

    await user.dblClick(screen.getByText('report.csv'));

    await waitFor(() => expect(asked).toEqual([false]));
    expect(unloadIsCancelled()).toBe(true);
  });

  it('registers no unload listener on a page without the shell', async () => {
    const added = vi.spyOn(window, 'addEventListener');
    onTestFinished(() => added.mockRestore());
    renderFiles('/nope');
    await screen.findByRole('heading', {name: 'Page not found'});

    expect(added.mock.calls.filter(([type]) => type === 'beforeunload')).toEqual([]);
  });

  // Signing out is deliberate and asks nothing, as it always has. The sign-out moves the document to
  // the provider's logout page while the shell is still mounted, so the guard would still be armed
  // when the browser asks; the provider disarms it first, in the same task.
  it('lets a sign-out go without asking while an upload runs', async () => {
    holdUploadsOpen();
    vi.mocked(getCurrentAuthUser).mockResolvedValue({success: true, data: {username: 'alice'}});
    const asked: boolean[] = [];
    // Where the real service moves the document: what the browser would ask is read at that moment.
    vi.mocked(startSignOut).mockImplementation(async () => {
      asked.push(unloadIsCancelled());
      return {success: true, data: undefined};
    });
    const {user} = renderApp('/files', {auth: AuthProvider});
    await startUploads(user);

    await user.click(screen.getByRole('button', {name: 'Account: alice'}));
    await user.click(await screen.findByRole('menuitem', {name: 'Sign out'}));

    await waitFor(() => expect(asked).toEqual([false]));
  });

  it('asks again once a sign-out fails and the uploads carry on', async () => {
    const aborted = holdUploadsOpen();
    vi.mocked(getCurrentAuthUser).mockResolvedValue({success: true, data: {username: 'alice'}});
    vi.mocked(startSignOut).mockResolvedValue({success: false, error: {message: 'offline', code: 'NetworkError'}});
    const {user} = renderApp('/files', {auth: AuthProvider});
    await startUploads(user);

    await user.click(screen.getByRole('button', {name: 'Account: alice'}));
    await user.click(await screen.findByRole('menuitem', {name: 'Sign out'}));
    await waitFor(() => expect(startSignOut).toHaveBeenCalledOnce());

    await waitFor(() => expect(unloadIsCancelled()).toBe(true));
    expect(aborted()).toEqual([false]);
  });

  it('asks in a shell that mounts after an earlier sign-out disarmed the guard', async () => {
    disarmLeaveGuard();
    holdUploadsOpen();
    const {user} = renderFiles('/files');

    await startUploads(user);

    expect(unloadIsCancelled()).toBe(true);
  });
});

/**
 * Wait until the page settles on the area's own content or on the not-found page, then fail naming
 * the not-found page if that is what rendered: Next renders it for an area page missing from disk.
 */
async function servedByItsPage(content: () => HTMLElement | null) {
  const notFound = () => screen.queryByRole('heading', {name: 'Page not found'});
  await waitFor(() => expect(content() ?? notFound()).not.toBeNull());
  expect(notFound()).not.toBeInTheDocument();
  expect(content()).toBeInTheDocument();
}

/** Mounts of the Files page, counted by the pass-through below. */
let filesPageMounts = 0;

/**
 * The page files on disk. The Files page is read from here rather than imported, so that with it
 * deleted only the test that wraps it fails, and the rest of the file still fails on the 404.
 */
const DISK_PAGES = import.meta.glob<{default: ComponentType}>('../../app/**/page.tsx', {eager: true});

/** The Files page as it is on disk, counting each mount. */
function CountingFilesPage() {
  useEffect(() => {
    filesPageMounts += 1;
  }, []);
  const FilesPage = DISK_PAGES['../../app/(signed-in)/files/page.tsx'].default;
  return <FilesPage />;
}

describe('Files on the App Router', () => {
  // The page as it stands on disk: with it deleted, Next renders the not-found page at its path.
  it('is served by its own page, where Next would render the not-found page without it', async () => {
    renderApp('/files', {auth: authenticated('alice')});

    await servedByItsPage(() => screen.queryByRole('checkbox', {name: 'Select folder docs'}));
  });

  // Leaving Files for another path goes through Next's router, which renders a different page, and
  // the shell above both must not notice.
  it('keeps an upload running across a round trip to another page through Next’s router', async () => {
    const aborted = holdUploadsOpen();
    const {user} = renderApp('/files', {auth: authenticated('alice')});
    await startUploads(user);

    await user.click(screen.getByRole('link', {name: 'Query'}));
    await screen.findByRole('heading', {name: 'Query stand-in'});
    await backToFiles(user);
    await user.click(screen.getByRole('button', {name: 'Upload'}));

    expect(requests()).toEqual(['/query', '/files']);
    expect(aborted()).toEqual([false]);
    expect(await screen.findByRole('progressbar', {name: 'Uploading up.txt'})).toHaveAttribute('aria-valuenow', '50');
  });

  it('opens the folder a notification links to', async () => {
    vi.mocked(getNotifications).mockResolvedValue(
      ok([
        {
          id: 'n1',
          message: 'Your results are in docs',
          read: false,
          timestamp: '2026-11-14T00:00:00Z',
          link: '/files?prefix=alice/docs/'
        }
      ])
    );
    onTestFinished(() => {
      vi.mocked(getNotifications).mockResolvedValue(ok([]));
    });
    const {user} = renderApp('/notifications', {auth: authenticated('alice')});

    await user.click(await screen.findByRole('link', {name: 'Your results are in docs'}));

    const breadcrumb = within(await screen.findByRole('navigation', {name: 'breadcrumb'}));
    expect(await breadcrumb.findByText('docs')).toBeInTheDocument();
    expect(mock.listFiles).toHaveBeenCalledWith('user-space', 'alice/docs/', undefined, expect.anything());
    expect(requests()).toEqual(['/files?prefix=alice/docs/']);
  });
});

describe('a space switch on Files', () => {
  beforeEach(() => {
    filesPageMounts = 0;
    vi.mocked(readSharedConnectionsCache).mockResolvedValue(
      ok({version: 1, connections: [{name: 'marketing_data', role: 'member', status: 'active'}]})
    );
  });

  afterEach(() => {
    vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}));
  });

  // Only the search changes, so the seam writes the entry itself: Next fetches nothing, and the page
  // stays mounted while the file browser inside it remounts on the new space, by design.
  it('goes through neither router call, and does not remount the page', async () => {
    const {user} = renderApp('/files', {
      auth: authenticated('alice'),
      pages: {'(signed-in)/files/page.tsx': CountingFilesPage}
    });
    await screen.findByRole('checkbox', {name: 'Select folder docs'});

    const spaces = (await screen.findAllByRole('list', {name: 'Spaces'}))[0];
    await user.click(await within(spaces).findByRole('button', {name: /marketing_data/}));

    await waitFor(() => expect(window.location.search).toBe('?space=marketing_data'));
    const breadcrumb = within(await screen.findByRole('navigation', {name: 'breadcrumb'}));
    expect(await breadcrumb.findByText('marketing_data')).toBeInTheDocument();
    expect(requests()).toEqual([]);
    expect(filesPageMounts).toBe(1);
  });
});
