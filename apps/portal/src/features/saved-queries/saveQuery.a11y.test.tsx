import {describe, expect, it} from 'vitest';
import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {SaveQueryDialog} from './SaveQueryDialog';
import type {QuerySpace} from '../catalog/catalog.types';

/**
 * SPEC-175 FR-008 AC4. Every pass is against the DRIVEN container — the state the user is
 * actually in — because `expectNoA11yViolations` renders afresh and would check a dialog
 * before the interaction that produced the state under test (the memory this project
 * already carries about axe and the closed state).
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
});
