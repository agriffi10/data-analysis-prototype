import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {screen} from '@testing-library/react';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import type {QueryClient} from '@tanstack/react-query';
import {createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {FEATURE_FLAG_DEFAULTS, featureFlagKeys} from '../feature-flags';
import {configValue} from '../../lib/runtimeConfig';
import type {FeatureFlags} from '../feature-flags';
import {SaveResultsDialog} from './SaveResultsDialog';
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

/** A client answering the flags query with the compiled-in defaults plus `overrides`. */
function clientWithFlags(overrides: Partial<FeatureFlags>): QueryClient {
  const client = createTestQueryClient();
  client.setQueryDefaults(featureFlagKeys.all, {gcTime: Infinity, staleTime: Infinity});
  client.setQueryData(featureFlagKeys.resolved(configValue('environment')), {...FEATURE_FLAG_DEFAULTS, ...overrides});
  return client;
}

function renderDialog(props?: Partial<React.ComponentProps<typeof SaveResultsDialog>>, flags?: Partial<FeatureFlags>) {
  const onSave = vi.fn();
  const onCancel = vi.fn();
  const result = renderWithProviders(
    <SaveResultsDialog
      spaces={[personalSpace]}
      defaultName="query-results-20260622-1430"
      onSave={onSave}
      onCancel={onCancel}
      {...props}
    />,
    flags ? {queryClient: clientWithFlags(flags), seedFeatureFlags: false} : undefined
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

describe('SaveResultsDialog (SPEC-049 FR-002)', () => {
  it('saves the .csv-normalized name into the chosen root folder', async () => {
    const {user, onSave} = renderDialog();
    await user.click(await screen.findByRole('button', {name: 'Save here'}));
    expect(onSave).toHaveBeenCalledWith({
      destBucket: 'user-bucket',
      destPrefix: 'alice/',
      filename: 'query-results-20260622-1430.csv',
      format: 'csv'
    });
  });

  it('saves into a navigated subfolder', async () => {
    const {user, onSave} = renderDialog();
    await user.click(await screen.findByRole('button', {name: /open folder reports/i}));
    await user.click(screen.getByRole('button', {name: 'Save here'}));
    expect(onSave).toHaveBeenCalledWith({
      destBucket: 'user-bucket',
      destPrefix: 'alice/reports/',
      filename: 'query-results-20260622-1430.csv',
      format: 'csv'
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
      filename: 'query-results-20260622-1430.csv',
      format: 'csv'
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

  it('re-extensions the name for the chosen format and announces the wait on the button', async () => {
    const {user, onSave} = renderDialog();
    // "Save here" for the copy, "Convert and save" for a conversion — the user is told a wait
    // is coming before they click rather than after.
    expect(screen.getByRole('button', {name: 'Save here'})).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Format'), 'parquet');

    const convert = await screen.findByRole('button', {name: 'Convert and save'});
    expect(screen.queryByRole('button', {name: 'Save here'})).not.toBeInTheDocument();
    await user.click(convert);
    expect(onSave).toHaveBeenCalledWith({
      destBucket: 'user-bucket',
      destPrefix: 'alice/',
      filename: 'query-results-20260622-1430.parquet',
      format: 'parquet'
    });
  });

  it('drops the format field entirely with resultsConversion off, and still saves a CSV', async () => {
    // ABSENT, not disabled — with the flag off this is the dialog it was before the format
    // choice existed, down to the button's label.
    const {user, onSave} = renderDialog(undefined, {resultsConversion: false});
    expect(screen.queryByLabelText('Format')).not.toBeInTheDocument();

    await user.click(await screen.findByRole('button', {name: 'Save here'}));
    expect(onSave).toHaveBeenCalledWith({
      destBucket: 'user-bucket',
      destPrefix: 'alice/',
      filename: 'query-results-20260622-1430.csv',
      format: 'csv'
    });
  });

  it('has no axe violations with the format select present, and keeps Enter on the name field', async () => {
    // The DRIVEN container, not a re-render: `expectNoA11yViolations` renders the element it is
    // given, which for a dialog means axe never sees the state the user is actually in.
    const {user, container, onSave} = renderDialog();
    await screen.findByRole('button', {name: 'Save here'});
    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);

    // The select is keyboard-reachable, and it introduces no Enter-to-submit path — this dialog
    // has never had one, and the button is the only way to save.
    const format = screen.getByLabelText('Format');
    format.focus();
    expect(format).toHaveFocus();
    await user.keyboard('{Enter}');
    await user.type(screen.getByLabelText('File name'), '{Enter}');
    expect(onSave).not.toHaveBeenCalled();

    // POSITIVE CONTROL. Without it the two absences above pass on a dialog that cannot save at
    // all — which is exactly how this assertion read before: Enter submits from NOWHERE here,
    // so a keystroke on any element proved nothing about the select.
    await user.click(screen.getByRole('button', {name: 'Save here'}));
    expect(onSave).toHaveBeenCalledTimes(1);
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
