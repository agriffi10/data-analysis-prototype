import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

// The DestinationPicker inside the dialog browses folders via useFileBrowser.
vi.mock('../file-browser/useFileBrowser');

import { SaveResultsDialog } from './SaveResultsDialog';
import { normalizeCsvName } from './query.format';
import { useFileBrowser } from '../file-browser/useFileBrowser';
import type { UseFileBrowserResult } from '../file-browser/useFileBrowser';

const base: UseFileBrowserResult = {
  files: [],
  folders: [{ type: 'folder', prefix: 'alice/reports/', name: 'reports' }],
  isLoading: false,
  error: null,
  refresh: vi.fn(),
  hasMore: false,
  loadMore: vi.fn(),
  isLoadingMore: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useFileBrowser).mockReturnValue(base);
});

function renderDialog(props?: Partial<React.ComponentProps<typeof SaveResultsDialog>>) {
  const onSave = vi.fn();
  const onCancel = vi.fn();
  render(
    <SaveResultsDialog
      bucket="user-bucket"
      rootPrefix="alice/"
      rootLabel="My Files"
      defaultName="query-results-20260622-1430"
      onSave={onSave}
      onCancel={onCancel}
      {...props}
    />
  );
  return { onSave, onCancel };
}

describe('normalizeCsvName (SPEC-049)', () => {
  it('appends .csv when missing and does not double it', () => {
    expect(normalizeCsvName('report')).toBe('report.csv');
    expect(normalizeCsvName('report.csv')).toBe('report.csv');
    expect(normalizeCsvName('report.CSV')).toBe('report.CSV');
    expect(normalizeCsvName('  spaced  ')).toBe('spaced.csv');
  });
});

describe('SaveResultsDialog (SPEC-049 FR-002)', () => {
  it('saves the .csv-normalized name into the chosen destination (root)', () => {
    const { onSave } = renderDialog();
    // Default destination is the root; confirm there.
    fireEvent.click(screen.getByRole('button', { name: 'Save here' }));
    expect(onSave).toHaveBeenCalledWith({
      destPrefix: 'alice/',
      filename: 'query-results-20260622-1430.csv',
    });
  });

  it('saves into a navigated subfolder', () => {
    const { onSave } = renderDialog();
    fireEvent.click(screen.getByRole('button', { name: /open folder reports/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Save here' }));
    expect(onSave).toHaveBeenCalledWith({
      destPrefix: 'alice/reports/',
      filename: 'query-results-20260622-1430.csv',
    });
  });

  it('disables Save while the name is invalid', () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText('File name'), {
      target: { value: 'bad/name' },
    });
    expect(screen.getByRole('button', { name: 'Save here' })).toBeDisabled();
    expect(screen.getByText(/cannot contain/i)).toBeInTheDocument();
  });

  it('excludes the protected athenaresults folder from the picker', () => {
    vi.mocked(useFileBrowser).mockReturnValue({
      ...base,
      folders: [
        { type: 'folder', prefix: 'alice/athenaresults/', name: 'athenaresults' },
        { type: 'folder', prefix: 'alice/reports/', name: 'reports' },
      ],
    });
    renderDialog();
    expect(screen.queryByRole('button', { name: /open folder athenaresults/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /open folder reports/i })).toBeInTheDocument();
  });
});
