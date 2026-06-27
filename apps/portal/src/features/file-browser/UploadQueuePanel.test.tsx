import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { UploadQueuePanel } from './UploadQueuePanel';
import { useUploadQueue } from './uploadQueueContext';
import type { UploadQueueContextValue } from './uploadQueueContext';
import type { UploadItem } from './upload.types';

vi.mock('./uploadQueueContext', () => ({ useUploadQueue: vi.fn() }));
const mockUseUploadQueue = vi.mocked(useUploadQueue);

const actions = {
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

function setItems(items: UploadItem[]) {
  mockUseUploadQueue.mockReturnValue({
    items,
    ...actions,
  } as UploadQueueContextValue);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('UploadQueuePanel', () => {
  it('renders nothing when the queue is empty', () => {
    setItems([]);
    const { container } = render(<UploadQueuePanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a per-file progress bar reflecting loaded/total while uploading', () => {
    setItems([item({ loaded: 50, total: 100 })]);
    render(<UploadQueuePanel />);
    const bar = screen.getByRole('progressbar', { name: /uploading a\.txt/i });
    expect(bar).toHaveAttribute('aria-valuenow', '50');
    expect(screen.getByText('50%')).toBeInTheDocument();
  });

  it('cancels an in-flight upload via its hover action', () => {
    setItems([item()]);
    render(<UploadQueuePanel />);
    fireEvent.click(screen.getByRole('button', { name: /cancel upload of a\.txt/i }));
    expect(actions.cancel).toHaveBeenCalledWith('id-1');
  });

  it('dismisses a finished item (no cancel on a terminal row)', () => {
    setItems([item({ status: 'done', loaded: 100 })]);
    render(<UploadQueuePanel />);
    expect(screen.queryByRole('button', { name: /cancel upload/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /dismiss a\.txt/i }));
    expect(actions.dismiss).toHaveBeenCalledWith('id-1');
  });

  it('shows the failure reason as the subtext on a failed item', () => {
    setItems([item({ status: 'failed', error: 'Access Denied' })]);
    render(<UploadQueuePanel />);
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Access Denied')).toBeInTheDocument();
  });

  it('renders a collision prompt and wires Overwrite + Cancel to the queue', () => {
    setItems([item({ status: 'collision' })]);
    render(<UploadQueuePanel />);

    const prompt = screen.getByRole('alertdialog', { name: /already exists/i });
    fireEvent.click(within(prompt).getByRole('button', { name: /overwrite/i }));
    expect(actions.resolveOverwrite).toHaveBeenCalledWith('id-1');

    fireEvent.click(within(prompt).getByRole('button', { name: /cancel/i }));
    expect(actions.cancel).toHaveBeenCalledWith('id-1');
  });

  it('offers Clear finished only when a terminal item exists', () => {
    setItems([item({ status: 'uploading' })]);
    const { rerender } = render(<UploadQueuePanel />);
    expect(screen.queryByRole('button', { name: /clear finished/i })).not.toBeInTheDocument();

    setItems([item({ id: 'id-2', status: 'done' })]);
    rerender(<UploadQueuePanel />);
    fireEvent.click(screen.getByRole('button', { name: /clear finished/i }));
    expect(actions.clearFinished).toHaveBeenCalled();
  });
});
