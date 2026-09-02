import type {ReactNode} from 'react';
import {Drawer} from '../../components/Drawer';

type Props = {
  open: boolean;
  onClose: () => void;
  destinationLabel?: string; // current folder the upload targets
  children: ReactNode;
};

/**
 * Right slide-over hosting the upload flow (dropzone + collision + errors). A thin
 * wrapper over the shared Drawer; the destination hint sits beside the title and
 * the body uses slightly larger spacing for the dropzone sections.
 */
export function UploadDrawer({open, onClose, destinationLabel, children}: Props) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Upload"
      ariaLabel="Upload files"
      closeLabel="Close upload panel"
      bodyClassName="gap-4"
      headerAccessory={
        destinationLabel ? (
          <span className="min-w-0 truncate text-sm text-text-3">to {destinationLabel}</span>
        ) : undefined
      }>
      {children}
    </Drawer>
  );
}
