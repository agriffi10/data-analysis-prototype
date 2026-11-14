import type {AreaRecord} from './area.types';

/** Shared spaces: the paths it serves, and which router serves them. */
export const connectionsArea: AreaRecord = {area: 'connections', paths: ['/connections'], router: 'catch-all'};
