import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {createRenderCounter} from '../../test/renderCounter';
import {FileBrowser} from './FileBrowser';
import {FileOpsInFlightProvider} from './FileOpsInFlightProvider';
import {UploadQueueProvider} from './UploadQueueProvider';
import * as service from './fileBrowser.service';
import type {S3FileItem} from './fileBrowser.types';

vi.mock('./fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof service>();
  return {...actual, listFiles: vi.fn(), uploadFile: vi.fn()};
});
vi.mock('../../lib/idToken', () => ({
  getIdToken: vi.fn().mockResolvedValue({success: true, data: 'id-token'})
}));
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn().mockResolvedValue({success: true, data: {version: 1, connections: []}}),
  enqueueSharedSpaceRequest: vi.fn()
}));

const mock = vi.mocked(service);
const ok = <T,>(data: T) => ({success: true as const, data});
const LISTED = 100;
const report = (label: string, value: unknown) =>
  process.env.RENDER_SCOPE_REPORT && console.log(`RENDER_SCOPE ${label} ${JSON.stringify(value)}`);

const listed = (): S3FileItem[] =>
  Array.from({length: LISTED}, (_, i) => ({
    type: 'file',
    key: `alice/f${i}.csv`,
    name: `f${i}.csv`,
    size: 2048,
    lastModified: new Date('2026-03-04T00:00:00Z')
  }));

type Held = {onProgress: (loaded: number, total: number) => void; finish: (value: unknown) => void};

describe('FileBrowser — what an upload re-renders', () => {
  let held: Held[];

  beforeEach(() => {
    vi.clearAllMocks();
    window.innerWidth = 1024;
    held = [];
    mock.listFiles.mockImplementation(async () => ok({files: listed(), folders: [], isTruncated: false}));
    mock.uploadFile.mockImplementation(((params: {onProgress: Held['onProgress']}) =>
      new Promise((finish) => {
        held.push({onProgress: params.onProgress, finish});
      })) as never);
  });

  async function renderUploading(files: number) {
    const counter = createRenderCounter();
    const rendered = renderWithProviders(
      <counter.Probe>
        <UploadQueueProvider>
          <FileOpsInFlightProvider>
            <FileBrowser
              bucket="my-bucket"
              prefix="alice/"
              rootPrefix="alice/"
              rootLabel="My Files"
              writable
              username="alice"
            />
          </FileOpsInFlightProvider>
        </UploadQueueProvider>
      </counter.Probe>
    );
    await screen.findByText(`f${LISTED - 1}.csv`);
    await rendered.user.click(await screen.findByRole('button', {name: 'Upload'}));
    const input = await screen.findByLabelText('Choose files');
    await rendered.user.upload(
      input,
      Array.from({length: files}, (_, i) => new File(['data'], `up${i}.txt`, {type: 'text/plain'}))
    );
    await waitFor(() => expect(held.length).toBe(Math.min(files, 3)));
    return {...rendered, counter};
  }

  it('measures one progress event and a repeated one', async () => {
    const {counter} = await renderUploading(30);

    counter.reset();
    act(() => held[0].onProgress(10, 100));
    report('upload.progressEvent', counter.read());

    counter.reset();
    act(() => held[0].onProgress(10, 100));
    report('upload.repeatedProgressEvent', counter.read());

    counter.reset();
    act(() => {
      for (let i = 0; i < 60; i += 1) held[0].onProgress(11 + i, 100);
    });
    report('upload.sixtyEventsInOneTask', counter.read());
    expect(true).toBe(true);
  });

  it('measures the listing reads a batch of small files costs', async () => {
    const files = 30;
    await renderUploading(files);
    mock.listFiles.mockClear();
    for (let done = 0; done < files; done += 1) {
      await waitFor(() => expect(held.length).toBeGreaterThan(done));
      await act(async () => held[done].finish(ok({key: `alice/up${done}.txt`})));
    }
    await waitFor(() => expect(screen.getAllByText('Uploaded').length).toBe(files));
    report('upload.listingReadsForBatch', {files, listFiles: mock.listFiles.mock.calls.length});
    expect(true).toBe(true);
  });
});
