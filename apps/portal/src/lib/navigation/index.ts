/**
 * The navigation seam: the only module a feature imports for navigation. It works under both
 * routers during the coexistence, and decides per path which one performs a navigation.
 */
export {useLocation, useNavigate, useNavigationType, useParams, useSearchParams} from './hooks';
export {Link, type LinkProps} from './Link';
export {NavLink, type NavLinkProps} from './NavLink';
export {Navigate} from './Navigate';
export {matchPath} from './matchPath';
export {NavigationProvider} from './NavigationProvider';
export {CatchAllRouter} from './CatchAllRouter';
export {AREAS, AreaRecordsContext, areaOf, routerFor, useAreaRecords} from './areas';
export type {AreaName, AreaRecord, AreaRouter} from './areas';
export type {NavigateOptions, NavigationType, NavLocation, To} from './navigation.types';
