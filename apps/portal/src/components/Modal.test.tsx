import {describe, expect, it, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../test/renderWithProviders';
import {Modal} from './Modal';

describe('Modal — backdrop dismissal', () => {
  function renderModal() {
    const onDismiss = vi.fn();
    const rendered = renderWithProviders(
      <Modal
        ariaLabel="Rename file"
        onDismiss={onDismiss}>
        <label>
          Name
          <input defaultValue="report.csv" />
        </label>
      </Modal>
    );
    const panel = screen.getByRole('dialog', {name: 'Rename file'});
    return {...rendered, onDismiss, panel, scrim: panel.parentElement!};
  }

  it('stays open when a drag that started inside the panel is released over the backdrop', async () => {
    const {user, onDismiss, scrim} = renderModal();

    await user.pointer([
      {keys: '[MouseLeft>]', target: screen.getByRole('textbox', {name: 'Name'})},
      {target: scrim},
      {keys: '[/MouseLeft]', target: scrim}
    ]);

    expect(onDismiss).not.toHaveBeenCalled();
  });

  it('dismisses on a press and release on the backdrop itself', async () => {
    const {user, onDismiss, scrim} = renderModal();

    await user.click(scrim);

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
