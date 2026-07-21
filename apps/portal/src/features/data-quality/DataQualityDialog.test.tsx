import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {DataQualityDialog} from './DataQualityDialog';
import * as service from './dataQuality.service';
import type {DataQualitySpace} from './dataQuality.types';

// Integration style (react.md §21): render the real dialog over the real
// `useDataQualityCheck` and the real ToastProvider, mocking only the AWS
// service boundary. That is also why there is no separate hook test — the
// hook's behaviour (single enqueue, toast either way) is user-observable here,
// and asserting it twice would fragment the coverage it already has.
vi.mock('./dataQuality.service', () => ({enqueueQualityCheck: vi.fn()}));

const mock = vi.mocked(service);

const space: DataQualitySpace = {kind: 'personal', bucket: 'user-space', prefix: 'alice/'};

function renderDialog(over: Partial<Parameters<typeof DataQualityDialog>[0]> = {}) {
  const onClose = vi.fn();
  const result = renderWithProviders(
    <DataQualityDialog
      target={{space, location: 'alice/sales/'}}
      kind="folder"
      displayPath="sales/"
      onClose={onClose}
      {...over}
    />
  );
  return {...result, onClose};
}

beforeEach(() => {
  vi.clearAllMocks();
  mock.enqueueQualityCheck.mockResolvedValue({success: true, data: {requestId: 'req-1'}});
});

describe('DataQualityDialog', () => {
  it('names the target and promises plainly that nothing is modified', () => {
    renderDialog();
    const dialog = screen.getByRole('alertdialog', {name: 'Confirm data quality check'});
    expect(dialog).toHaveTextContent('sales/');
    expect(dialog).toHaveTextContent(/only reads/i);
    expect(dialog).toHaveTextContent(/nothing is modified, moved, or deleted/i);
    expect(dialog).toHaveTextContent(/runs in the background/i);
  });

  it('tells the user a notification will carry the result', () => {
    // The inverse of the SPEC-113 guard this replaces. That one asserted the dialog made
    // NO such promise, because nothing sent one; SPEC-114 built the producer, so the
    // promise is now true and the dialog must make it — a background check whose result
    // arrives nowhere the user is looking is the failure this whole spec exists to end.
    renderDialog();
    expect(screen.getByRole('alertdialog')).toHaveTextContent(/notification/i);
  });

  it('enqueues the check on confirm, closes, and toasts that it has started', async () => {
    const {user, onClose} = renderDialog();
    await user.click(screen.getByRole('button', {name: 'Start check'}));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(mock.enqueueQualityCheck).toHaveBeenCalledTimes(1);
    const sent = mock.enqueueQualityCheck.mock.calls[0][0];
    expect(sent).toMatchObject({space, location: 'alice/sales/'});
    // A browser-minted id keys the manifest, the results and the report.
    expect(sent.requestId).toEqual(expect.any(String));
    expect(sent.requestId).not.toBe('');
    expect(await screen.findByRole('status')).toHaveTextContent(/checking “sales”/i);
  });

  it('does not enqueue anything when cancelled', async () => {
    const {user, onClose} = renderDialog();
    await user.click(screen.getByRole('button', {name: 'Cancel'}));
    expect(onClose).toHaveBeenCalled();
    expect(mock.enqueueQualityCheck).not.toHaveBeenCalled();
  });

  it('closes on failure too, reporting it as a user-safe toast (never the raw AWS text)', async () => {
    // SPEC-106: an unrecognized raw message maps to the generic fallback. The
    // dialog closes rather than staying open — it has nothing to re-enter.
    mock.enqueueQualityCheck.mockResolvedValue({
      success: false,
      error: {message: 'AWS.SimpleQueueService.NonExistentQueue'}
    });
    const {user, onClose} = renderDialog();
    await user.click(screen.getByRole('button', {name: 'Start check'}));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/contact the administrator/i);
    expect(alert).not.toHaveTextContent(/SimpleQueueService/i);
  });

  // Scoped to what a USER can drive: both buttons go disabled. It deliberately does
  // NOT claim to cover the hook's re-entry guard — userEvent won't dispatch a click on
  // a disabled button, so this test passes with that guard deleted. The guard is
  // covered where it can actually be reached, in useDataQualityCheck.test.ts.
  it('locks both buttons while the request is in flight', async () => {
    let release: (v: {success: true; data: {requestId: string}}) => void = () => {};
    mock.enqueueQualityCheck.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      })
    );
    const {user} = renderDialog();
    await user.click(screen.getByRole('button', {name: 'Start check'}));

    const confirm = await screen.findByRole('button', {name: 'Starting…'});
    expect(confirm).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Cancel'})).toBeDisabled();
    await user.click(confirm);
    expect(mock.enqueueQualityCheck).toHaveBeenCalledTimes(1);

    release({success: true, data: {requestId: 'req-1'}});
  });
});
