import {render, screen, fireEvent, within} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {UploadList} from './UploadList';
import {useUploadQueue} from './uploadQueueContext';
import type {UploadQueueContextValue} from './uploadQueueContext';
import type {UploadItem} from './upload.types';

vi.mock('./uploadQueueContext', () => ({useUploadQueue: vi.fn()}));
const mockUseUploadQueue = vi.mocked(useUploadQueue);

const actions = {
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

function setItems(items: UploadItem[]) {
  mockUseUploadQueue.mockReturnValue({
    items,
    ...actions
  } as UploadQueueContextValue);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('UploadList', () => {
  it('renders nothing when the queue is empty', () => {
    setItems([]);
    const {container} = render(<UploadList />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a per-file progress bar + Uploading chip while uploading', () => {
    setItems([item({loaded: 50, total: 100})]);
    render(<UploadList />);
    const bar = screen.getByRole('progressbar', {name: /uploading a\.txt/i});
    expect(bar).toHaveAttribute('aria-valuenow', '50');
    expect(screen.getByText('Uploading')).toBeInTheDocument();
  });

  it('shows the Uploaded chip on a finished item', () => {
    setItems([item({status: 'done', loaded: 100})]);
    render(<UploadList />);
    expect(screen.getByText('Uploaded')).toBeInTheDocument();
  });

  it('lists uploads newest-first', () => {
    setItems([
      item({id: 'id-1', key: 'alice/first.txt', status: 'done', loaded: 100}),
      item({id: 'id-2', key: 'alice/second.txt', status: 'uploading'})
    ]);
    render(<UploadList />);
    const names = screen.getAllByText(/\.txt$/).map((el) => el.textContent);
    expect(names[0]).toBe('second.txt'); // most recently enqueued appears first
  });

  it('cancels an in-flight upload via its hover action', () => {
    setItems([item()]);
    render(<UploadList />);
    fireEvent.click(screen.getByRole('button', {name: /cancel upload of a\.txt/i}));
    expect(actions.cancel).toHaveBeenCalledWith('id-1');
  });

  it('dismisses a finished item (no cancel on a terminal row)', () => {
    setItems([item({status: 'done', loaded: 100})]);
    render(<UploadList />);
    expect(screen.queryByRole('button', {name: /cancel upload/i})).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: /dismiss a\.txt/i}));
    expect(actions.dismiss).toHaveBeenCalledWith('id-1');
  });

  it('shows the Failed chip and failure reason on a failed item', () => {
    setItems([item({status: 'failed', error: 'Access Denied'})]);
    render(<UploadList />);
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Access Denied')).toBeInTheDocument();
  });

  it('renders a collision prompt and wires Overwrite + Cancel to the queue', () => {
    setItems([item({status: 'collision'})]);
    render(<UploadList />);

    const prompt = screen.getByRole('alertdialog', {name: /already exists/i});
    fireEvent.click(within(prompt).getByRole('button', {name: /overwrite/i}));
    expect(actions.resolveOverwrite).toHaveBeenCalledWith('id-1');

    fireEvent.click(within(prompt).getByRole('button', {name: /cancel/i}));
    expect(actions.cancel).toHaveBeenCalledWith('id-1');
  });

  it('offers Clear finished only when a terminal item exists', () => {
    setItems([item({status: 'uploading'})]);
    const {rerender} = render(<UploadList />);
    expect(screen.queryByRole('button', {name: /clear finished/i})).not.toBeInTheDocument();

    setItems([item({id: 'id-2', status: 'done'})]);
    rerender(<UploadList />);
    fireEvent.click(screen.getByRole('button', {name: /clear finished/i}));
    expect(actions.clearFinished).toHaveBeenCalled();
  });
});
