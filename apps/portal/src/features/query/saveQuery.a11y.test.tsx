import {describe, expect, it, vi} from 'vitest';
import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {SaveQueryDialog} from './SaveQueryDialog';
import {QueryDialogs} from './QueryDialogs';
import type {QuerySpace} from './query.types';
import type {UseSaveQueryResult} from './useSaveQuery';

/**
 * SPEC-175 FR-008 AC4. Every pass is against the DRIVEN container — the state the user is
 * actually in — because `expectNoA11yViolations` renders afresh and would check a dialog
 * before the interaction that produced the state under test (the memory this project
 * already carries about axe and the closed state).
 */

const MINE: QuerySpace = {
  id: 'personal',
  label: 'My files',
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

describe('Save-query dialog accessibility (SPEC-045 / SPEC-175)', () => {
  it('has no violations with the space control, after the user has chosen a destination', async () => {
    const user = userEvent.setup();
    const {container} = render(
      <SaveQueryDialog
        initialName="Quarterly"
        spaces={[MINE, TEAM]}
        initialSpace={MINE}
        busy={false}
        onSave={noop}
        onCancel={noop}
      />
    );
    await user.selectOptions(screen.getByLabelText('Space'), 'project_alpha');
    // The control's label is visible and programmatically associated — the query above
    // resolves by accessible name, so a decorative label would fail here first.
    expect(screen.getByLabelText('Space')).toHaveValue('project_alpha');

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });

  it('has no violations while showing an inline write failure on the field', async () => {
    const {container} = render(
      <SaveQueryDialog
        initialName="Quarterly"
        spaces={[MINE, TEAM]}
        initialSpace={TEAM}
        error="You don’t have permission to do that."
        busy={false}
        onSave={noop}
        onCancel={noop}
      />
    );
    expect(await screen.findByRole('alert')).toBeInTheDocument();

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });

  it('has no violations in the no-writable-space state (FR-007)', async () => {
    const {container} = render(
      <SaveQueryDialog
        initialName=""
        spaces={[]}
        initialSpace={null}
        busy={false}
        onSave={noop}
        onCancel={noop}
      />
    );
    expect(screen.getByText(/There’s nowhere to save this query/)).toBeInTheDocument();

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });

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
        drop={{target: null, busy: false, onConfirm: noop, onCancel: noop}}
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
