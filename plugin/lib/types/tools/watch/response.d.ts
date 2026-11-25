/** watch response text: two variants, headless worker results and GUI sample results (frame attachments are assembled at their own entry points). */
import type { HostContext } from '../../host/context.js';
/** The headless worker's {frames,picks,code,...} -> text + up to 6 attached frames. */
export declare function workerWatchResponse(ctx: HostContext, res: Record<string, unknown>): Promise<unknown>;
/** GUI frame-by-frame sampling -> text + evenly sampled attached frames. shots[i]={t,ms,hash,png}. */
export declare function guiWatchResponse(ctx: HostContext, shots: Array<{
    t: number;
    ms: number;
    hash: string;
    png: Uint8Array | null;
}>, parts: string[], seconds: number, fps: number): Promise<Record<string, unknown>>;
