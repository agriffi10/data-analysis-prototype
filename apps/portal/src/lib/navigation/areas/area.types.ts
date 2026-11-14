/** Which router serves an area's pages during the coexistence. */
export type AreaRouter = 'catch-all' | 'app';

/** Every signed-in area, by its URL segment. */
export type AreaName = 'files' | 'notifications' | 'help' | 'query' | 'explore' | 'connections' | 'data-quality';

export type AreaRecord = {
  /** The URL segment, which is also the App Router folder: `src/app/(signed-in)/<area>/`. */
  area: AreaName;
  /** The path patterns the area serves, matched whole (a trailing segment is a 404, as today). */
  paths: readonly string[];
  router: AreaRouter;
};
