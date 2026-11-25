/** blender_rt_see execution layer: the GUI frame / custom viewpoint / headless worker channels (behavior identical to v2.6.2). */
import type { HostContext } from '../../host/context.js';
export declare function executeSee(args: Record<string, unknown>, ctx: HostContext, port: number): Promise<unknown>;
