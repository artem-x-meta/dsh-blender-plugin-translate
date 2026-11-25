import type { PlanCallDeps } from './index.js';
import type { GuiRoute } from './routes.generated.js';
export type RouteDecision = {
    matched: true;
    result: Promise<unknown>;
} | {
    matched: false;
};
export declare const hit: (result: unknown) => RouteDecision;
export declare const miss: () => RouteDecision;
/** evidence: inject the default view.path first, then go through the contract layer */
export declare function prepareEvidencePayload(E: PlanCallDeps, o: string, payload: unknown): Promise<unknown>;
/** Generic: dispatch op to the kernel module on the Blender side via dispatch(op, json) */
export declare function dispatchViaKernelModule(E: PlanCallDeps, ensure: () => Promise<unknown>, api: string, subOp: string, payload: unknown, timeoutMs: number): Promise<unknown>;
/** Matching/slicing convention shared by the generated tables: exact rows match op exactly, prefix rows match on prefix. */
export declare function routeMatches(route: GuiRoute, o: string): boolean;
/** Pick the call form by the kind of the generated row; api/strip/sub/preload/timeout always come from config/routing.json. */
export declare function handleRoute(E: PlanCallDeps, route: GuiRoute, o: string, payload: unknown): Promise<unknown>;
export declare function routeMainPlanOps(E: PlanCallDeps, o: string, payload: unknown): Promise<RouteDecision>;
export declare function routeModulePlanOps(E: PlanCallDeps, o: string, payload: unknown): Promise<RouteDecision>;
