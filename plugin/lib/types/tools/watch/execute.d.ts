/** watch execution layer: GUI frame-by-frame sampling; on failure or when a session is given, use the headless worker. */
import type { HostContext } from '../../host/context.js';
export declare function executeWatch(ctx: HostContext, port: number, args: Record<string, unknown>): Promise<unknown>;
