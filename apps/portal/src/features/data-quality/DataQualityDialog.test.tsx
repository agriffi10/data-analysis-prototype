import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {DataQualityDialog} from './DataQualityDialog';
import {COMPONENT_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import {ToastProvider} from '../../components/ToastProvider';
import type {DataQualitySpace} from './dataQuality.types';
import * as service from './dataQuality.service';

vi.mock('./dataQuality.service', () => ({
  enqueueQualityCheck: vi.fn().mockResolvedValue({success: true, data: {requestId: 'req-1'}})
}));

describe('DataQualityDialog', () => {
  // Integration style (react.md §21): render the real dialog over the real
  // `useDataQualityCheck` and the real ToastProvider, mocking only the AWS
  // service boundary. The hook's own file tests the ONE behaviour a component test
  // structurally cannot reach (two starts before the first resolves); everything
  // user-observable is asserted here and not repeated there.

  const mock = vi.mocked(service);

  const space: DataQualitySpace = {kind: 'personal', bucket: 'user-space', prefix: 'alice/'};

  function renderDialog(over: Partial<Parameters<typeof DataQualityDialog>[0]> = {}) {
    const onClose = vi.fn();
    const onStarted = vi.fn();
    const result = renderWithProviders(
      <DataQualityDialog
        target={{space, location: 'alice/sales/'}}
        kind="folder"
        displayPath="sales/"
        onClose={onClose}
        onStarted={onStarted}
        {...over}
      />
    );
    return {...result, onClose, onStarted};
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
      const {user, onClose, onStarted} = renderDialog();
      await user.click(screen.getByRole('button', {name: 'Start check'}));

      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
      expect(onStarted).toHaveBeenCalledTimes(1);
      // `onStarted` fires BEFORE `onClose`: the Files browser hangs its deselect off the first,
      // and a close that came first would deselect nothing.
      expect(onStarted.mock.invocationCallOrder[0]).toBeLessThan(onClose.mock.invocationCallOrder[0]);
      expect(mock.enqueueQualityCheck).toHaveBeenCalledTimes(1);
      const sent = mock.enqueueQualityCheck.mock.calls[0][0];
      expect(sent).toMatchObject({space, location: 'alice/sales/'});
      // A browser-minted id keys the manifest, the results and the report.
      expect(sent.requestId).toEqual(expect.any(String));
      expect(sent.requestId).not.toBe('');
      expect(await screen.findByRole('status')).toHaveTextContent(/checking “sales”/i);
    });

    it('does not enqueue anything when cancelled', async () => {
      const {user, onClose, onStarted} = renderDialog();
      await user.click(screen.getByRole('button', {name: 'Cancel'}));
      expect(onClose).toHaveBeenCalled();
      expect(mock.enqueueQualityCheck).not.toHaveBeenCalled();
      // The Files browser hangs its deselect off this — a cancel must not fire it.
      expect(onStarted).not.toHaveBeenCalled();
    });

    it('signals onStarted only when the request was actually enqueued', async () => {
      mock.enqueueQualityCheck.mockResolvedValue({success: false, error: {message: 'nope'}});
      const {user, onStarted, onClose} = renderDialog();
      await user.click(screen.getByRole('button', {name: 'Start check'}));
      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
      expect(onStarted).not.toHaveBeenCalled();
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

      await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
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

      // Settle the in-flight request inside `act`: releasing it re-renders the dialog,
      // and letting that land after the test body ends is what React warns about.
      await act(async () => {
        release({success: true, data: {requestId: 'req-1'}});
      });
    });
  });
});

// ─── from DataQualityDialog.a11y.test.tsx ───
// One registration for the file: vitest hoists every `vi.mock`, so a second one here
// would silently win over the first rather than scope to its own section. The default
// resolution is what the a11y cases need; the behaviour cases set their own per test.

describe('DataQualityDialog.a11y', () => {
  const space: DataQualitySpace = {kind: 'personal', bucket: 'user-space', prefix: 'alice/'};

  // COMPONENT_AXE_OPTIONS: the dialog renders outside any landmark, so the `region`
  // rule is off (SPEC-045). ToastProvider is the hook's only other requirement.
  const dialog = (kind: 'file' | 'folder', displayPath: string) => (
    <ToastProvider>
      <DataQualityDialog
        target={{space, location: `alice/${displayPath}`}}
        kind={kind}
        displayPath={displayPath}
        onClose={() => {}}
        onStarted={() => {}}
      />
    </ToastProvider>
  );

  describe('DataQualityDialog a11y', () => {
    it('has no axe violations for a folder target', async () => {
      await expectNoA11yViolations(dialog('folder', 'sales/'), COMPONENT_AXE_OPTIONS);
    });

    it('has no axe violations for a file target on a narrow viewport', async () => {
      Object.defineProperty(window, 'innerWidth', {value: 400, writable: true, configurable: true});
      try {
        await expectNoA11yViolations(dialog('file', 'sales.csv'), COMPONENT_AXE_OPTIONS);
      } finally {
        Object.defineProperty(window, 'innerWidth', {value: 1024, writable: true, configurable: true});
      }
    });
  });
});
