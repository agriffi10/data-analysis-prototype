import type {AreaRecord} from './area.types';

/** Files: the paths it serves, and which router serves them. */
export const filesArea: AreaRecord = {area: 'files', paths: ['/files'], router: 'catch-all'};
