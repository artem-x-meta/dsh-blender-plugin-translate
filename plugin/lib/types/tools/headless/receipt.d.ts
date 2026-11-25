/** blender_rt_headless receipt layer: job promotion / sync receipts / missing-field diagnosis / shots attachments (behavior identical to v2.6.2). */
import type { HostContext } from '../../host/context.js';
import { type ToolReceipt } from '../../headless/receipts/index.js';
export declare function runAsJob(port: number, body: Record<string, unknown>, waitS: number | null, asJob: boolean, serverBudget: number, autoJobMs: number): Promise<unknown>;
export declare function missingResultText(res: Record<string, unknown>, body: Record<string, unknown>): {
    text: string;
};
export declare function syncReceipt(bodyRes: Record<string, unknown>, res: Record<string, unknown>): ToolReceipt;
export declare function attachShots(ctx: HostContext, out: ToolReceipt, args: Record<string, unknown>): Promise<unknown[]>;
