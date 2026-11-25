/** blender_rt_headless execution layer: argument validation / body assembly / sync-or-job routing (behavior identical to v2.6.2). */
import type { HostContext } from '../../host/context.js';
export declare function executeHeadless(args: Record<string, unknown>, ctx: HostContext, port: number): Promise<unknown>;
