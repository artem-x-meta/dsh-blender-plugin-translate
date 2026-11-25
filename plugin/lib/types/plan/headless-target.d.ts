import type { HostContext } from '../host/context.js';
import { PLAN_HEADLESS_ALIAS, PLAN_HEADLESS_MAP } from './routes.generated.js';
import type { HeadlessTarget } from './routes.generated.js';
export { PLAN_HEADLESS_ALIAS, PLAN_HEADLESS_MAP };
export type { HeadlessTarget };
export declare function planHeadlessTarget(op: string): HeadlessTarget | null;
/** Run a plan op on the persistent worker (does not depend on the GUI addon; modules are injected into K by preload) */
export declare function planViaWorker(ctx: HostContext, port: number, op: string, payload: unknown, session?: string): Promise<Record<string, unknown>>;
/** Common plan-receipt finish: envelope + attached images (shared by GUI/headless) */
export declare function finishPlanResponse(ctx: HostContext, op: string, res: unknown, argsIn: unknown): Promise<Record<string, unknown>>;
/** Weak-model contract v2: verdict-first envelope (single line, ≤2k) — the shared convention for plan and headless */
export declare function planEnvelope(op: string, res: unknown): Record<string, unknown>;
