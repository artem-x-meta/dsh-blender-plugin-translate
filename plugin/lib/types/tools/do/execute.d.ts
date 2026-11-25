/** blender_rt_do execution layer: two paths, GUI /act and the persistent headless session (behaviour matches v2.6.2). */
import type { HostContext } from '../../host/context.js';
export declare function executeDo(args: Record<string, unknown>, ctx: HostContext, port: number): Promise<unknown>;
/** One interactive headless step: exec code + optional see (persistent worker; not a job / not an async turn). */
export declare function doViaSession(ctx: HostContext, port: number, opts: Record<string, unknown>): Promise<unknown>;
