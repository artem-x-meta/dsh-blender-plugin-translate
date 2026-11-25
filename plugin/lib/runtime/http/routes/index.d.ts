import type { RouteDef } from '../router.js';
import type { HttpRouteDeps } from './deps.js';
/** Public route contract (a stable set; order matches the onListening log from before the split). */
export declare const CONTRACT_ROUTES: string[];
export declare function createRoutes(E: HttpRouteDeps): RouteDef[];
