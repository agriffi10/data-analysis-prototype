import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, cleanup} from '@testing-library/react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import type {ReactElement} from 'react';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {StartQualityCheckDialog} from './StartQualityCheckDialog';
import * as fileBrowserService from '../file-browser/fileBrowser.service';
import type {FileSpaceTarget} from '../file-browser';

vi.mock('../file-browser/fileBrowser.service', async (importActual) => ({
  ...(await importActual<typeof fileBrowserService>()),
  listFiles: vi.fn()
}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));

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

function dialog(): ReactElement {
  return (
    <QueryClientProvider client={client}>
      <StartQualityCheckDialog
        spaces={spaces}
        onStart={() => {}}
        onCancel={() => {}}
      />
    </QueryClientProvider>
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
