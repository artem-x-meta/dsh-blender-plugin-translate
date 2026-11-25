import type { PlanCallDeps } from './index.js';
import type { RouteDecision } from './plan-call.js';
/** The EXT table matches in the order of config/routing.json: 21 module prefixes → gui_ → render_ → contract fallback. */
export declare function routeExtRouting(E: PlanCallDeps, o: string, payload: unknown): Promise<RouteDecision>;
