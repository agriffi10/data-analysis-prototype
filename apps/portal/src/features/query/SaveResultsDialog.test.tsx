import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {SaveResultsDialog} from './SaveResultsDialog';
import {normalizeCsvName} from './query.format';
import * as fileService from '../file-browser/fileBrowser.service';
import type {FileListPage, S3FolderItem} from '../../types/s3.types';

// Integration style (react.md §21): render the REAL SaveResultsDialog → real
// Modal + real DestinationPicker → real useFileBrowser, and mock ONLY the AWS
// boundary — the file-browser listing service. The picker's folder browsing runs
// for real against the mocked listing.
vi.mock('../file-browser/fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof fileService>();
  return {...actual, listFiles: vi.fn()};
});

const mock = vi.mocked(fileService);
const ok = <T,>(data: T) => ({success: true as const, data});

const folder = (name: string, prefix: string): S3FolderItem => ({type: 'folder', prefix, name});
const listing = (folders: S3FolderItem[]): FileListPage => ({files: [], folders, isTruncated: false});

const personalSpace = {
  id: 'personal',
  label: 'My files',
  bucket: 'user-bucket',
  rootPrefix: 'alice/',
  rootLabel: 'My Files'
};
const sharedSpace = {
  id: 'salesdata',
  label: 'salesdata',
  bucket: 'shared-bucket',
  rootPrefix: 'salesdata/',
  rootLabel: 'salesdata'
};

function renderDialog(props?: Partial<React.ComponentProps<typeof SaveResultsDialog>>) {
  const onSave = vi.fn();
  const onCancel = vi.fn();
  const result = renderWithProviders(
    <SaveResultsDialog
      spaces={[personalSpace]}
      defaultName="query-results-20260622-1430"
      onSave={onSave}
      onCancel={onCancel}
      {...props}
    />
  );
  return {...result, onSave, onCancel};
}

beforeEach(() => {
  vi.clearAllMocks();
  mock.listFiles.mockResolvedValue(ok(listing([folder('reports', 'alice/reports/')])));
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('normalizeCsvName (SPEC-049)', () => {
  it('appends .csv when missing and does not double it', () => {
    expect(normalizeCsvName('report')).toBe('report.csv');
    expect(normalizeCsvName('report.csv')).toBe('report.csv');
    expect(normalizeCsvName('report.CSV')).toBe('report.CSV');
    expect(normalizeCsvName('  spaced  ')).toBe('spaced.csv');
  });
});

describe('SaveResultsDialog (SPEC-049 FR-002)', () => {
  it('saves the .csv-normalized name into the chosen root folder', async () => {
    const {user, onSave} = renderDialog();
    await user.click(await screen.findByRole('button', {name: 'Save here'}));
    expect(onSave).toHaveBeenCalledWith({
      destBucket: 'user-bucket',
      destPrefix: 'alice/',
      filename: 'query-results-20260622-1430.csv'
    });
  });

  it('saves into a navigated subfolder', async () => {
    const {user, onSave} = renderDialog();
    await user.click(await screen.findByRole('button', {name: /open folder reports/i}));
    await user.click(screen.getByRole('button', {name: 'Save here'}));
    expect(onSave).toHaveBeenCalledWith({
      destBucket: 'user-bucket',
      destPrefix: 'alice/reports/',
      filename: 'query-results-20260622-1430.csv'
    });
  });

  it('offers a space selector for shared spaces and hides it with only the personal space', async () => {
    // Personal-only: no selector.
    const {unmount} = renderDialog();
    expect(screen.queryByLabelText('Save to')).not.toBeInTheDocument();
    unmount();

    // With a shared space: pick it and save into it.
    const {user, onSave} = renderDialog({spaces: [personalSpace, sharedSpace]});
    await user.selectOptions(screen.getByLabelText('Save to'), 'salesdata');
    await user.click(await screen.findByRole('button', {name: 'Save here'}));
    expect(onSave).toHaveBeenCalledWith({
      destBucket: 'shared-bucket',
      destPrefix: 'salesdata/',
      filename: 'query-results-20260622-1430.csv'
    });
  });

  it('disables Save while the name is invalid', async () => {
    const {user} = renderDialog();
    const name = screen.getByLabelText('File name');
    await user.clear(name);
    await user.type(name, 'bad/name');
    expect(screen.getByRole('button', {name: 'Save here'})).toBeDisabled();
    expect(screen.getByText(/cannot contain/i)).toBeInTheDocument();
  });

  it('excludes the protected athenaresults folder from the picker', async () => {
    mock.listFiles.mockResolvedValue(
      ok(listing([folder('athenaresults', 'alice/athenaresults/'), folder('reports', 'alice/reports/')]))
    );
    renderDialog();
    expect(await screen.findByRole('button', {name: /open folder reports/i})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /open folder athenaresults/i})).not.toBeInTheDocument();
  });
});
