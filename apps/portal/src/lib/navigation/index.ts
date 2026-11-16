/**
 * The navigation seam: the only module a feature imports for navigation. It runs on Next's App
 * Router and owns what that router lacks: history state, the navigation type and a key per entry.
 */
export {useLocation, useNavigate, useNavigationType, useParams, useSearchParams} from './hooks';
export {Link, type LinkProps} from './Link';
export {NavLink, type NavLinkProps} from './NavLink';
export {Navigate} from './Navigate';
export {matchPath} from './matchPath';
export {decodePath} from './address';
export {NavigationProvider} from './NavigationProvider';
export {AREAS, areaOf} from './areas';
export type {AreaName, AreaRecord} from './areas';
export type {NavigateOptions, NavigationType, NavLocation, To} from './navigation.types';
