import { describe, it, vi, beforeEach } from 'vitest';
import {
  expectNoA11yViolations,
  COMPONENT_AXE_OPTIONS,
} from '../../test/axe';
import { CollisionPrompt } from './CollisionPrompt';
import { DestinationPicker } from './DestinationPicker';
import { UploadQueuePanel } from './UploadQueuePanel';
import { useUploadQueue } from './uploadQueueContext';
import type { UploadQueueContextValue } from './uploadQueueContext';
import type { UploadItem } from './upload.types';
import { useFileBrowser } from './useFileBrowser';
import type { UseFileBrowserResult } from './useFileBrowser';
import type { SelectableItem } from './selectionContext';

vi.mock('./uploadQueueContext', () => ({ useUploadQueue: vi.fn() }));
vi.mock('./useFileBrowser');

const noop = () => {};

const queueActions = {
  enqueue: vi.fn(),
  cancel: vi.fn(),
  dismiss: vi.fn(),
  resolveOverwrite: vi.fn(),
  resolveRename: vi.fn(),
  clearFinished: vi.fn(),
};

function item(over: Partial<UploadItem> = {}): UploadItem {
  return {
    id: 'id-1',
    file: new File(['x'], 'a.txt'),
    key: 'alice/a.txt',
    status: 'uploading',
    loaded: 50,
    total: 100,
    overwrite: false,
    ...over,
  };
}

function setQueue(items: UploadItem[]) {
  vi.mocked(useUploadQueue).mockReturnValue({
    items,
    ...queueActions,
  } as UploadQueueContextValue);
}

const browserBase: UseFileBrowserResult = {
  files: [],
  folders: [{ type: 'folder', prefix: 'alice/archive/', name: 'archive' }],
  isLoading: false,
  error: null,
  refresh: vi.fn(),
  hasMore: false,
  loadMore: vi.fn(),
  isLoadingMore: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useFileBrowser).mockReturnValue(browserBase);
});

describe('UploadQueuePanel accessibility (every state)', () => {
  it.each([
    ['uploading', item({ status: 'uploading', loaded: 50, total: 100 })],
    ['done', item({ status: 'done', loaded: 100 })],
    ['failed', item({ status: 'failed', error: 'Access Denied' })],
    ['collision', item({ status: 'collision' })],
  ] as const)('%s state has no violations', async (_label, queueItem) => {
    setQueue([queueItem]);
    await expectNoA11yViolations(<UploadQueuePanel />, COMPONENT_AXE_OPTIONS);
  });
});

describe('CollisionPrompt accessibility', () => {
  it('has no violations', async () => {
    await expectNoA11yViolations(
      <CollisionPrompt
        kind="file"
        name="report.pdf"
        onOverwrite={noop}
        onRename={noop}
        onCancel={noop}
      />,
      COMPONENT_AXE_OPTIONS,
    );
  });
});

describe('DestinationPicker accessibility', () => {
  it('has no violations', async () => {
    await expectNoA11yViolations(
      <DestinationPicker
        bucket="us"
        items={[{ type: 'file', key: 'alice/docs/f.txt' } satisfies SelectableItem]}
        rootPrefix="alice/"
        rootLabel="My Files"
        currentPrefix="alice/docs/"
        confirmLabel="Copy here"
        busyLabel="Copying…"
        onConfirm={noop}
        onCancel={noop}
      />,
      COMPONENT_AXE_OPTIONS,
    );
  });
});
