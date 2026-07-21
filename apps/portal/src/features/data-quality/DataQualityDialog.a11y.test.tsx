import {describe, it, vi} from 'vitest';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {ToastProvider} from '../../components/ToastProvider';
import {DataQualityDialog} from './DataQualityDialog';
import type {DataQualitySpace} from './dataQuality.types';

vi.mock('./dataQuality.service', () => ({
  enqueueQualityCheck: vi.fn().mockResolvedValue({success: true, data: {requestId: 'req-1'}})
}));

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
