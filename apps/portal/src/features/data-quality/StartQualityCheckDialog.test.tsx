import {beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render, screen, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authValue} from '../../test/authFixtures';
import {AuthContext} from '../auth/authContext';
import {StartQualityCheckDialog} from './StartQualityCheckDialog';
import {CHECK_AT_ROOT_REFUSAL} from './dataQuality.format';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {COMPONENT_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import type {FileSpaceTarget} from '../file-browser';
import type {FileListPage} from '../../types/s3.types';
import type {ReactElement} from 'react';
import * as fileBrowserService from '../file-browser/fileBrowser.service';

// ─── from StartQualityCheckDialog.test.tsx ───
vi.mock('../file-browser/fileBrowser.service', async (importActual) => ({
  ...(await importActual<typeof fileBrowserService>()),
  listFiles: vi.fn()
}));

describe('StartQualityCheckDialog', () => {
  // Integration style (react.md §21): the real dialog driving the real DestinationPicker and
  // the real useFileBrowser, with only the S3 listing boundary mocked.

  const mockList = vi.mocked(fileBrowserService.listFiles);

  const personal: FileSpaceTarget = {
    id: 'personal',
    bucket: 'user-space',
    rootPrefix: 'alice/',
    kind: 'personal',
    label: 'alice'
  };
  const shared: FileSpaceTarget = {
    id: 'team-data',
    bucket: 'shared-space',
    rootPrefix: 'team-data/',
    kind: 'shared',
    label: 'team-data'
  };

  const page = (over: Partial<FileListPage> = {}): FileListPage => ({
    files: [],
    folders: [],
    isTruncated: false,
    ...over
  });
  const listing = (data: FileListPage) => mockList.mockResolvedValue({success: true, data});

  function renderDialog(props?: Partial<React.ComponentProps<typeof StartQualityCheckDialog>>) {
    const onStart = vi.fn();
    const onCancel = vi.fn();
    const result = renderWithProviders(
      <StartQualityCheckDialog
        spaces={[personal]}
        onStart={onStart}
        onCancel={onCancel}
        {...props}
      />
    );
    return {...result, onStart, onCancel};
  }

  beforeEach(() => {
    vi.clearAllMocks();
    listing(page());
  });

  describe('StartQualityCheckDialog', () => {
    it('carries the read-only reassurance and the background promise', async () => {
      // This is the one place a user decides whether to point a background job at their data.
      // Same promise, same words as the Files-browser confirm (SPEC-113 FR-002).
      renderDialog();
      const dialog = await screen.findByRole('dialog', {name: 'Start a quality check'});
      expect(dialog).toHaveTextContent(/only reads/i);
      expect(dialog).toHaveTextContent(/nothing is modified, moved, or deleted/i);
      expect(dialog).toHaveTextContent(/notification when it finishes/i);
    });

    it('omits the space selector when there is only one space', async () => {
      renderDialog();
      await screen.findByRole('dialog');
      expect(screen.queryByLabelText('Space')).not.toBeInTheDocument();
    });

    it('focuses the space selector when there is one to focus', async () => {
      // Modal defers initial focus to the consumer, and this dialog has no text field to
      // inherit it (the SaveResultsDialog precedent focuses its filename input).
      renderDialog({spaces: [personal, shared]});
      await waitFor(() => expect(screen.getByLabelText('Space')).toHaveFocus());
    });

    it('renders nothing when there are no usable spaces', () => {
      // Only reachable with the bucket env var unset — a personal space always exists.
      const {container} = renderDialog({spaces: []});
      expect(container).toBeEmptyDOMElement();
    });

    it('refuses the space root as a folder target, in the words the user needs', async () => {
      // A check reads its folder recursively, so one at the root counts the portal's own
      // query results and shared tables as the user's data — and SUCCEEDS while doing it.
      // The server refuses it; this is the half that stops a user reaching the refusal.
      listing(page({folders: [{type: 'folder', prefix: 'alice/sales/', name: 'sales'}]}));
      const {onStart} = renderDialog();

      const confirm = await screen.findByRole('button', {name: 'Check this folder'});
      expect(confirm).toBeDisabled();
      // Literals, not just the imported constant. Asserting `getByText(CONSTANT)` proves the
      // sentence is RENDERED and nothing about what it says — gutting the constant to
      // "Not allowed." keeps such a test green, which is the opposite of this test's name.
      const shown = screen.getByText(CHECK_AT_ROOT_REFUSAL);
      expect(shown).toHaveTextContent('top of a space');
      expect(shown).toHaveTextContent(/open the folder|pick a single file/i);
      expect(onStart).not.toHaveBeenCalled();
    });

    it('still takes a folder BELOW the root', async () => {
      // The refusal is about the root, not about folder targets — without this the previous
      // test would pass just as well over a picker that could never confirm anything.
      listing(page({folders: [{type: 'folder', prefix: 'alice/sales/', name: 'sales'}]}));
      const {user, onStart} = renderDialog();

      await user.click(await screen.findByRole('button', {name: 'Open folder sales'}));
      const confirm = await screen.findByRole('button', {name: 'Check this folder'});
      await waitFor(() => expect(confirm).toBeEnabled());
      await user.click(confirm);
      expect(onStart).toHaveBeenCalledWith({
        space: {kind: 'personal', bucket: 'user-space', prefix: 'alice/'},
        location: 'alice/sales/'
      });
    });

    it('enqueues exactly the location it last displayed', async () => {
      listing(
        page({files: [{type: 'file', key: 'alice/report.csv', name: 'report.csv', size: 1, lastModified: new Date(0)}]})
      );
      const {user, onStart} = renderDialog();

      await user.click(await screen.findByRole('button', {name: 'Select file report.csv'}));
      // The target line is the dialog's claim about what is about to happen; the enqueued
      // location is what actually happens. A drift between them is a silent wrong-target.
      // Read by id: the line is deliberately two spans (head-truncation), so no single text
      // node carries the whole location.
      const shown = document.getElementById('dq-start-target')?.textContent;
      expect(shown).toBe('alice/report.csv');
      await user.click(screen.getByRole('button', {name: 'Check this file'}));

      expect(onStart).toHaveBeenCalledWith(expect.objectContaining({location: shown}));
    });

    it('identifies a shared space by its own root prefix, not the browsed folder', async () => {
      listing(page({folders: [{type: 'folder', prefix: 'team-data/raw/', name: 'raw'}]}));
      const {user, onStart} = renderDialog({spaces: [shared]});

      await user.click(await screen.findByRole('button', {name: /open folder raw/i}));
      await user.click(await screen.findByRole('button', {name: 'Check this folder'}));

      expect(onStart).toHaveBeenCalledWith({
        space: {kind: 'shared', bucket: 'shared-space', prefix: 'team-data/'},
        location: 'team-data/raw/'
      });
    });

    it('locks the dialog while a request is in flight', async () => {
      listing(page({folders: [{type: 'folder', prefix: 'alice/sales/', name: 'sales'}]}));
      renderDialog({isPending: true});

      await screen.findByRole('button', {name: /starting…/i});
      expect(screen.getByRole('button', {name: /starting…/i})).toBeDisabled();
      // Not dismissible mid-flight: no orphaned send.
      expect(screen.getByRole('button', {name: /cancel/i})).toBeDisabled();
    });
  });
});

// ─── from StartQualityCheckDialog.a11y.test.tsx ───

describe('StartQualityCheckDialog.a11y', () => {
  // Bespoke tree, kept deliberately (SPEC-154 FR-007): `expectNoA11yViolations` takes a
  // COMPOSED ELEMENT and renders it itself, so there is no `renderWithProviders` result to
  // hand it. The client is bespoke too, and that is load-bearing: the pattern below warms
  // the cache in one render and reuses it in the next, which `createTestQueryClient`'s
  // `gcTime: 0` would defeat — axe would then inspect a loading state and pass vacuously.
  const mockList = vi.mocked(fileBrowserService.listFiles);

  const spaces: FileSpaceTarget[] = [
    {id: 'personal', bucket: 'user-space', rootPrefix: 'alice/', kind: 'personal', label: 'alice'},
    {id: 'team-data', bucket: 'shared-space', rootPrefix: 'team-data/', kind: 'shared', label: 'team-data'}
  ];

  // COMPONENT_AXE_OPTIONS: the dialog renders outside any landmark, so the `region` rule is
  // off (SPEC-045). A SHARED client with default gcTime, so the listing warmed by the first
  // render is already resolved for the render inside expectNoA11yViolations — otherwise axe
  // would inspect the picker's "Loading…" line, not its rows (the DataQualityPage.a11y
  // precedent).
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});

  // The auth provider is not decoration: `DestinationPicker` reads the `query` flag
  // (SPEC-173 FR-008 — a destination the user cannot see is not a destination), and the
  // flag chain resolves the signed-in user.
  function dialog(): ReactElement {
    return (
      <AuthContext.Provider value={authValue()}>
        <QueryClientProvider client={client}>
          <StartQualityCheckDialog
            spaces={spaces}
            onStart={() => {}}
            onCancel={() => {}}
          />
        </QueryClientProvider>
      </AuthContext.Provider>
    );
  }

  /** Render, wait for the listing, unmount — then hand the same tree to axe. */
  async function renderThenAxe(): Promise<void> {
    const ui = dialog();
    render(ui);
    expect(await screen.findByRole('button', {name: 'Select file report.csv'})).toBeInTheDocument();
    cleanup();
    await expectNoA11yViolations(ui, COMPONENT_AXE_OPTIONS);
  }

  beforeEach(() => {
    vi.clearAllMocks();
    client.clear();
    // A folder AND a file, so the selectable file row (aria-pressed on a button) is in the
    // tree axe sees — the row this spec exists to check.
    mockList.mockResolvedValue({
      success: true,
      data: {
        folders: [{type: 'folder', prefix: 'alice/sales/', name: 'sales'}],
        files: [{type: 'file', key: 'alice/report.csv', name: 'report.csv', size: 1, lastModified: new Date(0)}],
        isTruncated: false
      }
    });
  });

  describe('StartQualityCheckDialog a11y', () => {
    it('has no axe violations', async () => {
      await renderThenAxe();
    });

    it('has no axe violations at a phone width', async () => {
      Object.defineProperty(window, 'innerWidth', {value: 400, writable: true, configurable: true});
      try {
        await renderThenAxe();
      } finally {
        Object.defineProperty(window, 'innerWidth', {value: 1024, writable: true, configurable: true});
      }
    });
  });
});
