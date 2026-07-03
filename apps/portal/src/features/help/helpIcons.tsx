import type {ComponentType} from 'react';
import {BellIcon, ConnectionsIcon, DatabaseIcon, FolderIcon} from '../../components/icons';
import type {HelpIconName} from './help.types';

/** Maps a section/guide's `HelpIconName` to its inline SVG icon component. */
export const helpIcons: Record<HelpIconName, ComponentType<{className?: string}>> = {
  files: FolderIcon,
  query: DatabaseIcon,
  connections: ConnectionsIcon,
  notifications: BellIcon
};
