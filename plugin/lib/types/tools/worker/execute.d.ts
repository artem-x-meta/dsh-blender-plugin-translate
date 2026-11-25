/** blender_rt_worker execution layer: session command forwarding + receipts (behavior identical to v2.6.2). */
import type { HostContext } from '../../host/context.js';
export declare function executeWorker(args: Record<string, unknown>, ctx: HostContext, port: number): Promise<unknown>;
