import {useState, type ReactNode} from 'react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {App} from './App';
import {renderWithProviders} from './test/renderWithProviders';
import {authenticated, unauthenticated} from './test/authFixtures';
import {AuthContext} from './features/auth/authContext';
import type {AuthContextValue} from './features/auth';
import * as fileService from './features/file-browser/fileBrowser.service';
import {submitFileOperation} from './features/file-browser/fileOps.service';
import type {FileListPage} from './types/s3.types';

/**
 * What a route change must leave alone, driven through the REAL route table.
 *
 * The signed-in shell holds two session-scoped records — the upload queue and the in-flight file
 * operations — and both are only worth anything if neither a click on a nav tab nor a page that
 * throws remounts the shell. Nothing below the route table can see that: a test that composes its
 * own layouts cannot catch a `key` somewhere above them, and one did exactly that in production,
 * while each nav-tab click aborted the uploads in progress.
 *
 * Every navigation here is a click on a link the header really renders, and each one waits for
 * the destination before asserting, so a click that failed to change the route cannot pass for
 * one that did. Only the service boundary is mocked.
 */
vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));
vi.mock('./features/file-browser/fileBrowser.service', async (importActual) => ({
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
vi.mock('./features/file-browser/fileOps.service', () => ({submitFileOperation: vi.fn()}));
vi.mock('./features/shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn().mockResolvedValue({success: true, data: {version: 1, connections: []}}),
  enqueueSharedSpaceRequest: vi.fn()
}));
vi.mock('./features/notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));
// A signed-in page standing in for any eager page's render defect: it throws wherever the test
// says it does, so one scenario can crash it from its own tab and another can crash it only
// behind a query string that the tab does not carry.
const standIn = vi.hoisted(() => ({throwsAt: (() => true) as (search: string) => boolean}));
vi.mock('./routes/DataQualityPage', async () => {
  const {useLocation} = await import('react-router');
  return {
    default: function DataQualityStandIn() {
      const {search} = useLocation();
      if (standIn.throwsAt(search)) throw new Error('render failed');
      return <p>Data quality stand-in</p>;
    }
  };
});

const mock = vi.mocked(fileService);
const ok = <T,>(data: T) => ({success: true as const, data});

const page: FileListPage = {
  files: [{type: 'file', key: 'alice/report.csv', name: 'report.csv', size: 10, lastModified: new Date('2026-03-04')}],
  folders: [{type: 'folder', prefix: 'alice/docs/', name: 'docs'}],
  isTruncated: false
};

const renderApp = (route: string) => renderWithProviders(<App />, {route, auth: authenticated('alice')});

type User = ReturnType<typeof renderApp>['user'];

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
 * The real provider flips on an Amplify Hub event this suite has no Amplify to raise. What is
 * under test is what the shell does when the status flips, so the flip is supplied directly.
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
    const {user} = renderApp('/files');
    await startUploads(user);

    await roundTripThroughNotifications(user);
    await user.click(screen.getByRole('button', {name: 'Upload'}));

    expect(aborted()).toEqual([false]);
    expect(await screen.findByRole('progressbar', {name: 'Uploading up.txt'})).toHaveAttribute('aria-valuenow', '50');
  });

  it('keeps an in-flight folder operation on screen, and its space gated, across a route change', async () => {
    const {user} = renderApp('/files');
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

  // The other side of the same claim: a fix that kept the providers alive by hoisting them above
  // the auth gate would pass every test above, and leave a signed-out tab uploading.
  it('ends with the session: signing out aborts the upload and drops the operations', async () => {
    const aborted = holdUploadsOpen();
    const {user} = renderWithProviders(
      <SignOutable>
        <App />
      </SignOutable>,
      {route: '/files', auth: null}
    );
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
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const aborted = holdUploadsOpen();
    const {user} = renderApp('/files');
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
    consoleError.mockRestore();
    consoleWarn.mockRestore();
  });

  // The path is the same, so a reset keyed on the path alone would never fire, and the page's own
  // tab — the first thing a user clicks — would leave the fallback where it was.
  it('recovers when its own tab drops the query string that broke it', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    standIn.throwsAt = (search) => search.includes('broken');
    const {user} = renderApp('/data-quality?broken=1');
    await screen.findByRole('alert');
    // Nothing is uploading, so a reload costs nothing and the panel does not say it would.
    expect(screen.queryByText(/Reloading cancels/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('link', {name: 'Data quality'}));

    expect(await screen.findByText('Data quality stand-in')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    consoleError.mockRestore();
    consoleWarn.mockRestore();
  });
});
