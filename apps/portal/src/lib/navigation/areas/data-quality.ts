import type {AreaRecord} from './area.types';

/** Data quality: the runs dashboard and one run's report, and which router serves them. */
export const dataQualityArea: AreaRecord = {
  area: 'data-quality',
  paths: ['/data-quality', '/data-quality/:space/:requestId'],
  router: 'app'
};
