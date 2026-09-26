import {describe, expect, it, vi} from 'vitest';
import {render, screen, within} from '@testing-library/react';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {QueryDialogs} from './QueryDialogs';
import type {QuerySpace} from '../catalog/catalog.types';
import type {UseSaveQueryResult} from '../saved-queries/useSaveQuery';

/**
 * SPEC-175 FR-008 AC4, split out of `saveQuery.a11y.test.tsx` by SPEC-177: the dialog
 * itself moved to `features/saved-queries/`, but the Replace confirm is mounted by the
 * Query workspace's own `QueryDialogs`, and a saved-queries test may not reach back into
 * `features/query/` to render it.
 */

const MINE: QuerySpace = {
  id: 'personal',
  label: 'alice',
  bucket: 'user-space',
  rootPrefix: 'alice/',
  rootLabel: 'My Files'
};
const TEAM: QuerySpace = {
  id: 'project_alpha',
  label: 'project_alpha',
  bucket: 'shared-space',
  rootPrefix: 'project_alpha/',
  rootLabel: 'project_alpha'
};

const noop = () => {};

describe('Save-query confirm accessibility (SPEC-045 / SPEC-175)', () => {
  it('has no violations on the Replace confirm the collision raises', async () => {
    // Driven through `QueryDialogs`, which is where the confirm is mounted — so the pass
    // covers the markup the workspace actually renders, not a hand-built ConfirmDialog.
    const save: UseSaveQueryResult = {
      spaces: [MINE, TEAM],
      linked: undefined,
      open: false,
      openDialog: noop,
      closeDialog: noop,
      busy: false,
      error: null,
      collision: {space: TEAM, name: 'Quarterly'},
      initialName: 'Quarterly',
      initialSpace: TEAM,
      save: noop,
      confirmReplace: noop,
      cancelReplace: noop
    };
    const {container} = render(
      <QueryDialogs
        clear={{open: false, onConfirm: noop, onCancel: noop}}
        save={save}
        closing={{tab: null, onConfirm: noop, onCancel: noop}}
        tabLimit={{open: false, onDismiss: noop}}
        createView={{open: false, busy: false, targetDatabase: '', onCreate: noop, onCancel: noop}}
        drop={{target: null, shared: false, busy: false, onConfirm: noop, onCancel: noop}}
        share={{target: null, busy: false, error: null, open: vi.fn(), close: noop, submit: vi.fn()} as never}
        refresh={{target: null, busy: false, error: null, open: vi.fn(), close: noop, submit: vi.fn()} as never}
        saveResults={{open: false, spaces: [], overwritePrompt: null} as never}
      />
    );
    const confirm = await screen.findByRole('alertdialog', {name: /confirm replace saved query/i});
    expect(within(confirm).getByText(/already exists in project_alpha/)).toBeInTheDocument();

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});
