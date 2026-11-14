import type {AreaRecord} from './area.types';

/** Query: the paths it serves, and which router serves them. */
export const queryArea: AreaRecord = {area: 'query', paths: ['/query'], router: 'catch-all'};
