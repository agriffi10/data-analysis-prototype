import {describe, it, vi, beforeEach} from 'vitest';
import {screen, cleanup} from '@testing-library/react';
import {expectNoA11yViolations, expectContainerHasNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {renderWithProviders} from '../../test/renderWithProviders';
import {CollisionPrompt} from './CollisionPrompt';
import {DestinationPicker} from './DestinationPicker';
import {UploadList} from './UploadList';
import {useUploadQueue} from './uploadQueueContext';
import type {UploadQueueContextValue} from './uploadQueueContext';
import type {UploadItem} from './upload.types';
import {listFiles} from './fileBrowser.service';
import type {SelectableItem} from './selectionContext';

/**
 * The AWS boundary, and nothing else (SPEC-154 FR-008). `DestinationPicker` renders through
 * the REAL `useFileBrowser` — the hook §21 names in its 🔴 list — so the accessibility
 * guarantee is asserted against the tree a user actually gets, folder rows and all, rather
 * than against a hand-built `UseFileBrowserResult`. A stubbed hook could return a shape the
 * component never produces and the axe pass would say nothing about the real one.
 */
vi.mock('./fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./fileBrowser.service')>()),
  listFiles: vi.fn()
}));

/**
 * `useUploadQueue` STAYS mocked, and this is the one line of justification FR-008 asks for.
 * The four states below (uploading / done / failed / collision) are INPUTS to this render,
 * not outcomes to be driven: reaching them through a real provider means performing four
 * uploads, which is an upload test with an axe assertion bolted on — and that flow is
 * SPEC-154 FR-004's subject, tested there against the real provider.
 */
vi.mock('./uploadQueueContext', () => ({useUploadQueue: vi.fn()}));

const noop = () => {};

const queueActions = {
  enqueue: vi.fn(),
  cancel: vi.fn(),
  dismiss: vi.fn(),
  resolveOverwrite: vi.fn(),
  resolveRename: vi.fn(),
  clearFinished: vi.fn()
};

function item(over: Partial<UploadItem> = {}): UploadItem {
  return {
    id: 'id-1',
    file: new File(['x'], 'a.txt'),
    bucket: 'us',
    key: 'alice/a.txt',
    status: 'uploading',
    loaded: 50,
    total: 100,
    overwrite: false,
    ...over
  };
}

function setQueue(items: UploadItem[]) {
  vi.mocked(useUploadQueue).mockReturnValue({
    items,
    ...queueActions
  } as UploadQueueContextValue);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listFiles).mockResolvedValue({
    success: true,
    data: {
      files: [],
      folders: [{type: 'folder', prefix: 'alice/backups/', name: 'backups'}],
      isTruncated: false
    }
  });
});

describe('UploadList accessibility (every state)', () => {
  it.each([
    ['uploading', item({status: 'uploading', loaded: 50, total: 100})],
    ['done', item({status: 'done', loaded: 100})],
    ['failed', item({status: 'failed', error: 'Access Denied'})],
    ['collision', item({status: 'collision'})]
  ] as const)('%s state has no violations', async (_label, queueItem) => {
    setQueue([queueItem]);
    await expectNoA11yViolations(<UploadList />, COMPONENT_AXE_OPTIONS);
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
      COMPONENT_AXE_OPTIONS
    );
  });
});

describe('DestinationPicker accessibility', () => {
  it('has no violations once the real listing has resolved', async () => {
    // The container is checked AFTER the folder row arrives, not on first paint: the real
    // hook renders a loading state first, and axing that would assert nothing about the
    // populated tree this test is named for.
    const {container} = renderWithProviders(
      <DestinationPicker
        bucket="us"
        items={[{type: 'file', key: 'alice/docs/f.txt'} satisfies SelectableItem]}
        rootPrefix="alice/"
        rootLabel="My Files"
        currentPrefix="alice/docs/"
        confirmLabel="Copy here"
        busyLabel="Copying…"
        onConfirm={noop}
        onCancel={noop}
      />
    );

    await screen.findByText('backups');

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
    cleanup();
  });
});
